"""
run_diff.py — Phase 2 diff pipeline orchestrator.

Usage:
  python3 scripts/run_diff.py --work-dir work/ --out work/diff/change_candidates.json
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run full diff pipeline")
    parser.add_argument("--work-dir", required=True, help="Work directory with Phase 1 outputs")
    parser.add_argument("--out", required=True, help="Output path for change_candidates.json")
    args = parser.parse_args()

    work = Path(args.work_dir)
    out_path = Path(args.out)

    # Validate Phase 1 outputs
    required = [
        work / "old" / "blocks.json",
        work / "new" / "blocks.json",
        work / "old" / "section_index.json",
        work / "new" / "section_index.json",
        work / "matched_pairs.json",
        work / "old" / "media_inventory.json",
        work / "new" / "media_inventory.json",
        work / "old" / "headers_footers.json",
        work / "new" / "headers_footers.json",
    ]
    for f in required:
        if not f.exists():
            print(f"Error: Missing Phase 1 output: {f}", file=sys.stderr)
            sys.exit(1)

    # Import diff modules
    try:
        from scripts.diff_text import run_text_diff
        from scripts.diff_tables import run_table_diff
        from scripts.diff_media import run_media_diff
        from scripts.diff_headers import run_header_diff
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.diff_text import run_text_diff
        from scripts.diff_tables import run_table_diff
        from scripts.diff_media import run_media_diff
        from scripts.diff_headers import run_header_diff

    print("=" * 60)
    print("Phase 2: Section Diff Pipeline")
    print("=" * 60)
    print()

    # Step 1: Text diff
    print("[Step 1/4] Text diff...")
    try:
        text_candidates = run_text_diff(str(work))
    except Exception as e:
        print(f"Error in text diff: {e}", file=sys.stderr)
        sys.exit(1)
    print()

    # Step 2: Table diff
    print("[Step 2/4] Table diff...")
    try:
        table_candidates = run_table_diff(str(work))
    except Exception as e:
        print(f"Error in table diff: {e}", file=sys.stderr)
        sys.exit(1)
    print()

    # Step 3: Media diff
    print("[Step 3/4] Media diff...")
    try:
        media_candidates = run_media_diff(
            str(work / "old" / "media_inventory.json"),
            str(work / "new" / "media_inventory.json"),
        )
    except Exception as e:
        print(f"Error in media diff: {e}", file=sys.stderr)
        sys.exit(1)
    print()

    # Step 4: Header/Footer diff
    print("[Step 4/4] Header/Footer diff...")
    try:
        header_candidates = run_header_diff(
            str(work / "old" / "headers_footers.json"),
            str(work / "new" / "headers_footers.json"),
        )
    except Exception as e:
        print(f"Error in header diff: {e}", file=sys.stderr)
        sys.exit(1)
    print()

    # Merge all candidates
    all_candidates = text_candidates + table_candidates + media_candidates + header_candidates

    # Enrich with page numbers if available
    new_page_map_path = work / "new" / "page_map.json"
    old_page_map_path = work / "old" / "page_map.json"
    new_section_index_path = work / "new" / "section_index.json"

    if new_page_map_path.exists() and new_section_index_path.exists():
        new_page_map = json.load(open(new_page_map_path, encoding="utf-8"))
        new_sections = json.load(open(new_section_index_path, encoding="utf-8"))

        # Build section_path -> page_str lookup
        path_to_page = {}
        for sec in new_sections:
            pg = new_page_map.get(sec["section_id"], {})
            if pg.get("page_str"):
                path_to_page[sec["section_path"]] = pg["page_str"]

        # Add page_hint to each candidate
        for c in all_candidates:
            sp = c.get("section_path", "")
            c["page_hint"] = path_to_page.get(sp, "")
            # For header_footer, use "전체" (all pages)
            if c.get("object_type") == "header_footer":
                c["page_hint"] = "전체"

        enriched = sum(1 for c in all_candidates if c.get("page_hint"))
        print(f"  Page numbers enriched: {enriched}/{len(all_candidates)}")

    # Write output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_candidates, f, ensure_ascii=False, indent=2)

    # Summary
    print("=" * 60)
    print(f"Total change candidates: {len(all_candidates)}")
    obj_types = {}
    change_types = {}
    for c in all_candidates:
        obj_types[c["object_type"]] = obj_types.get(c["object_type"], 0) + 1
        change_types[c["change_type"]] = change_types.get(c["change_type"], 0) + 1
    print(f"  By object type: {dict(sorted(obj_types.items()))}")
    print(f"  By change type: {dict(sorted(change_types.items()))}")
    print(f"  Output: {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
