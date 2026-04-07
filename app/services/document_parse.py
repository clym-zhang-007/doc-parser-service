"""使用 LlamaIndex（SimpleDirectoryReader）抽取文档文本，并组装 V1 基线结果结构。"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


BLOCKS_SCHEMA_VERSION = "1.1"


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _coalesce_small_blocks(
    blocks: list[dict[str, Any]],
    *,
    min_chars: int = 80,
    max_chars: int = 1500,
) -> list[dict[str, Any]]:
    """通用块大小治理：合并过小块、切分过大块（保守策略，避免破坏结构）。"""

    def split_large(text: str) -> list[str]:
        t = text.strip()
        if len(t) <= max_chars:
            return [t] if t else []
        # 优先按空行切，再按句号/换行切，尽量保持语义边界
        chunks: list[str] = []
        parts = [p.strip() for p in t.split("\n\n") if p.strip()]
        if len(parts) == 1:
            parts = [p.strip() for p in re.split(r"(?<=[。！？.!?])\s+", t) if p.strip()] or [t]
        buf = ""
        for p in parts:
            if not buf:
                buf = p
                continue
            if len(buf) + 2 + len(p) <= max_chars:
                buf = f"{buf}\n\n{p}"
            else:
                chunks.append(buf)
                buf = p
        if buf:
            chunks.append(buf)
        return chunks

    # 1) 先切分大块
    expanded: list[dict[str, Any]] = []
    for b in blocks:
        text = (b.get("text") or "").strip()
        if not text:
            continue
        for part in split_large(text):
            expanded.append({**b, "text": part})

    # 2) 再合并小块（同类型优先；否则并到上一个块）
    merged: list[dict[str, Any]] = []
    for b in expanded:
        text = (b.get("text") or "").strip()
        if not merged:
            merged.append({**b, "text": text})
            continue
        prev = merged[-1]
        prev_text = (prev.get("text") or "").strip()
        if len(text) < min_chars:
            # heading/代码块不合并，避免破坏结构
            if b.get("type") in ("heading", "code"):
                merged.append({**b, "text": text})
                continue
            # 也不要把段落并进 heading/code，避免标题文本被污染
            if prev.get("type") in ("heading", "code"):
                merged.append({**b, "text": text})
                continue
            # 尽量并到同类型块里
            if prev.get("type") == b.get("type"):
                prev["text"] = (prev_text + "\n\n" + text).strip()
                continue
            # 否则也并到上一个块，减少碎片
            prev["text"] = (prev_text + "\n\n" + text).strip()
            continue
        merged.append({**b, "text": text})

    # 3) 重建 index
    out: list[dict[str, Any]] = []
    for i, b in enumerate(merged):
        out.append({**b, "index": i})
    return out


def _split_blocks_simple(text: str) -> list[dict[str, Any]]:
    """按空行分段为 paragraph 块（V1 兜底简化版）。"""
    parts = [p.strip() for p in _normalize_newlines(text).split("\n\n") if p.strip()]
    if not parts and text.strip():
        parts = [text.strip()]
    return [{"type": "paragraph", "text": p, "index": i} for i, p in enumerate(parts)]


def _split_blocks_markdown(text: str) -> list[dict[str, Any]]:
    """Markdown 分块：按标题层级 + 段落；代码块保持整体不被打散。"""
    t = _normalize_newlines(text)
    lines = t.split("\n")
    blocks: list[dict[str, Any]] = []

    in_code = False
    code_fence = ""
    buf: list[str] = []

    def flush_paragraph() -> None:
        nonlocal buf
        content = "\n".join(buf).strip()
        buf = []
        if content:
            blocks.append({"type": "paragraph", "text": content, "index": -1})

    def flush_code(code_lines: list[str]) -> None:
        content = "\n".join(code_lines).strip("\n")
        if content.strip():
            blocks.append({"type": "code", "text": content, "index": -1})

    code_buf: list[str] = []
    for line in lines:
        m_fence = re.match(r"^(\s*)(```+|~~~+)(.*)$", line)
        if m_fence:
            fence = m_fence.group(2)
            if not in_code:
                flush_paragraph()
                in_code = True
                code_fence = fence
                code_buf = [line]
            else:
                code_buf.append(line)
                # 仅在匹配同一类 fence 时关闭
                if fence[0] == code_fence[0]:
                    in_code = False
                    flush_code(code_buf)
                    code_buf = []
                    code_fence = ""
            continue

        if in_code:
            code_buf.append(line)
            continue

        m_h = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m_h:
            flush_paragraph()
            level = len(m_h.group(1))
            title = m_h.group(2).strip()
            blocks.append({"type": "heading", "text": title, "level": level, "index": -1})
            continue

        if not line.strip():
            flush_paragraph()
            continue

        buf.append(line)

    flush_paragraph()
    if in_code and code_buf:
        flush_code(code_buf)

    # markdown 小块合并时避免动 heading/code；最大块仍做保守切分
    return _coalesce_small_blocks(blocks, min_chars=80, max_chars=1500)


def _split_blocks_txt(text: str) -> list[dict[str, Any]]:
    """TXT 分块：软换行修复 + 按段落分块 + 合并碎块。"""
    t = _normalize_newlines(text)
    # 先把连续 3+ 空行压成 2 个，避免过度切块
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    lines = [ln.rstrip() for ln in t.split("\n")]

    paragraphs: list[str] = []
    cur: list[str] = []

    def is_sentence_end(s: str) -> bool:
        s = s.strip()
        return bool(re.search(r"[。！？.!?]$", s))

    def is_list_or_heading(s: str) -> bool:
        s = s.strip()
        if not s:
            return False
        # 极简规则：编号/列表符
        return bool(re.match(r"^(\d+[.)]|[-*•])\s+\S+", s))

    for ln in lines:
        if not ln.strip():
            if cur:
                paragraphs.append(" ".join(cur).strip())
                cur = []
            continue

        if not cur:
            cur.append(ln.strip())
            continue

        prev = cur[-1]
        # 如果上一行不像句末，且当前行也不像新结构开始，则视为软换行合并
        if (not is_sentence_end(prev)) and (not is_list_or_heading(ln)):
            cur[-1] = (prev + " " + ln.strip()).strip()
        else:
            cur.append(ln.strip())

    if cur:
        paragraphs.append(" ".join(cur).strip())

    blocks = [{"type": "paragraph", "text": p, "index": -1} for p in paragraphs if p.strip()]
    if not blocks and t.strip():
        blocks = [{"type": "paragraph", "text": t.strip(), "index": -1}]
    return _coalesce_small_blocks(blocks, min_chars=80, max_chars=1500)


def split_blocks(text: str, file_type: str) -> tuple[list[dict[str, Any]], str]:
    """按 file_type 选择分块策略；返回 (blocks, strategy_name)。"""
    ft = (file_type or "").lower()
    if ft == "markdown":
        return _split_blocks_markdown(text), "markdown.heading_v1"
    if ft == "txt":
        return _split_blocks_txt(text), "txt.paragraph_v1"
    # 其它类型先保持旧行为
    return _coalesce_small_blocks(_split_blocks_simple(text)), "simple.blankline_v1"


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
    blocks, block_strategy = split_blocks(text, file_type)
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
            "blocks_schema_version": BLOCKS_SCHEMA_VERSION,
            "block_strategy": block_strategy,
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
