from __future__ import annotations

import re
from typing import Any

# 各分块策略共享的大小治理参数（改此处即可）
BLOCK_COALESCE_MIN_CHARS = 150
BLOCK_COALESCE_MAX_CHARS = 800


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _block_char_count(b: dict[str, Any]) -> int:
    t = b.get("text")
    return len(t) if isinstance(t, str) else 0


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


def coalesce_small_blocks(
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


def split_blocks_simple(text: str) -> list[dict[str, Any]]:
    """按空行分段为 paragraph 块（V1 兜底简化版）。"""
    parts = [p.strip() for p in normalize_newlines(text).split("\n\n") if p.strip()]
    if not parts and text.strip():
        parts = [text.strip()]
    return [{"type": "paragraph", "text": p, "index": i} for i, p in enumerate(parts)]

