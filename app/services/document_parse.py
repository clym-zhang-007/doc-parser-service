"""使用 LlamaIndex（SimpleDirectoryReader）抽取文档文本，并组装 V1 基线结果结构。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _split_blocks(text: str) -> list[dict[str, Any]]:
    """按空行分段为 paragraph 块（V1 简化版）。"""
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not parts and text.strip():
        parts = [text.strip()]
    return [{"type": "paragraph", "text": p, "index": i} for i, p in enumerate(parts)]


def _extract_with_llamaindex(path: Path) -> tuple[str, str]:
    """用 LlamaIndex 加载单文件，返回 (全文, 解析器标识)。"""
    from llama_index.core import SimpleDirectoryReader

    reader = SimpleDirectoryReader(input_files=[str(path.resolve())])
    documents = reader.load_data()
    texts = [d.text for d in documents if getattr(d, "text", None)]
    text = "\n\n".join(texts).strip()
    return text, "llamaindex.SimpleDirectoryReader"


def _extract_fallback(path: Path, file_type: str) -> tuple[str, str]:
    """LlamaIndex 失败或返回空时的按类型回退。"""
    ft = (file_type or "").lower()
    if ft in ("txt", "markdown"):
        raw = path.read_text(encoding="utf-8", errors="replace")
        return raw, "utf8_plain"

    if ft == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages: list[str] = []
        for page in reader.pages:
            t = page.extract_text()
            pages.append(t or "")
        return "\n\n".join(pages).strip(), "pypdf.PdfReader"

    if ft == "docx":
        import docx

        doc = docx.Document(str(path))
        paras = [p.text for p in doc.paragraphs if p.text]
        return "\n\n".join(paras).strip(), "python-docx"

    raise ValueError(f"unsupported file_type for fallback: {file_type}")


def extract_text(path: Path, file_type: str) -> tuple[str, str]:
    """抽取纯文本；返回 (text, parser_used)。"""
    try:
        text, name = _extract_with_llamaindex(path)
        if text:
            return text, name
        logger.warning("llamaindex returned empty text for %s, using fallback", path)
    except Exception:
        logger.exception("llamaindex load failed for %s, using fallback", path)

    return _extract_fallback(path, file_type)


def build_v1_result(
    *,
    text: str,
    file_type: str,
    file_name: str | None,
    storage_path: str | None,
    parser_used: str,
) -> dict[str, Any]:
    """组装基线约定：document / blocks / meta / error。"""
    blocks = _split_blocks(text)
    title = Path(file_name or "document").stem
    return {
        "document": {
            "title": title,
            "text": text,
        },
        "blocks": blocks,
        "meta": {
            "file_type": file_type,
            "file_name": file_name,
            "storage_path": storage_path,
            "char_count": len(text),
            "block_count": len(blocks),
            "parser": parser_used,
        },
        "error": None,
    }


def parse_stored_file(
    *,
    path: Path,
    file_type: str,
    file_name: str | None,
    storage_path: str | None,
) -> dict[str, Any]:
    """解析已落盘文件，返回可写入 result_json 的字典。"""
    text, parser_used = extract_text(path, file_type)
    return build_v1_result(
        text=text,
        file_type=file_type,
        file_name=file_name,
        storage_path=storage_path,
        parser_used=parser_used,
    )


def build_error_result(
    *,
    code: str,
    message: str,
    file_type: str | None = None,
    file_name: str | None = None,
    storage_path: str | None = None,
) -> dict[str, Any]:
    """失败时仍返回统一外壳，便于前端只解析一种 JSON 形状。"""
    return {
        "document": None,
        "blocks": [],
        "meta": {
            "file_type": file_type,
            "file_name": file_name,
            "storage_path": storage_path,
        },
        "error": {"code": code, "message": message},
    }
