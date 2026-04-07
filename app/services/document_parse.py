"""使用 LlamaIndex（SimpleDirectoryReader）抽取文档文本，并组装 V1 基线结果结构。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .blocks_coalesce import coalesce_small_blocks, normalize_newlines, split_blocks_simple
from .markdown_blocks import split_blocks_markdown
from .txt_blocks import split_blocks_txt

logger = logging.getLogger(__name__)


BLOCKS_SCHEMA_VERSION = "1.5"


def split_blocks(text: str, file_type: str) -> tuple[list[dict[str, Any]], str]:
    """按 file_type 选择分块策略；返回 (blocks, strategy_name)。"""
    ft = (file_type or "").lower()
    if ft == "markdown":
        return split_blocks_markdown(text), "markdown.heading_list_v4"
    if ft == "txt":
        return split_blocks_txt(text), "txt.paragraph_v1"
    # 其它类型先保持旧行为
    return coalesce_small_blocks(split_blocks_simple(text)), "simple.blankline_v1"


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
    text = normalize_newlines(text)
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
