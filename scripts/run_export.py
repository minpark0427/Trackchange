"""
run_export.py — Phase 4 orchestrator: change_rows → comparison table DOCX.

Auto-generates filename from protocol metadata in headers.

Usage:
  python3 scripts/run_export.py --work-dir work/ --out-dir work/output/
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


def _extract_metadata(headers_footers: dict) -> dict:
    """Extract protocol number and version from header text."""
    meta = {"protocol_no": "", "version": "", "doc_type": "Clinical Trial Protocol"}

    for part_name, entry in headers_footers.items():
        text = entry.get("text", "")

        # Protocol number: "Protocol No: SPONSOR_PROTOCOL001" or "Protocol No: DW_COMPOUND_X 1 01"
        m = re.search(r"Protocol\s+No[.:]\s*([A-Z0-9_\s]+?)(?:\s+Version|\s*$)", text, re.IGNORECASE)
        if m and not meta["protocol_no"]:
            raw = m.group(1).strip()
            # Clean up spaces within protocol number
            meta["protocol_no"] = re.sub(r"\s+", "", raw)

        # Version: "Version/date: 1.0 / 01 Jul 2019"
        m = re.search(r"Version/date:\s*([\d.]+)\s*/", text, re.IGNORECASE)
        if m and not meta["version"]:
            meta["version"] = m.group(1)

    return meta


def _generate_filename(old_meta: dict, new_meta: dict) -> str:
    """Generate filename from metadata."""
    date_str = datetime.now().strftime("%d%b%Y")
    protocol_no = new_meta.get("protocol_no") or old_meta.get("protocol_no")
    doc_type = new_meta.get("doc_type", "Clinical Trial Protocol")
    old_ver = old_meta.get("version", "")
    new_ver = new_meta.get("version", "")

    if protocol_no and old_ver and new_ver:
        return f"{protocol_no}_{doc_type}_Comparison Table of Change_Ver{old_ver}_to_Ver{new_ver}_{date_str}.docx"
    elif protocol_no:
        return f"{protocol_no}_Comparison Table of Change_{date_str}.docx"
    else:
        return f"Comparison_Table_of_Change_{date_str}.docx"


def main():
    parser = argparse.ArgumentParser(description="Run Phase 4: DOCX export")
    parser.add_argument("--work-dir", required=True, help="Work directory")
    parser.add_argument("--out-dir", required=True, help="Output directory for DOCX")
    args = parser.parse_args()

    work = Path(args.work_dir)
    rows_path = work / "rows" / "change_rows.json"
    old_hf_path = work / "old" / "headers_footers.json"
    new_hf_path = work / "new" / "headers_footers.json"

    if not rows_path.exists():
        print(f"Error: {rows_path} not found. Run Phase 3 first.", file=sys.stderr)
        sys.exit(1)

    try:
        from scripts.export_docx import export_docx
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.export_docx import export_docx

    print("=" * 60)
    print("Phase 4: DOCX Export")
    print("=" * 60)
    print()

    rows = json.load(open(rows_path, encoding="utf-8"))
    print(f"Input: {len(rows)} rows")

    # Extract metadata for filename and header
    old_meta = {"protocol_no": "", "version": "", "doc_type": "Clinical Trial Protocol"}
    new_meta = old_meta.copy()
    if old_hf_path.exists():
        old_hf = json.load(open(old_hf_path, encoding="utf-8"))
        old_meta = _extract_metadata(old_hf)
    if new_hf_path.exists():
        new_hf = json.load(open(new_hf_path, encoding="utf-8"))
        new_meta = _extract_metadata(new_hf)

    old_ver = f"Ver{old_meta['version']}" if old_meta["version"] else ""
    new_ver = f"Ver{new_meta['version']}" if new_meta["version"] else ""

    print(f"Protocol: {new_meta.get('protocol_no', 'unknown')}")
    print(f"Old version: {old_meta.get('version', 'unknown')}")
    print(f"New version: {new_meta.get('version', 'unknown')}")

    # Generate filename
    filename = _generate_filename(old_meta, new_meta)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename

    # Export
    export_docx(rows, str(out_path), old_ver, new_ver)

    print()
    print("=" * 60)
    print(f"Output: {out_path}")
    print(f"Rows: {len(rows)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
