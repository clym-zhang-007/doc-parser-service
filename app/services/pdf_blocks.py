from __future__ import annotations

import io
import json
import logging
import os
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _flatten_text_payload(payload: Any) -> str:
    """把 MinerU 等解析器返回的嵌套结构尽量转成纯文本。"""
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, (int, float, bool)):
        return str(payload)
    if isinstance(payload, dict):
        for key in ("text", "content", "markdown", "md", "plain_text"):
            v = payload.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        parts: list[str] = []
        for v in payload.values():
            t = _flatten_text_payload(v)
            if t:
                parts.append(t)
        return "\n\n".join(parts).strip()
    if isinstance(payload, (list, tuple, set)):
        parts = []
        for item in payload:
            t = _flatten_text_payload(item)
            if t:
                parts.append(t)
        return "\n\n".join(parts).strip()
    return ""


def extract_pdf_text_with_mineru(path: Path) -> tuple[str, str] | None:
    """用 MinerU 精准解析 v4 提取 PDF 文本；失败返回 None。"""

    def _http_json(
        url: str,
        *,
        method: str,
        body: dict[str, Any] | None,
        headers: dict[str, str],
        timeout: int,
    ) -> Any:
        base_headers = {"Accept": "application/json", "User-Agent": "doc-parser-service/1.0"}
        data_bytes = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={**base_headers, **headers, "Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)

    def _http_get_bytes(url: str, *, headers: dict[str, str], timeout: int) -> bytes:
        base_headers = {"Accept": "*/*", "User-Agent": "doc-parser-service/1.0"}
        req = urllib.request.Request(url, headers={**base_headers, **headers}, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    def _http_put_file(url: str, *, file_path: Path, timeout: int) -> None:
        with open(file_path, "rb") as f:
            data = f.read()
        req = urllib.request.Request(url, data=data, method="PUT")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _ = resp.read()

    token = os.getenv("MinerU_API_KEY") or os.getenv("MINERU_API_KEY") or os.getenv("MINERU_TOKEN")
    logger.info(
        "mineru pdf: token_present=%s (MinerU_API_KEY=%s, MINERU_API_KEY=%s, MINERU_TOKEN=%s)",
        bool(token),
        bool(os.getenv("MinerU_API_KEY")),
        bool(os.getenv("MINERU_API_KEY")),
        bool(os.getenv("MINERU_TOKEN")),
    )
    if not token:
        logger.warning("mineru v4 skipped: missing token")
        return None

    try:
        size = path.stat().st_size
    except OSError:
        size = None

    try:
        if size is not None and size > 200 * 1024 * 1024:
            logger.warning("mineru v4 skip: file too large (%s bytes): %s", size, path)
            return None

        api_base = os.getenv("MINERU_V4_API_BASE", "https://mineru.net/api/v4")
        batch_url = f"{api_base}/file-urls/batch"
        headers = {"Authorization": f"Bearer {token}"}
        data_id = f"doc-parser-{int(time.time())}"
        payload: dict[str, Any] = {
            "files": [{"name": path.name, "data_id": data_id, "is_ocr": False}],
            "model_version": os.getenv("MINERU_MODEL_VERSION", "vlm"),
            "language": os.getenv("MINERU_LANGUAGE", "ch"),
            "enable_table": True,
            "enable_formula": True,
        }
        logger.info(
            "mineru v4 submit: %s model=%s lang=%s",
            path.name,
            payload["model_version"],
            payload["language"],
        )
        created = _http_json(batch_url, method="POST", body=payload, headers=headers, timeout=30)
        if isinstance(created, dict):
            logger.info(
                "mineru v4 create resp: code=%s msg=%s trace_id=%s",
                created.get("code"),
                created.get("msg"),
                created.get("trace_id"),
            )
        if not isinstance(created, dict) or created.get("code") != 0:
            logger.warning("mineru v4 create batch failed: %s", str(created)[:500])
            return None

        batch_id = created.get("data", {}).get("batch_id")
        urls = created.get("data", {}).get("file_urls") or []
        if not (batch_id and urls and isinstance(urls, list) and isinstance(urls[0], str)):
            logger.warning("mineru v4 create batch missing upload url or batch id")
            return None

        logger.info("mineru v4 upload: batch_id=%s", batch_id)
        _http_put_file(urls[0], file_path=path, timeout=120)
        logger.info("mineru v4 upload complete: batch_id=%s", batch_id)

        poll_url = f"{api_base}/extract-results/batch/{batch_id}"
        timeout_sec = float(os.getenv("MINERU_V4_TIMEOUT_SEC", "300"))
        interval = float(os.getenv("MINERU_V4_POLL_SEC", "3"))
        deadline = time.time() + timeout_sec
        logger.info(
            "mineru v4 poll: timeout_sec=%s interval_sec=%s url=%s",
            timeout_sec,
            interval,
            poll_url,
        )
        while time.time() < deadline:
            status = _http_json(poll_url, method="GET", body=None, headers=headers, timeout=30)
            results = status.get("data", {}).get("extract_result") if isinstance(status, dict) else None
            if isinstance(status, dict):
                logger.info(
                    "mineru v4 poll resp: code=%s msg=%s trace_id=%s has_results=%s",
                    status.get("code"),
                    status.get("msg"),
                    status.get("trace_id"),
                    isinstance(results, list) and len(results) > 0,
                )
            if isinstance(results, list) and results:
                r0 = results[0]
                st = r0.get("state")
                logger.info("mineru v4 poll state: %s", st)
                if st == "failed":
                    logger.warning("mineru v4 failed: %s", r0.get("err_msg"))
                    return None
                if st == "done":
                    zip_url = r0.get("full_zip_url")
                    if not zip_url:
                        logger.warning("mineru v4 done without full_zip_url")
                        return None
                    logger.info("mineru v4 done: downloading zip")
                    zbytes = _http_get_bytes(zip_url, headers={}, timeout=120)
                    with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
                        name = None
                        for n in zf.namelist():
                            if n.endswith("full.md"):
                                name = n
                                break
                        if not name:
                            for n in zf.namelist():
                                if n.lower().endswith(".md"):
                                    name = n
                                    break
                        if not name:
                            logger.warning("mineru v4 zip missing markdown file")
                            return None
                        md = zf.read(name).decode("utf-8", errors="replace").strip()
                        return (md, f"mineru.v4.{payload['model_version']}") if md else None
            time.sleep(interval)

        logger.warning("mineru v4 poll timeout after %ss (batch_id=%s)", timeout_sec, batch_id)
        return None
    except urllib.error.HTTPError as exc:
        logger.warning("mineru v4 http error: %s %s", exc.code, exc.reason)
        return None
    except Exception:
        logger.exception("mineru v4 api failed for %s", path)
        return None
