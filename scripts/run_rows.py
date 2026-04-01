"""
run_rows.py — Phase 3 orchestrator: change_candidates → change_rows via Claude CLI.

Usage:
  python3 scripts/run_rows.py --work-dir work/ --out work/rows/change_rows.json
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run Phase 3: Claude row generation")
    parser.add_argument("--work-dir", required=True, help="Work directory with Phase 1+2 outputs")
    parser.add_argument("--out", required=True, help="Output path for change_rows.json")
    parser.add_argument("--max-workers", type=int, default=3, help="Max parallel Claude CLI calls")
    args = parser.parse_args()

    work = Path(args.work_dir)
    candidates_path = work / "diff" / "change_candidates.json"
    blocks_path = work / "new" / "blocks.json"

    if not candidates_path.exists():
        print(f"Error: {candidates_path} not found. Run Phase 2 first.", file=sys.stderr)
        sys.exit(1)
    if not blocks_path.exists():
        print(f"Error: {blocks_path} not found. Run Phase 1 first.", file=sys.stderr)
        sys.exit(1)

    try:
        from scripts.generate_rows import generate_all_rows
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.generate_rows import generate_all_rows

    print("=" * 60)
    print("Phase 3: Claude Row Generation")
    print("=" * 60)
    print()

    candidates = json.load(open(candidates_path, encoding="utf-8"))
    print(f"Input: {len(candidates)} change candidates")
    print(f"Max workers: {args.max_workers}")
    print()

    rows = generate_all_rows(str(candidates_path), str(blocks_path), args.max_workers)

    # Sort rows by page number (document order)
    def _page_sort_key(row):
        page = row.get("page", "")
        if not page:
            return (0, 0)  # front matter first
        if page == "전체":
            return (0, 1)  # headers right after front matter
        # Extract first number from page string (e.g., "18-35" -> 18)
        import re
        m = re.search(r"(\d+)", page)
        if m:
            return (1, int(m.group(1)))
        return (2, 0)

    rows.sort(key=_page_sort_key)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    # Summary
    print()
    print("=" * 60)
    print(f"Total rows generated: {len(rows)}")
    if rows:
        required = ["page", "item", "previous_version", "current_version", "note"]
        valid = sum(1 for r in rows if all(f in r for f in required))
        print(f"Valid rows (5-field): {valid}/{len(rows)}")
    print(f"Output: {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
