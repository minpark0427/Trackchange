"""
diff_tables.py — Cell-level table diff with merge cell handling.

Normalizes vMerge/gridSpan merged cells into a regular grid, then compares
cell-by-cell at (row, col) coordinates.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from scripts.schema import make_candidate


def _normalize_text(text: str) -> str:
    """Normalize cell text for comparison."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_grid(table_block: dict) -> list:
    """
    Normalize a table with merged cells into a regular grid.
    
    Handles:
    - gridSpan: cell spans multiple columns → replicate text across columns
    - vMerge: vertical merge → copy "restart" cell text to "continue" cells
    
    Returns: list of rows, each row is list of normalized cell texts.
    """
    rows = table_block.get("rows", [])
    if not rows:
        return []

    # First pass: expand gridSpan horizontally
    expanded_rows = []
    for row in rows:
        expanded_row = []
        for cell in row.get("cells", []):
            text = _normalize_text(cell.get("text", ""))
            grid_span = cell.get("gridSpan", 1)
            vmerge = cell.get("vMerge")
            for _ in range(grid_span):
                expanded_row.append({"text": text, "vMerge": vmerge})
        expanded_rows.append(expanded_row)

    # Determine max columns
    max_cols = max((len(r) for r in expanded_rows), default=0)

    # Pad rows to max_cols
    for row in expanded_rows:
        while len(row) < max_cols:
            row.append({"text": "", "vMerge": None})

    # Second pass: resolve vMerge vertically
    grid = []
    for ri, row in enumerate(expanded_rows):
        grid_row = []
        for ci, cell in enumerate(row):
            if cell["vMerge"] == "continue" and ri > 0 and ci < len(grid[ri - 1]):
                # Copy from the cell above
                grid_row.append(grid[ri - 1][ci])
            else:
                grid_row.append(cell["text"])
        grid.append(grid_row)

    return grid


def _get_section_blocks(blocks, start_idx, end_idx):
    return [b for b in blocks if start_idx <= b["idx"] < end_idx]


def _get_tables(section_blocks):
    return [b for b in section_blocks if b["type"] == "table"]


def _diff_table_pair(old_table, new_table, section_path, table_num):
    """Diff two matched tables cell-by-cell."""
    candidates = []
    old_grid = _normalize_grid(old_table)
    new_grid = _normalize_grid(new_table)

    old_rows = len(old_grid)
    new_rows = len(new_grid)
    old_cols = max((len(r) for r in old_grid), default=0)
    new_cols = max((len(r) for r in new_grid), default=0)

    max_rows = max(old_rows, new_rows)
    max_cols = max(old_cols, new_cols)

    # Row addition/deletion
    if old_rows != new_rows:
        if new_rows > old_rows:
            for ri in range(old_rows, new_rows):
                row_text = " | ".join(new_grid[ri]) if ri < len(new_grid) else ""
                candidates.append(make_candidate(
                    section_path=section_path,
                    object_type="table",
                    change_type="add",
                    location_hint=f"table={table_num},row={ri}",
                    after=row_text[:500],
                    evidence=f"row added (old had {old_rows} rows, new has {new_rows})",
                    confidence=1.0,
                ))
        else:
            for ri in range(new_rows, old_rows):
                row_text = " | ".join(old_grid[ri]) if ri < len(old_grid) else ""
                candidates.append(make_candidate(
                    section_path=section_path,
                    object_type="table",
                    change_type="delete",
                    location_hint=f"table={table_num},row={ri}",
                    before=row_text[:500],
                    evidence=f"row deleted (old had {old_rows} rows, new has {new_rows})",
                    confidence=1.0,
                ))

    # Cell-level comparison for overlapping area
    compare_rows = min(old_rows, new_rows)
    compare_cols = min(old_cols, new_cols)

    for ri in range(compare_rows):
        for ci in range(compare_cols):
            old_cell = old_grid[ri][ci] if ci < len(old_grid[ri]) else ""
            new_cell = new_grid[ri][ci] if ci < len(new_grid[ri]) else ""
            if old_cell != new_cell:
                candidates.append(make_candidate(
                    section_path=section_path,
                    object_type="table",
                    change_type="modify",
                    location_hint=f"table={table_num},row={ri},col={ci}",
                    before=old_cell[:500],
                    after=new_cell[:500],
                    evidence=f"cell content changed at ({ri},{ci})",
                    confidence=1.0,
                ))

    # Column addition/deletion (only report at row 0 level)
    if old_cols != new_cols:
        if new_cols > old_cols:
            candidates.append(make_candidate(
                section_path=section_path,
                object_type="table",
                change_type="add",
                location_hint=f"table={table_num},cols={old_cols}-{new_cols-1}",
                evidence=f"columns added (old had {old_cols} cols, new has {new_cols})",
                confidence=1.0,
            ))
        else:
            candidates.append(make_candidate(
                section_path=section_path,
                object_type="table",
                change_type="delete",
                location_hint=f"table={table_num},cols={new_cols}-{old_cols-1}",
                evidence=f"columns removed (old had {old_cols} cols, new has {new_cols})",
                confidence=1.0,
            ))

    return candidates


