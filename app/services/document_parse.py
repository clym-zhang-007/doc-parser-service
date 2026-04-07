"""使用 LlamaIndex（SimpleDirectoryReader）抽取文档文本，并组装 V1 基线结果结构。"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


BLOCKS_SCHEMA_VERSION = "1.5"

# 各策略传入 _coalesce_small_blocks 的默认阈值（改此处即可，勿只改单一 return 行）
BLOCK_COALESCE_MIN_CHARS = 200
BLOCK_COALESCE_MAX_CHARS = 800


def _block_char_count(b: dict[str, Any]) -> int:
    """块主体字符数（与块内 `text` 对齐），便于粗算 token。"""
    t = b.get("text")
    return len(t) if isinstance(t, str) else 0


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _split_oversize_segment(s: str, limit: int) -> list[str]:
    """将仍超过 limit 的单段再切分（无可用软边界时按字数硬切）。"""
    t = s.strip()
    if not t:
        return []
    if len(t) <= limit:
        return [t]
    out: list[str] = []
    i = 0
    n = len(t)
    while i < n:
        end = min(i + limit, n)
        if end < n:
            window = t[i:end]
            br = max(window.rfind("\n"), window.rfind(" "))
            if br > max(8, limit // 4):
                end = i + br
        chunk = t[i:end].strip()
        if chunk:
            out.append(chunk)
        i = end
        while i < n and t[i] in " \n":
            i += 1
    return out


def _coalesce_small_blocks(
    blocks: list[dict[str, Any]],
    *,
    min_chars: int = BLOCK_COALESCE_MIN_CHARS,
    max_chars: int = BLOCK_COALESCE_MAX_CHARS,
) -> list[dict[str, Any]]:
    """通用块大小治理：合并过小块、切分过大块（保守策略，避免破坏结构）。"""

    def split_large(text: str) -> list[str]:
        t = text.strip()
        if len(t) <= max_chars:
            return [t] if t else []
        # 优先按空行切，再按句号切，尽量保持语义边界
        parts = [p.strip() for p in t.split("\n\n") if p.strip()]
        if len(parts) == 1:
            parts = [p.strip() for p in re.split(r"(?<=[。！？.!?])\s+", t) if p.strip()] or [t]
        flat: list[str] = []
        for p in parts:
            flat.extend(_split_oversize_segment(p, max_chars))
        parts = flat
        chunks: list[str] = []
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
        # 整块列表 / 表格 / 独立链接与图片不再按句切，避免破坏结构
        if b.get("type") in ("list", "table", "link", "image"):
            expanded.append(dict(b))
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
            # 结构块不合并、也不被短段落吞并
            if b.get("type") in (
                "heading",
                "code",
                "separator",
                "list",
                "list_item",
                "blockquote",
                "table",
                "link",
                "image",
            ):
                merged.append({**b, "text": text})
                continue
            if prev.get("type") in (
                "heading",
                "code",
                "separator",
                "list",
                "list_item",
                "blockquote",
                "table",
                "link",
                "image",
            ):
                merged.append({**b, "text": text})
                continue
            glue_len = len(prev_text) + 2 + len(text)
            # 尽量并到同类型块里（不得超过 max_chars，否则大块切分被合并抵消）
            if prev.get("type") == b.get("type"):
                if glue_len <= max_chars:
                    prev["text"] = (prev_text + "\n\n" + text).strip()
                    continue
                merged.append({**b, "text": text})
                continue
            # 否则也并到上一个块，减少碎片
            if glue_len <= max_chars:
                prev["text"] = (prev_text + "\n\n" + text).strip()
                continue
            merged.append({**b, "text": text})
            continue
        merged.append({**b, "text": text})

    # 3) 重建 index，并写出 char_count（各策略均经此函数出口）
    out: list[dict[str, Any]] = []
    for i, b in enumerate(merged):
        nb = {**b, "index": i}
        nb["char_count"] = _block_char_count(nb)
        out.append(nb)
    return out


def _split_blocks_simple(text: str) -> list[dict[str, Any]]:
    """按空行分段为 paragraph 块（V1 兜底简化版）。"""
    parts = [p.strip() for p in _normalize_newlines(text).split("\n\n") if p.strip()]
    if not parts and text.strip():
        parts = [text.strip()]
    return [{"type": "paragraph", "text": p, "index": i} for i, p in enumerate(parts)]


def _merge_consecutive_list_runs(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将连续、同有序/无序的一组 list_item 合成一块 list，减轻过碎语义块。"""
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b.get("type") != "list_item":
            out.append(b)
            i += 1
            continue
        ordered = bool(b.get("ordered"))
        texts = [str(b.get("text") or "").strip()]
        j = i + 1
        while j < len(blocks):
            nxt = blocks[j]
            if nxt.get("type") != "list_item" or bool(nxt.get("ordered")) != ordered:
                break
            texts.append(str(nxt.get("text") or "").strip())
            j += 1
        texts = [t for t in texts if t]
        if j - i <= 1:
            out.append(b)
            i = j
            continue
        out.append(
            {
                "type": "list",
                "ordered": ordered,
                "items": texts,
                "text": "\n".join(texts),
                "index": -1,
            }
        )
        i = j
    return out


