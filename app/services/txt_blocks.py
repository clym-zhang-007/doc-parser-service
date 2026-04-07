from __future__ import annotations

import re
from typing import Any

from .blocks_coalesce import coalesce_small_blocks, normalize_newlines


def split_blocks_txt(text: str) -> list[dict[str, Any]]:
    """TXT 分块：软换行修复 + 按段落分块 + 合并碎块。"""
    t = normalize_newlines(text)
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

    blocks: list[dict[str, Any]] = [
        {"type": "paragraph", "text": p, "index": -1} for p in paragraphs if p.strip()
    ]
    if not blocks and t.strip():
        blocks = [{"type": "paragraph", "text": t.strip(), "index": -1}]
    return coalesce_small_blocks(blocks)

