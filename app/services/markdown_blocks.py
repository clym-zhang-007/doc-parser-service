from __future__ import annotations

import re
from typing import Any

from .blocks_coalesce import coalesce_small_blocks, normalize_newlines


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


def split_blocks_markdown(text: str) -> list[dict[str, Any]]:
    """Markdown 分块：标题 / 段落 / 代码 / 分隔线 / 列表 / 引用 / 表格 / 独立行链接与图片（v4）。"""
    t = normalize_newlines(text)
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
    return coalesce_small_blocks(blocks)