_RE_MD_STANDALONE_IMAGE = re.compile(r"^!\[([^\]]*)\]\(\s*([^)]+?)\s*\)$")
_RE_MD_STANDALONE_LINK = re.compile(r"^\[([^\]]*)\]\(\s*([^)]+?)\s*\)$")


def _gfm_split_pipe_row(s: str) -> list[str]:
    s = s.strip()
    if not s.startswith("|"):
        return []
    s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_gfm_table_separator_line(s: str) -> bool:
    s = s.strip()
    if not s.startswith("|"):
        return False
    cells = _gfm_split_pipe_row(s)
    if not cells:
        return False
    for c in cells:
        t = re.sub(r"\s+", "", c)
        if not re.match(r"^:?-{3,}:?$", t):
            return False
    return True


def _is_gfm_table_row_line(s: str) -> bool:
    s = s.strip()
    return s.startswith("|") and s.count("|") >= 2


def _try_consume_gfm_table(lines: list[str], i: int) -> tuple[list[str] | None, int]:
    """识别 GFM 管道表：首行表头 + 次行分隔线，后续为数据行，遇空行或非表行结束。"""
    if i + 1 >= len(lines):
        return None, i
    a, b = lines[i].strip(), lines[i + 1].strip()
    if not _is_gfm_table_row_line(a) or not _is_gfm_table_separator_line(b):
        return None, i
    chunk = [lines[i], lines[i + 1]]
    j = i + 2
    while j < len(lines):
        raw = lines[j]
        if not raw.strip():
            break
        st = raw.strip()
        if not _is_gfm_table_row_line(st):
            break
        if _is_gfm_table_separator_line(st):
            break
        chunk.append(lines[j])
        j += 1
    return chunk, j


