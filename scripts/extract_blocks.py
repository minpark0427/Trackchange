"""
extract_blocks.py — DOCX → blocks.json + media_inventory.json + headers_footers.json

XML-level body traversal using lxml. Preserves paragraph-table-paragraph order.
Restores automatic Heading numbering from numbering.xml.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Optional

from lxml import etree

# OOXML namespaces
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _tag(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}"


W_P = _tag(W, "p")
W_TBL = _tag(W, "tbl")
W_TR = _tag(W, "tr")
W_TC = _tag(W, "tc")
W_PPR = _tag(W, "pPr")
W_PSTYLE = _tag(W, "pStyle")
W_NUMPPR = _tag(W, "numPr")
W_NUMID = _tag(W, "numId")
W_ILVL = _tag(W, "ilvl")
W_T = _tag(W, "t")
W_R = _tag(W, "r")
W_RPR = _tag(W, "rPr")
W_TCPR = _tag(W, "tcPr")
W_VMERGE = _tag(W, "vMerge")
W_GRIDSPAN = _tag(W, "gridSpan")
W_DRAWING = _tag(W, "drawing")
W_PICT = _tag(W, "pict")
W_BODY = _tag(W, "body")
W_ABSTRACTNUMID = _tag(W, "abstractNumId")
W_LVLTEXT = _tag(W, "lvlText")
W_LVL = _tag(W, "lvl")
W_ABSTRACTNUM = _tag(W, "abstractNum")
W_NUM = _tag(W, "num")
W_NUMFMT = _tag(W, "numFmt")


def _get_val(elem) -> Optional[str]:
    """Get w:val attribute."""
    return elem.get(_tag(W, "val"))


def _elem_text(elem) -> str:
    """Extract all text from a w:p or w:tc element."""
    parts = []
    for t in elem.iter(W_T):
        if t.text:
            parts.append(t.text)
    return "".join(parts)


def _has_image(p_elem) -> bool:
    """Check if paragraph contains an image."""
    return bool(
        p_elem.find(".//" + W_DRAWING) is not None
        or p_elem.find(".//" + W_PICT) is not None
    )


def _get_style(p_elem) -> Optional[str]:
    """Get paragraph style name from pStyle element (XML form: 'Heading1' no space)."""
    ppr = p_elem.find(W_PPR)
    if ppr is None:
        return None
    pstyle = ppr.find(W_PSTYLE)
    if pstyle is None:
        return None
    return _get_val(pstyle)


def _get_para_numid(p_elem) -> Optional[str]:
    """Get numId from paragraph-level numPr, or None if not present."""
    ppr = p_elem.find(W_PPR)
    if ppr is None:
        return None
    numppr = ppr.find(W_NUMPPR)
    if numppr is None:
        return None
    numid_elem = numppr.find(W_NUMID)
    if numid_elem is None:
        return None
    return _get_val(numid_elem)


def _parse_styles_outline_map(styles_xml_bytes: bytes) -> dict:
    """
    Parse styles.xml and return {styleId: heading_level} for all styles
    that have an outlineLvl < 9 (outlineLvl 9 = body text equivalent).
    heading_level = outlineLvl + 1 (so outlineLvl=0 → heading_level=1).
    """
    if not styles_xml_bytes:
        return {}
    root = etree.fromstring(styles_xml_bytes)
    W_STYLE = _tag(W, "style")
    W_STYLEID = _tag(W, "styleId")
    W_OUTLINELVL = _tag(W, "outlineLvl")

    outline_map = {}
    for style in root.findall(W_STYLE):
        sid = style.get(W_STYLEID)
        if not sid:
            continue
        ppr = style.find(W_PPR)
        if ppr is None:
            continue
        olvl = ppr.find(W_OUTLINELVL)
        if olvl is not None:
            val = _get_val(olvl)
            if val is not None:
                level = int(val)
                if level < 9:  # outlineLvl 9 = non-heading
                    outline_map[sid] = level + 1  # 0-based → 1-based
    return outline_map


def _heading_level(style: Optional[str], outline_map: Optional[dict] = None) -> Optional[int]:
    """Return heading level (1-5) if style is a Heading, else None.

    Uses outline_map from styles.xml first, then falls back to style name matching.
    """
    if not style:
        return None
    # Check outline map from styles.xml
    if outline_map and style in outline_map:
        lvl = outline_map[style]
        if 1 <= lvl <= 9:
            return lvl
    # Fallback: match "Heading1", "Heading2", etc.
    m = re.fullmatch(r"Heading(\d)", style)
    if m:
        return int(m.group(1))
    return None


def _parse_numbering(numbering_xml_bytes: bytes) -> dict:
    """
    Parse numbering.xml and return a mapping:
      abstractNum_id -> {level (0-based) -> lvlText pattern}

    Also returns: num_id -> abstractNum_id
    """
    root = etree.fromstring(numbering_xml_bytes)

    abstract_nums = {}  # abstractNumId -> {lvl -> lvlText}
    for an in root.findall(W_ABSTRACTNUM):
        an_id = an.get(_tag(W, "abstractNumId"))
        levels = {}
        for lvl in an.findall(W_LVL):
            ilvl = lvl.get(_tag(W, "ilvl"))
            lvltext_elem = lvl.find(W_LVLTEXT)
            if lvltext_elem is not None:
                levels[int(ilvl)] = _get_val(lvltext_elem) or ""
        abstract_nums[an_id] = levels

    num_map = {}  # numId -> abstractNumId
    for num in root.findall(W_NUM):
        num_id = num.get(_tag(W, "numId"))
        an_ref = num.find(W_ABSTRACTNUMID)
        if an_ref is not None:
            num_map[num_id] = _get_val(an_ref)

    return abstract_nums, num_map


def _parse_styles_heading_numid(styles_xml_bytes: bytes) -> Optional[str]:
    """
    Find the numId used by Heading styles in styles.xml.
    Returns the first numId found for Heading 1 style (all headings share same list).
    Searches by outlineLvl=0 or styleId "Heading1" to handle custom style IDs.
    """
    root = etree.fromstring(styles_xml_bytes)
    W_STYLE = _tag(W, "style")
    W_STYLEID = _tag(W, "styleId")
    W_OUTLINELVL = _tag(W, "outlineLvl")

    for style in root.findall(W_STYLE):
        sid = style.get(W_STYLEID)
        ppr = style.find(W_PPR)
        if ppr is None:
            continue

        # Check if this is Heading 1: either by styleId or outlineLvl=0
        is_heading1 = (sid == "Heading1")
        if not is_heading1:
            olvl = ppr.find(W_OUTLINELVL)
            if olvl is not None and _get_val(olvl) == "0":
                # Verify it has a name containing "heading"
                name_elem = style.find(_tag(W, "name"))
                if name_elem is not None:
                    name = _get_val(name_elem) or ""
                    if "heading" in name.lower():
                        is_heading1 = True

        if is_heading1:
            numppr = ppr.find(W_NUMPPR)
            if numppr is not None:
                numid_elem = numppr.find(W_NUMID)
                if numid_elem is not None:
                    return _get_val(numid_elem)
    return None


class NumberingRestorer:
    """
    Restores automatic heading numbers by tracking per-level counters.
    
    Rules:
    - Only applies to headings that inherit numPr from style (not paragraph-level numPr)
    - Paragraph-level numPr = front-matter heading → numbering = None
    - Heading5 has no numPr in styles.xml → numbering = None
    """

    def __init__(self, abstract_nums: dict, num_map: dict, style_numid: Optional[str]):
        self.abstract_nums = abstract_nums
        self.num_map = num_map
        self.style_numid = style_numid
        self.counters = [0] * 9  # 0-indexed levels (level 0 = H1)

        # Get the lvlText patterns for the heading list
        self.patterns = {}
        if style_numid and style_numid in num_map:
            abstract_id = num_map[style_numid]
            self.patterns = abstract_nums.get(abstract_id, {})

    def _render_number(self, level_0: int) -> str:
        """Render number string for a given 0-based level."""
        pattern = self.patterns.get(level_0, "")
        if not pattern:
            return ""
        # Replace %1, %2, ... with counter values
        result = pattern
        for i in range(level_0 + 1):
            result = result.replace(f"%{i+1}", str(self.counters[i]))
        return result

    def get_numbering(self, heading_level: int, para_numid: Optional[str], text: str = "") -> Optional[str]:
        """
        Get numbering string for a heading.
        
        heading_level: 1-5
        para_numid: numId from paragraph-level numPr (None if inherited from style)
            - "0" = front-matter (explicitly no numbering)
            - other value = paragraph overrides style, check if same abstractNum
            - None = inherits from style
        text: heading text — empty headings are skipped (don't consume a number)
        """
        # numId=0 means explicitly no numbering (front-matter)
        if para_numid == "0":
            return None

        if heading_level == 5:
            return None  # Heading5 has no numPr in styles.xml

        if not self.patterns:
            return None  # no numbering definition found

        # If paragraph has numPr with a non-zero numId, check if it maps to
        # the same abstractNum as the heading style. If so, it participates
        # in heading numbering. If different, skip.
        if para_numid is not None and para_numid != "0":
            para_abstract = self.num_map.get(para_numid)
            style_abstract = self.num_map.get(self.style_numid) if self.style_numid else None
            if para_abstract != style_abstract:
                return None  # different numbering list

        # Empty headings don't consume numbering slots in Word's rendering
        if not text.strip():
            return None

        level_0 = heading_level - 1  # convert to 0-based

        # Increment this level's counter, reset all lower levels
        self.counters[level_0] += 1
        for i in range(level_0 + 1, 9):
            self.counters[i] = 0

        return self._render_number(level_0)


def _extract_table(tbl_elem) -> dict:
    """Extract table block with cell text and merge info."""
    rows = []
    for tr in tbl_elem.findall(".//" + W_TR):
        # Only direct w:tc children of this w:tr (not nested tables)
        cells = []
        for tc in tr:
            if tc.tag != W_TC:
                continue
            # gridSpan
            tcpr = tc.find(W_TCPR)
            grid_span = 1
            vmerge = None
            if tcpr is not None:
                gs_elem = tcpr.find(W_GRIDSPAN)
                if gs_elem is not None:
                    try:
                        grid_span = int(_get_val(gs_elem) or "1")
                    except ValueError:
                        grid_span = 1
                vm_elem = tcpr.find(W_VMERGE)
                if vm_elem is not None:
                    vm_val = _get_val(vm_elem)
                    vmerge = "restart" if vm_val == "restart" else "continue"
            cell_text = _elem_text(tc)
            cells.append({
                "text": cell_text,
                "gridSpan": grid_span,
                "vMerge": vmerge,
            })
        if cells:
            rows.append({"cells": cells})
    return {"rows": rows}


def _extract_media_inventory(docx_path: str) -> dict:
    """Extract SHA-256 hashes of all media files in the DOCX."""
    inventory = {}
    with zipfile.ZipFile(docx_path, "r") as z:
        for name in z.namelist():
            if name.startswith("word/media/"):
                data = z.read(name)
                sha256 = hashlib.sha256(data).hexdigest()
                inventory[name] = {
                    "sha256": sha256,
                    "size": len(data),
                }
    return inventory


def _extract_headers_footers(docx_path: str) -> dict:
    """Extract text from header/footer XML parts."""
    result = {}
    with zipfile.ZipFile(docx_path, "r") as z:
        for name in z.namelist():
            if re.match(r"word/(header|footer)\d*\.xml", name):
                data = z.read(name)
                root = etree.fromstring(data)
                text = " ".join(
                    t.text for t in root.iter(W_T) if t.text
                ).strip()
                result[name] = {"text": text}
    return result


def extract_blocks(docx_path: str, out_dir: str):
    """
    Main extraction function.
    Writes blocks.json, media_inventory.json, headers_footers.json to out_dir.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Read numbering and styles XML from inside the DOCX (ZIP)
    with zipfile.ZipFile(docx_path, "r") as z:
        numbering_bytes = z.read("word/numbering.xml") if "word/numbering.xml" in z.namelist() else None
        styles_bytes = z.read("word/styles.xml") if "word/styles.xml" in z.namelist() else None
        doc_bytes = z.read("word/document.xml")

    # Parse numbering and styles
    abstract_nums, num_map = {}, {}
    style_numid = None
    outline_map = {}
    if numbering_bytes:
        abstract_nums, num_map = _parse_numbering(numbering_bytes)
    if styles_bytes:
        style_numid = _parse_styles_heading_numid(styles_bytes)
        outline_map = _parse_styles_outline_map(styles_bytes)

    numbering_restorer = NumberingRestorer(abstract_nums, num_map, style_numid)

    # Parse document body
    doc_root = etree.fromstring(doc_bytes)
    body = doc_root.find(W_BODY)
    if body is None:
        raise ValueError("No w:body found in document.xml")

    blocks = []
    idx = 0

    for child in body:
        tag = child.tag

        if tag == W_P:
            style = _get_style(child)
            text = _elem_text(child)
            has_img = _has_image(child)
            level = _heading_level(style, outline_map)
            numbering = None
            para_numid = _get_para_numid(child)
            is_front_matter = (para_numid == "0")

            if level is not None:
                numbering = numbering_restorer.get_numbering(level, para_numid, text)

            block = {
                "idx": idx,
                "type": "paragraph",
                "style": style,
                "text": text,
                "has_image": has_img,
            }
            if level is not None:
                block["heading_level"] = level
                block["numbering"] = numbering
                block["is_front_matter"] = is_front_matter

            blocks.append(block)
            idx += 1

        elif tag == W_TBL:
            tbl_data = _extract_table(child)
            blocks.append({
                "idx": idx,
                "type": "table",
                **tbl_data,
            })
            idx += 1

        # All other tags (w:bookmarkEnd, w:sdt, etc.) are skipped

    # Write outputs
    with open(out_dir / "blocks.json", "w", encoding="utf-8") as f:
        json.dump(blocks, f, ensure_ascii=False, indent=2)

    media_inventory = _extract_media_inventory(docx_path)
    with open(out_dir / "media_inventory.json", "w", encoding="utf-8") as f:
        json.dump(media_inventory, f, ensure_ascii=False, indent=2)

    headers_footers = _extract_headers_footers(docx_path)
    with open(out_dir / "headers_footers.json", "w", encoding="utf-8") as f:
        json.dump(headers_footers, f, ensure_ascii=False, indent=2)

    print(f"[extract_blocks] {docx_path}")
    print(f"  blocks: {len(blocks)} ({sum(1 for b in blocks if b['type']=='paragraph')} paragraphs, {sum(1 for b in blocks if b['type']=='table')} tables)")
    print(f"  media:  {len(media_inventory)} files")
    print(f"  hdrftr: {len(headers_footers)} parts")

    return blocks, media_inventory, headers_footers


def main():
    parser = argparse.ArgumentParser(description="Extract DOCX blocks to JSON")
    parser.add_argument("--docx", required=True, help="Path to DOCX file")
    parser.add_argument("--out", required=True, help="Output directory")
    args = parser.parse_args()

    if not os.path.exists(args.docx):
        print(f"Error: DOCX file not found: {args.docx}", file=sys.stderr)
        sys.exit(1)

    extract_blocks(args.docx, args.out)


if __name__ == "__main__":
    main()
