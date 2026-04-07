from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Iterator

from .blocks_coalesce import coalesce_small_blocks


def _merge_consecutive_list_runs(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将连续、同 ordered 且同 level 的 list_item 合成一块 list。"""
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b.get("type") != "list_item":
            out.append(b)
            i += 1
            continue
        ordered = bool(b.get("ordered"))
        level = int(b.get("level") or 0)
        texts = [str(b.get("text") or "").strip()]
        j = i + 1
        while j < len(blocks):
            nxt = blocks[j]
            if nxt.get("type") != "list_item":
                break
            if bool(nxt.get("ordered")) != ordered:
                break
            if int(nxt.get("level") or 0) != level:
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
                "level": level,
                "items": texts,
                "text": "\n".join(texts),
                "source": b.get("source", "mixed"),
                "confidence": float(b.get("confidence", 0.6)),
                "index": -1,
            }
        )
        i = j
    return out


def _iter_block_items(doc: Any) -> Iterator[tuple[str, Any]]:
    """按文档顺序遍历 paragraph/table。"""
    # python-docx 的公开 API 无法按顺序拿到表格与段落，因此用底层 element.body
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield ("paragraph", Paragraph(child, doc))
        elif isinstance(child, CT_Tbl):
            yield ("table", Table(child, doc))


def _heading_level(style_name: str | None) -> int | None:
    if not style_name:
        return None
    m = re.match(r"^\s*Heading\s+(\d+)\s*$", style_name)
    if not m:
        return None
    lvl = int(m.group(1))
    if 1 <= lvl <= 6:
        return lvl
    return None


def _heuristic_heading_level(text: str) -> int | None:
    t = text.strip()
    if not t:
        return None
    if re.match(r"^第[一二三四五六七八九十百千万0-9]+[章节篇部]\b", t):
        return 1
    if re.match(r"^[（(]?[一二三四五六七八九十][）)]?[、.．]\s*\S+", t) and len(t) <= 30:
        return 2
    if re.match(r"^\d+(\.\d+){1,3}\s+\S+", t) and len(t) <= 50 and not re.search(r"[。！？.!?]$", t):
        return min(6, t.split(" ", 1)[0].count(".") + 1)
    return None


def _heuristic_list_info(text: str) -> tuple[bool, int] | None:
    t = text.strip()
    if re.match(r"^[-*•]\s+\S+", t):
        return False, 0
    if re.match(r"^\d+[.)、]\s+\S+", t):
        return True, 0
    if re.match(r"^[（(]?\d+[）)]\s+\S+", t):
        return True, 0
    if re.match(r"^[（(]?[一二三四五六七八九十]+[）)]?[、.．]\s+\S+", t):
        return True, 0
    return None


def _docx_list_info(doc: Any, paragraph: Any) -> tuple[bool, int, str, float] | None:
    """返回 (ordered, level, source, confidence)。无法判断返回 None。"""
    # 先用样式名做兜底（不少 docx 列表只有 style，没有显式 numPr）
    style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
    sn = style_name.strip().lower()
    if sn.startswith("list bullet") or sn == "bullet" or "list bullet" in sn:
        return False, 0, "style", 0.85
    if sn.startswith("list number") or sn == "number" or "list number" in sn:
        return True, 0, "style", 0.85

    p = getattr(paragraph, "_p", None)
    if p is None:
        return None
    pPr = getattr(p, "pPr", None)
    if pPr is None or pPr.numPr is None:
        return None
    numPr = pPr.numPr
    try:
        num_id = int(numPr.numId.val) if numPr.numId is not None else None
        level = int(numPr.ilvl.val) if numPr.ilvl is not None else 0
    except Exception:
        return None
    if num_id is None:
        return None

    ordered = False
    try:
        # 通过 numbering.xml 判定 numFmt：bullet vs decimal/roman/...
        numbering = doc.part.numbering_part.element  # type: ignore[attr-defined]
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        num_nodes = numbering.xpath(f".//w:num[@w:numId='{num_id}']", namespaces=ns)
        if num_nodes:
            abs_id_nodes = num_nodes[0].xpath("./w:abstractNumId", namespaces=ns)
            abs_id = abs_id_nodes[0].get(f"{{{ns['w']}}}val") if abs_id_nodes else None
            if abs_id is not None:
                abs_nodes = numbering.xpath(f".//w:abstractNum[@w:abstractNumId='{abs_id}']", namespaces=ns)
                if abs_nodes:
                    lvl_nodes = abs_nodes[0].xpath(
                        f"./w:lvl[@w:ilvl='{level}']/w:numFmt",
                        namespaces=ns,
                    )
                    if lvl_nodes:
                        fmt = lvl_nodes[0].get(f"{{{ns['w']}}}val") or ""
                        ordered = fmt.lower() != "bullet"
    except Exception:
        # 兜底：列表但无法识别格式，默认 unordered
        ordered = False
    return ordered, level, "numbering", 0.92


def _table_to_rows(tbl: Any) -> list[list[str]]:
    rows: list[list[str]] = []
    for r in tbl.rows:
        row: list[str] = []
        for c in r.cells:
            txt = (c.text or "").strip()
            row.append(re.sub(r"\s+", " ", txt))
        rows.append(row)
    # 去掉全空行
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    return rows


def _table_text_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [r + [""] * (width - len(r)) for r in rows]
    head = norm[0]
    sep = ["---"] * width
    body = norm[1:]
    lines = [
        "| " + " | ".join(head) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for r in body:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def extract_docx_text_and_blocks(path: Path) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """DOCX 结构化抽取：heading / paragraph / list_item/list / table。"""
    import docx

    doc = docx.Document(str(path))
    blocks: list[dict[str, Any]] = []
    text_parts: list[str] = []

    for kind, obj in _iter_block_items(doc):
        if kind == "paragraph":
            p = obj
            txt = (p.text or "").strip()
            if not txt:
                continue
            text_parts.append(txt)

            lvl = _heading_level(getattr(getattr(p, "style", None), "name", None))
            if lvl is not None:
                blocks.append(
                    {
                        "type": "heading",
                        "text": txt,
                        "level": lvl,
                        "source": "style",
                        "confidence": 0.95,
                        "index": -1,
                    }
                )
                continue

            li = _docx_list_info(doc, p)
            if li is not None:
                ordered, level, source, confidence = li
                blocks.append(
                    {
                        "type": "list_item",
                        "text": txt,
                        "ordered": ordered,
                        "level": level,
                        "source": source,
                        "confidence": confidence,
                        "index": -1,
                    }
                )
                continue

            h_lvl = _heuristic_heading_level(txt)
            if h_lvl is not None:
                blocks.append(
                    {
                        "type": "heading",
                        "text": txt,
                        "level": h_lvl,
                        "source": "heuristic",
                        "confidence": 0.68,
                        "index": -1,
                    }
                )
                continue

            h_li = _heuristic_list_info(txt)
            if h_li is not None:
                ordered, level = h_li
                blocks.append(
                    {
                        "type": "list_item",
                        "text": txt,
                        "ordered": ordered,
                        "level": level,
                        "source": "heuristic",
                        "confidence": 0.62,
                        "index": -1,
                    }
                )
                continue

            blocks.append({"type": "paragraph", "text": txt, "index": -1})
            continue

        if kind == "table":
            rows = _table_to_rows(obj)
            if not rows:
                continue
            text_parts.append(_table_text_markdown(rows))
            blocks.append(
                {
                    "type": "table",
                    "rows": rows,
                    "text": _table_text_markdown(rows),
                    "source": "docx_table",
                    "confidence": 0.95,
                    "index": -1,
                }
            )
            continue

    raw_blocks = _merge_consecutive_list_runs(blocks)
    source_hits = {
        "style": 0,
        "numbering": 0,
        "heuristic": 0,
        "docx_table": 0,
        "unknown": 0,
    }
    structured_total = 0
    confidence_sum = 0.0
    for b in raw_blocks:
        if b.get("type") in ("heading", "list_item", "list", "table"):
            structured_total += 1
            source = str(b.get("source") or "unknown")
            source_hits[source if source in source_hits else "unknown"] += 1
            confidence_sum += float(b.get("confidence") or 0.0)

    blocks = coalesce_small_blocks(raw_blocks)
    text = "\n\n".join([p for p in text_parts if p.strip()]).strip()
    avg_conf = (confidence_sum / structured_total) if structured_total else 0.0
    quality = {
        "structured_block_count": structured_total,
        "style_hit_ratio": (source_hits["style"] / structured_total) if structured_total else 0.0,
        "numbering_hit_ratio": (source_hits["numbering"] / structured_total) if structured_total else 0.0,
        "heuristic_hit_ratio": (source_hits["heuristic"] / structured_total) if structured_total else 0.0,
        "table_hit_ratio": (source_hits["docx_table"] / structured_total) if structured_total else 0.0,
        "avg_confidence": avg_conf,
    }
    return text, blocks, quality

