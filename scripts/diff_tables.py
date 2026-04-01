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
    """
    Diff two matched tables and produce aggregated candidates.

    Instead of one candidate per cell, aggregates all cell-level changes
    into a single candidate per table with representative before/after samples.
    """
    old_grid = _normalize_grid(old_table)
    new_grid = _normalize_grid(new_table)

    old_rows = len(old_grid)
    new_rows = len(new_grid)
    old_cols = max((len(r) for r in old_grid), default=0)
    new_cols = max((len(r) for r in new_grid), default=0)

    # Collect all cell-level changes
    cell_changes = []  # (ri, ci, old_text, new_text)
    compare_rows = min(old_rows, new_rows)
    compare_cols = min(old_cols, new_cols)

    for ri in range(compare_rows):
        for ci in range(compare_cols):
            old_cell = old_grid[ri][ci] if ci < len(old_grid[ri]) else ""
            new_cell = new_grid[ri][ci] if ci < len(new_grid[ri]) else ""
            if old_cell != new_cell:
                cell_changes.append((ri, ci, old_cell, new_cell))

    # Collect added/deleted rows
    added_rows = []
    deleted_rows = []
    if new_rows > old_rows:
        for ri in range(old_rows, new_rows):
            row_text = " | ".join(new_grid[ri]) if ri < len(new_grid) else ""
            added_rows.append((ri, row_text))
    elif old_rows > new_rows:
        for ri in range(new_rows, old_rows):
            row_text = " | ".join(old_grid[ri]) if ri < len(old_grid) else ""
            deleted_rows.append((ri, row_text))

    # If no changes at all, return empty
    if not cell_changes and not added_rows and not deleted_rows and old_cols == new_cols:
        return []

    # Build aggregated candidate(s)
    candidates = []

    # Build a representative summary of changes
    change_count = len(cell_changes)
    changed_rows = sorted(set(ri for ri, ci, _, _ in cell_changes))

    # Build before/after text showing key changed content (representative samples)
    before_parts = []
    after_parts = []
    # Show up to 5 representative cell changes
    for ri, ci, old_cell, new_cell in cell_changes[:5]:
        if old_cell.strip():
            before_parts.append(old_cell.strip())
        if new_cell.strip():
            after_parts.append(new_cell.strip())

    # Add row additions/deletions info
    if added_rows:
        for ri, text in added_rows[:3]:
            after_parts.append(f"[추가된 행 {ri}] {text.strip()}")
    if deleted_rows:
        for ri, text in deleted_rows[:3]:
            before_parts.append(f"[삭제된 행 {ri}] {text.strip()}")

    # Add column additions/deletions info with content from extra columns
    if new_cols > old_cols:
        for ri in range(min(3, compare_rows)):
            extra = [new_grid[ri][ci] for ci in range(old_cols, new_cols) if ci < len(new_grid[ri])]
            if any(c.strip() for c in extra):
                after_parts.append(f"[추가된 열, 행 {ri}] {' | '.join(extra)}")
    elif old_cols > new_cols:
        for ri in range(min(3, compare_rows)):
            extra = [old_grid[ri][ci] for ci in range(new_cols, old_cols) if ci < len(old_grid[ri])]
            if any(c.strip() for c in extra):
                before_parts.append(f"[삭제된 열, 행 {ri}] {' | '.join(extra)}")

    before_text = "\n\n".join(before_parts)[:1000]
    after_text = "\n\n".join(after_parts)[:1000]

    # Evidence summary
    evidence_parts = []
    if cell_changes:
        evidence_parts.append(f"{change_count} cells changed across rows {changed_rows[:10]}")
    if added_rows:
        evidence_parts.append(f"{len(added_rows)} rows added")
    if deleted_rows:
        evidence_parts.append(f"{len(deleted_rows)} rows deleted")
    if old_cols != new_cols:
        evidence_parts.append(f"columns: {old_cols}→{new_cols}")

    # Determine change_type: use "modify" for any structural or content change
    change_type = "modify"
    if not cell_changes and not deleted_rows and old_cols == new_cols:
        change_type = "add" if added_rows else "modify"
    elif not cell_changes and not added_rows and old_cols == new_cols:
        change_type = "delete" if deleted_rows else "modify"

    candidates.append(make_candidate(
        section_path=section_path,
        object_type="table",
        change_type=change_type,
        location_hint=f"table={table_num} ({old_rows}×{old_cols}→{new_rows}×{new_cols})",
        before=before_text,
        after=after_text,
        evidence="; ".join(evidence_parts),
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
