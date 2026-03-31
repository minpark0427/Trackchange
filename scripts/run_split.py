"""
run_split.py — Full section-split pipeline orchestrator.

Usage:
  python3 scripts/run_split.py \\
    --old "path/to/V1.docx" \\
    --new "path/to/V2.docx" \\
    --out work/
"""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run full DOCX section-split pipeline")
    parser.add_argument("--old", required=True, help="Path to old (V1) DOCX file")
    parser.add_argument("--new", required=True, help="Path to new (V2) DOCX file")
    parser.add_argument("--out", required=True, help="Output directory (e.g. work/)")
    args = parser.parse_args()

    old_docx = Path(args.old)
    new_docx = Path(args.new)
    out_dir = Path(args.out)

    # Validate inputs
    if not old_docx.exists():
        print(f"Error: Old DOCX not found: {old_docx}", file=sys.stderr)
        sys.exit(1)
    if not new_docx.exists():
        print(f"Error: New DOCX not found: {new_docx}", file=sys.stderr)
        sys.exit(1)

    old_dir = out_dir / "old"
    new_dir = out_dir / "new"
    matched_path = out_dir / "matched_pairs.json"

    # Import pipeline modules
    try:
        from scripts.extract_blocks import extract_blocks
        from scripts.split_sections import split_sections
        from scripts.match_sections import match_sections
        from scripts.extract_pages import extract_pages
    except ImportError:
        # Fallback: add parent dir to path
        import os
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.extract_blocks import extract_blocks
        from scripts.split_sections import split_sections
        from scripts.match_sections import match_sections
        from scripts.extract_pages import extract_pages

    print("=" * 60)
    print("DOCX Section-Split Pipeline")
    print("=" * 60)
    print(f"Old: {old_docx}")
    print(f"New: {new_docx}")
    print(f"Out: {out_dir}")
    print()

    # Step 1: Extract blocks from old DOCX
    print("[Step 1/5] Extracting blocks from old DOCX...")
    try:
        extract_blocks(str(old_docx), str(old_dir))
    except Exception as e:
        print(f"Error in Step 1 (extract old): {e}", file=sys.stderr)
        sys.exit(1)
    print()

    # Step 2: Extract blocks from new DOCX
    print("[Step 2/5] Extracting blocks from new DOCX...")
    try:
        extract_blocks(str(new_docx), str(new_dir))
    except Exception as e:
        print(f"Error in Step 2 (extract new): {e}", file=sys.stderr)
        sys.exit(1)
    print()

    # Step 3: Split old into sections
    print("[Step 3/5] Splitting old DOCX into sections...")
    try:
        split_sections(str(old_dir / "blocks.json"), str(old_dir / "section_index.json"))
    except Exception as e:
        print(f"Error in Step 3 (split old): {e}", file=sys.stderr)
        sys.exit(1)
    print()

    # Step 4: Split new into sections
    print("[Step 4/5] Splitting new DOCX into sections...")
    try:
        split_sections(str(new_dir / "blocks.json"), str(new_dir / "section_index.json"))
    except Exception as e:
        print(f"Error in Step 4 (split new): {e}", file=sys.stderr)
        sys.exit(1)
    print()

    # Step 5: Match sections
    print("[Step 5/5] Matching old↔new sections...")
    try:
        match_sections(
            str(old_dir / "section_index.json"),
            str(new_dir / "section_index.json"),
            str(matched_path),
        )
    except Exception as e:
        print(f"Error in Step 5 (match sections): {e}", file=sys.stderr)
        sys.exit(1)
    print()

    # Step 6: Extract page numbers (requires Microsoft Word)
    print("[Step 6/7] Extracting page numbers from old DOCX...")
    try:
        extract_pages(str(old_docx), str(old_dir / "section_index.json"),
                       str(old_dir / "blocks.json"), str(old_dir / "page_map.json"))
    except Exception as e:
        print(f"Warning: Page extraction failed for old DOCX: {e}")
        print("  (Page numbers will be unavailable. Install docx2pdf and ensure Word is installed.)")
    print()

    print("[Step 7/7] Extracting page numbers from new DOCX...")
    try:
        extract_pages(str(new_docx), str(new_dir / "section_index.json"),
                       str(new_dir / "blocks.json"), str(new_dir / "page_map.json"))
    except Exception as e:
        print(f"Warning: Page extraction failed for new DOCX: {e}")
        print("  (Page numbers will be unavailable. Install docx2pdf and ensure Word is installed.)")
    print()

    # Summary
    print("=" * 60)
    print("Pipeline complete. Output files:")
    for f in [
        old_dir / "blocks.json",
        old_dir / "section_index.json",
        old_dir / "media_inventory.json",
        new_dir / "blocks.json",
        new_dir / "section_index.json",
        new_dir / "media_inventory.json",
        matched_path,
    ]:
        status = "OK" if f.exists() else "MISSING"
        print(f"  [{status}] {f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
