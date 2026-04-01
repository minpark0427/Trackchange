"""
split_sections.py — blocks.json → section_index.json

Adaptive heading-based section splitting:
  - Primary split: Heading 1/2/3
  - If section > 30 blocks and has Heading 4/5 → additional split
  - Excludes: TOC, empty headings, signature pages, synopsis
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional


# Heading levels used for primary split
PRIMARY_HEADING_LEVELS = {1, 2, 3}
SECONDARY_HEADING_LEVELS = {4, 5}
ADAPTIVE_THRESHOLD = 30

# Exclusion patterns (matched against heading text, case-insensitive)
EXCLUDE_PATTERNS = [
    r"^table\s+of\s+contents?$",
    r"^list\s+of\s+(tables?|figures?|abbreviations?|tables?\s+and\s+figures?)$",
    r"sponsor\s+protocol\s+signature",
    r"investigator\s+acknowledgement",
    r"clinical\s+(study|protocol)\s+synopsis",
    r"목차",                      # Korean: table of contents
    r"표\s*목차",                  # Korean: list of tables
    r"그림\s*목차",                # Korean: list of figures
    r"서명\s*페이지",              # Korean: signature page
    r"SIGNATURE\s+PAGE",
]

# Styles to exclude (TOC-related)
# Standard: "TOC1", Korean documents may use numeric IDs like "10" (toc 1), "21" (toc 2), etc.
EXCLUDE_STYLES = {
    "TOC1", "TOC2", "TOC3", "TOC4", "TOC5",
    "toc1", "toc2", "toc3", "toc4", "toc5",
    "10", "21", "31", "40", "50", "6", "70", "80", "90",  # numeric TOC style IDs
}


def _is_excluded_heading(heading_text: str, heading_style: Optional[str]) -> bool:
    """Check if a heading should be excluded from comparison."""
    text = heading_text.strip()

    # Empty heading
    if not text:
        return True

    # Match exclusion patterns
    for pat in EXCLUDE_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True

    return False


def _section_path(heading_stack: list) -> str:
    """
    Build section_path from the heading stack.
    Each entry: (level, numbering, text)
    """
    parts = []
    for level, numbering, text in heading_stack:
        if numbering:
            parts.append(f"{numbering} {text}")
        else:
            parts.append(text)
    return " > ".join(parts)


def _has_tables(blocks: list, start: int, end: int) -> bool:
    """Check if any block in range [start, end) is a table."""
    for b in blocks[start:end]:
        if b["type"] == "table":
            return True
    return False


def _has_images(blocks: list, start: int, end: int) -> bool:
    """Check if any paragraph in range has an image."""
    for b in blocks[start:end]:
        if b["type"] == "paragraph" and b.get("has_image"):
            return True
    return False


def split_sections(blocks_path: str, out_path: str):
    """
    Main split function.
    Reads blocks.json, writes section_index.json.
    """
    blocks = json.load(open(blocks_path, encoding="utf-8"))

    # Find all heading positions for primary levels
    heading_positions = []
    for i, b in enumerate(blocks):
        lvl = b.get("heading_level")
        if lvl and lvl in PRIMARY_HEADING_LEVELS:
            heading_positions.append(i)

    if not heading_positions:
        raise ValueError("No headings found in blocks.json")

    # Build initial sections from primary headings
    # Each section: [heading_block_index, next_heading_block_index)
    raw_sections = []

    # Add pre-heading front matter section (cover page, document history, etc.)
    if heading_positions[0] > 0:
        raw_sections.append((0, heading_positions[0]))

    for i, pos in enumerate(heading_positions):
        end = heading_positions[i + 1] if i + 1 < len(heading_positions) else len(blocks)
        raw_sections.append((pos, end))

    # Adaptive split: sections > ADAPTIVE_THRESHOLD with H4/H5
    final_sections = []
    for start, end in raw_sections:
        block_count = end - start
        if block_count > ADAPTIVE_THRESHOLD:
            # Look for secondary headings within this section
            sub_positions = [
                j for j in range(start + 1, end)
                if blocks[j].get("heading_level") in SECONDARY_HEADING_LEVELS
            ]
            if sub_positions:
                # Split at each secondary heading
                sub_starts = [start] + sub_positions
                for k, sub_start in enumerate(sub_starts):
                    sub_end = sub_starts[k + 1] if k + 1 < len(sub_starts) else end
                    final_sections.append((sub_start, sub_end))
            else:
                # No sub-headings → keep as is (can't split further)
                final_sections.append((start, end))
        else:
            final_sections.append((start, end))

    # Build section_index
    section_index = []
    sec_counter = 0

    # Track heading stack for building section_path
    # We rebuild this by scanning the full block list up to each section heading
    # Instead, we maintain the stack as we iterate sequentially
    heading_stack = []  # list of (level, numbering, text)

    for start, end in final_sections:
        heading_block = blocks[start]
        level = heading_block.get("heading_level")

        # Handle pre-heading front matter section (no heading_level)
        if level is None:
            sec_id = f"sec_{sec_counter:04d}"
            sec_counter += 1

            # Check if front matter has only TOC content
            has_toc = any(b.get("style") in EXCLUDE_STYLES for b in blocks[start:end])
            # Check if front matter has substantive content (cover page, doc history)
            has_content = any(
                b.get("type") == "table" or (b.get("type") == "paragraph" and b.get("text", "").strip())
                for b in blocks[start:end]
                if b.get("style") not in EXCLUDE_STYLES
            )

            section_index.append({
                "section_id": sec_id,
                "section_path": "(front_matter)",
                "heading_level": 0,
                "heading_text": "(Front Matter)",
                "start_block_idx": start,
                "end_block_idx": end,
                "block_count": end - start,
                "excluded": not has_content,
                "has_tables": _has_tables(blocks, start, end),
                "has_images": _has_images(blocks, start, end),
            })
            continue

        numbering = heading_block.get("numbering")
        text = heading_block.get("text", "").strip()
        style = heading_block.get("style", "")

        # Update heading stack for this level
        # Remove all entries at this level and deeper
        heading_stack = [(l, n, t) for (l, n, t) in heading_stack if l < level]
        heading_stack.append((level, numbering, text))

        # Determine exclusion
        excluded = _is_excluded_heading(text, style)

        # Also exclude if any block in section uses TOC styles
        # (TOC sections contain TOC-styled paragraphs)
        if not excluded:
            for b in blocks[start:end]:
                if b.get("style") in EXCLUDE_STYLES:
                    excluded = True
                    break

        sec_id = f"sec_{sec_counter:04d}"
        sec_counter += 1

        path = _section_path(heading_stack)
        block_count = end - start

        section_index.append({
            "section_id": sec_id,
            "section_path": path,
            "heading_level": level,
            "heading_text": text,
            "start_block_idx": start,
            "end_block_idx": end,
            "block_count": block_count,
            "excluded": excluded,
            "has_tables": _has_tables(blocks, start, end),
            "has_images": _has_images(blocks, start, end),
        })

    # Write output
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(section_index, f, ensure_ascii=False, indent=2)

    active = [s for s in section_index if not s["excluded"]]
    excluded_list = [s for s in section_index if s["excluded"]]
    max_blocks = max((s["block_count"] for s in active), default=0)
    over_30 = [s for s in active if s["block_count"] > 30]

    print(f"[split_sections] {blocks_path}")
    print(f"  total sections:    {len(section_index)}")
    print(f"  active (included): {len(active)}")
    print(f"  excluded:          {len(excluded_list)}")
    print(f"  max block count:   {max_blocks}")
    print(f"  over 30 blocks:    {len(over_30)}")
    if over_30:
        for s in over_30:
            print(f"    [{s['section_id']}] {s['section_path']} ({s['block_count']} blocks)")

    return section_index


def main():
    parser = argparse.ArgumentParser(description="Split blocks.json into sections")
    parser.add_argument("--blocks", required=True, help="Path to blocks.json")
    parser.add_argument("--out", required=True, help="Output path for section_index.json")
    args = parser.parse_args()

    try:
        split_sections(args.blocks, args.out)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