def _gfm_table_rows_from_lines(table_lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for ln in table_lines:
        st = ln.strip()
        if _is_gfm_table_separator_line(st):
            continue
        rows.append(_gfm_split_pipe_row(st))
    return rows


def _split_blocks_markdown(text: str) -> list[dict[str, Any]]:
    """Markdown 分块：标题 / 段落 / 代码 / 分隔线 / 列表 / 引用 / 表格 / 独立行链接与图片（v4）。"""
    t = _normalize_newlines(text)
    lines = t.split("\n")
    blocks: list[dict[str, Any]] = []

    in_code = False
    code_fence = ""
    buf: list[str] = []
    quote_buf: list[str] = []

    _re_hr = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
    _re_list_u = re.compile(r"^\s*[-*+]\s+(.+)$")
    _re_list_o = re.compile(r"^\s*(\d+)[.)]\s+(.+)$")

    def flush_paragraph() -> None:
        nonlocal buf
        content = "\n".join(buf).strip()
        buf = []
        if content:
            blocks.append({"type": "paragraph", "text": content, "index": -1})

    def flush_blockquote() -> None:
        nonlocal quote_buf
        if not quote_buf:
            return
        inner = "\n".join(quote_buf).strip()
        quote_buf = []
        if inner:
            blocks.append({"type": "blockquote", "text": inner, "index": -1})

    def flush_code(code_lines: list[str]) -> None:
        content = "\n".join(code_lines).strip("\n")
        if content.strip():
            blocks.append({"type": "code", "text": content, "index": -1})

    code_buf: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m_fence = re.match(r"^(\s*)(```+|~~~+)(.*)$", line)
        if m_fence:
            fence = m_fence.group(2)
            if not in_code:
                flush_paragraph()
                flush_blockquote()
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
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        if not line.strip():
            flush_paragraph()
            flush_blockquote()
            i += 1
            continue

        m_quote = re.match(r"^\s*>\s?(.*)$", line)
        if m_quote:
            flush_paragraph()
            quote_buf.append(m_quote.group(1))
            i += 1
            continue

        flush_blockquote()

        if _re_hr.match(line):
            flush_paragraph()
            blocks.append({"type": "separator", "text": "---", "index": -1})
            i += 1
            continue

        m_h = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m_h:
            flush_paragraph()
            level = len(m_h.group(1))
            title = m_h.group(2).strip()
            blocks.append({"type": "heading", "text": title, "level": level, "index": -1})
            i += 1
            continue

        tab_lines, j = _try_consume_gfm_table(lines, i)
        if tab_lines is not None:
            flush_paragraph()
            raw = "\n".join(tab_lines)
            rows = _gfm_table_rows_from_lines(tab_lines)
            blocks.append(
                {
                    "type": "table",
                    "text": raw,
                    "rows": rows,
                    "index": -1,
                }
            )
            i = j
            continue

        m_lo = _re_list_o.match(line)
        if m_lo:
            flush_paragraph()
            blocks.append(
                {
                    "type": "list_item",
                    "text": m_lo.group(2).strip(),
                    "ordered": True,
                    "index": -1,
                }
            )
            i += 1
            continue

        m_lu = _re_list_u.match(line)
        if m_lu:
            flush_paragraph()
            blocks.append(
                {
                    "type": "list_item",
                    "text": m_lu.group(1).strip(),
                    "ordered": False,
                    "index": -1,
                }
            )
            i += 1
            continue

        st = line.strip()
        mi = _RE_MD_STANDALONE_IMAGE.match(st)
        if mi:
            flush_paragraph()
            alt, url = mi.group(1), mi.group(2).strip()
            md = f"![{alt}]({url})"
            blocks.append(
                {
                    "type": "image",
                    "alt": alt,
                    "url": url,
                    "text": md,
                    "index": -1,
                }
            )
            i += 1
            continue

        ml = _RE_MD_STANDALONE_LINK.match(st)
        if ml:
            flush_paragraph()
            label, url = ml.group(1), ml.group(2).strip()
            md = f"[{label}]({url})"
            blocks.append(
                {
                    "type": "link",
                    "label": label,
                    "url": url,
                    "text": md,
                    "index": -1,
                }
            )
            i += 1
            continue

        buf.append(line)
        i += 1

    flush_paragraph()
    flush_blockquote()
    if in_code and code_buf:
        flush_code(code_buf)

    blocks = _merge_consecutive_list_runs(blocks)
    # markdown 小块合并时避免动结构块；最大块仍做保守切分
    return _coalesce_small_blocks(blocks)


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
    return _coalesce_small_blocks(blocks)


def split_blocks(text: str, file_type: str) -> tuple[list[dict[str, Any]], str]:
    """按 file_type 选择分块策略；返回 (blocks, strategy_name)。"""
    ft = (file_type or "").lower()
    if ft == "markdown":
        return _split_blocks_markdown(text), "markdown.heading_list_v4"
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
    text = _normalize_newlines(text)
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