def run_table_diff(work_dir: str) -> list:
    """Run table diff on all matched section pairs."""
    work = Path(work_dir)
    matched_pairs = json.load(open(work / "matched_pairs.json", encoding="utf-8"))
    old_blocks = json.load(open(work / "old" / "blocks.json", encoding="utf-8"))
    new_blocks = json.load(open(work / "new" / "blocks.json", encoding="utf-8"))
    old_sections = json.load(open(work / "old" / "section_index.json", encoding="utf-8"))
    new_sections = json.load(open(work / "new" / "section_index.json", encoding="utf-8"))

    old_sec_map = {s["section_id"]: s for s in old_sections}
    new_sec_map = {s["section_id"]: s for s in new_sections}

    all_candidates = []

    for pair in matched_pairs:
        match_type = pair["match_type"]

        if match_type in ("old_only", "new_only"):
            # Section-level add/delete for tables handled by diff_text section logic
            # We still note table presence
            if match_type == "old_only":
                old_sec = old_sec_map[pair["old_section_id"]]
                tables = _get_tables(_get_section_blocks(old_blocks, old_sec["start_block_idx"], old_sec["end_block_idx"]))
                for ti, tbl in enumerate(tables):
                    all_candidates.append(make_candidate(
                        section_path=pair["old_section_path"],
                        object_type="table",
                        change_type="delete",
                        location_hint=f"table={ti}",
                        before=f"table with {len(tbl.get('rows',[]))} rows",
                        evidence="section deleted",
                        confidence=1.0,
                    ))
            else:
                new_sec = new_sec_map[pair["new_section_id"]]
                tables = _get_tables(_get_section_blocks(new_blocks, new_sec["start_block_idx"], new_sec["end_block_idx"]))
                for ti, tbl in enumerate(tables):
                    all_candidates.append(make_candidate(
                        section_path=pair["new_section_path"],
                        object_type="table",
                        change_type="add",
                        location_hint=f"table={ti}",
                        after=f"table with {len(tbl.get('rows',[]))} rows",
                        evidence="section added",
                        confidence=1.0,
                    ))
            continue

        # Matched pair — diff tables
        old_sec = old_sec_map[pair["old_section_id"]]
        new_sec = new_sec_map[pair["new_section_id"]]

        old_tables = _get_tables(_get_section_blocks(old_blocks, old_sec["start_block_idx"], old_sec["end_block_idx"]))
        new_tables = _get_tables(_get_section_blocks(new_blocks, new_sec["start_block_idx"], new_sec["end_block_idx"]))

        section_path = pair.get("new_section_path") or pair.get("old_section_path")

        # Match tables by order
        max_tbls = max(len(old_tables), len(new_tables))
        for ti in range(max_tbls):
            if ti < len(old_tables) and ti < len(new_tables):
                candidates = _diff_table_pair(old_tables[ti], new_tables[ti], section_path, ti)
                all_candidates.extend(candidates)
            elif ti >= len(old_tables):
                # New table added
                tbl = new_tables[ti]
                all_candidates.append(make_candidate(
                    section_path=section_path,
                    object_type="table",
                    change_type="add",
                    location_hint=f"table={ti}",
                    after=f"table with {len(tbl.get('rows',[]))} rows",
                    evidence="table added in section",
                    confidence=1.0,
                ))
            else:
                # Old table deleted
                tbl = old_tables[ti]
                all_candidates.append(make_candidate(
                    section_path=section_path,
                    object_type="table",
                    change_type="delete",
                    location_hint=f"table={ti}",
                    before=f"table with {len(tbl.get('rows',[]))} rows",
                    evidence="table removed from section",
                    confidence=1.0,
                ))

    print(f"[diff_tables] {len(all_candidates)} table change candidates")
    types = {}
    for c in all_candidates:
        types[c["change_type"]] = types.get(c["change_type"], 0) + 1
    for t, n in sorted(types.items()):
        print(f"  {t}: {n}")

    return all_candidates


def main():
    parser = argparse.ArgumentParser(description="Table cell-level diff")
    parser.add_argument("--work-dir", required=True, help="Work directory")
    parser.add_argument("--out", required=True, help="Output path")
    args = parser.parse_args()

    candidates = run_table_diff(args.work_dir)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
