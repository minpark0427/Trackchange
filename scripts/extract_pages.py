"""
extract_pages.py — Extract page numbers for each section by converting DOCX→PDF via Word.

Requires:
- Microsoft Word installed
- docx2pdf package
- PyMuPDF (fitz) package
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import fitz
import docx2pdf


def _convert_to_pdf(docx_path: str, pdf_path: str):
    """Convert DOCX to PDF using Microsoft Word (docx2pdf or AppleScript fallback)."""
    import subprocess

    Path(pdf_path).parent.mkdir(parents=True, exist_ok=True)

    # Try docx2pdf first
    try:
        docx2pdf.convert(docx_path, pdf_path)
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
            return
    except Exception:
        pass

    # Fallback: AppleScript direct Word automation (macOS only)
    abs_docx = os.path.abspath(docx_path)
    abs_pdf = os.path.abspath(pdf_path)
    script = f'''
tell application "Microsoft Word"
    open "{abs_docx}"
    delay 5
    set theDoc to active document
    save as theDoc file name "{abs_pdf}" file format format PDF
    close theDoc saving no
end tell
'''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0 or not os.path.exists(pdf_path):
        raise RuntimeError(
            f"PDF conversion failed: {result.stderr[:300]}"
        )


def _extract_heading_pages(pdf_path: str, min_heading_size: float = 13.0) -> list:
    """
    Extract headings and their page numbers from PDF.
    Returns list of (page_number, font_size, text).
    """
    doc = fitz.open(pdf_path)
    headings = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict")["blocks"]

        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                spans = line["spans"]
                if not spans:
                    continue

                text = "".join(span["text"] for span in spans).strip()
                max_size = max(span["size"] for span in spans)

                if max_size >= min_heading_size and len(text) > 2 and len(text) < 120:
                    headings.append((page_num + 1, max_size, text))

    doc.close()
    return headings


def _match_sections_to_pages(
    section_index: list,
    pdf_headings: list,
    blocks: list,
) -> dict:
    """
    Match sections to their page numbers using heading text from PDF.
    Returns dict: section_id -> {"page_start": int, "page_end": int, "page_str": str}
    """
    # Build a lookup of heading text -> page number from PDF
    # Only consider headings with size > 13 (H1=16.1, H2=13.9)
    pdf_lookup = {}
    for page, size, text in pdf_headings:
        # Normalize text for matching
        norm = re.sub(r'\s+', ' ', text.strip().lower())
        # Remove leading number prefix for matching
        without_num = re.sub(r'^\d+(?:\.\d+)*\.?\s*', '', norm)
        if without_num and without_num not in pdf_lookup:
            pdf_lookup[without_num] = page
        if norm and norm not in pdf_lookup:
            pdf_lookup[norm] = page

    # For each section, find its page
    page_map = {}
    section_pages = []

    for sec in section_index:
        if sec.get("excluded"):
            continue

        heading_text = sec.get("heading_text", "").strip()
        numbering = None

        # Get numbering from blocks
        start_idx = sec["start_block_idx"]
        for b in blocks:
            if b["idx"] == start_idx and b.get("heading_level"):
                numbering = b.get("numbering")
                break

        # Try matching with various normalizations
        page = None

        # 1. Try numbered heading (e.g., "10. statistical methods...")
        if numbering:
            full_text = f"{numbering} {heading_text}".lower().strip()
            norm = re.sub(r'\s+', ' ', full_text)
            page = pdf_lookup.get(norm)

        # 2. Try just the heading text
        if not page:
            norm = re.sub(r'\s+', ' ', heading_text.lower().strip())
            page = pdf_lookup.get(norm)

        # 3. Try partial match (first 30 chars)
        if not page and heading_text:
            partial = re.sub(r'\s+', ' ', heading_text[:30].lower().strip())
            for key, pg in pdf_lookup.items():
                if partial in key:
                    page = pg
                    break

        section_pages.append((sec["section_id"], page, sec.get("heading_text", "")))
        if page:
            page_map[sec["section_id"]] = page

    # Compute page ranges: each section spans from its page to the page before the next section
    result = {}
    sorted_sections = [(sid, pg, txt) for sid, pg, txt in section_pages if pg]

    for i, (sid, page_start, txt) in enumerate(sorted_sections):
        # Find next section's page
        if i + 1 < len(sorted_sections):
            next_page = sorted_sections[i + 1][1]
            page_end = next_page if next_page > page_start else page_start
        else:
            page_end = page_start

        if page_start == page_end:
            page_str = str(page_start)
        else:
            page_str = f"{page_start}-{page_end}"

        result[sid] = {
            "page_start": page_start,
            "page_end": page_end,
            "page_str": page_str,
        }

    # Fill in unmatched sections by inheriting from parent/previous section
    all_section_ids = [s["section_id"] for s in section_index if not s.get("excluded")]
    sec_by_id = {s["section_id"]: s for s in section_index}

    for sid in all_section_ids:
        if sid in result and result[sid]["page_start"] is not None:
            continue
        # Find the nearest previous section with a known page
        sec = sec_by_id.get(sid)
        if not sec:
            continue
        # Look at parent sections (walk up heading hierarchy)
        best_page = None
        for prev_sid in all_section_ids:
            if prev_sid == sid:
                break
            if prev_sid in result and result[prev_sid]["page_start"] is not None:
                best_page = result[prev_sid]["page_start"]
        if best_page:
            result[sid] = {"page_start": best_page, "page_end": best_page, "page_str": str(best_page)}
        else:
            result[sid] = {"page_start": None, "page_end": None, "page_str": ""}

    return result


def extract_pages(docx_path: str, section_index_path: str, blocks_path: str, out_path: str):
    """Main function: DOCX → PDF → page mapping for sections."""
    # Convert to PDF
    pdf_path = str(Path(out_path).parent / "temp.pdf")
    print(f"[extract_pages] Converting {docx_path} → PDF...")
    _convert_to_pdf(docx_path, pdf_path)

    # Extract headings from PDF
    pdf_headings = _extract_heading_pages(pdf_path)
    print(f"  PDF headings found: {len(pdf_headings)}")

    # Load section index and blocks
    section_index = json.load(open(section_index_path, encoding="utf-8"))
    blocks = json.load(open(blocks_path, encoding="utf-8"))

    # Match sections to pages
    page_map = _match_sections_to_pages(section_index, pdf_headings, blocks)
    matched = sum(1 for v in page_map.values() if v["page_start"] is not None)
    print(f"  Sections with pages: {matched}/{len(page_map)}")

    # Save
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(page_map, f, ensure_ascii=False, indent=2)

    # Clean up temp PDF
    if os.path.exists(pdf_path):
        os.remove(pdf_path)

    print(f"  Output: {out_path}")
    return page_map


def main():
    parser = argparse.ArgumentParser(description="Extract page numbers for sections")
    parser.add_argument("--docx", required=True, help="Path to DOCX file")
    parser.add_argument("--sections", required=True, help="Path to section_index.json")
    parser.add_argument("--blocks", required=True, help="Path to blocks.json")
    parser.add_argument("--out", required=True, help="Output path for page_map.json")
    args = parser.parse_args()

    extract_pages(args.docx, args.sections, args.blocks, args.out)


if __name__ == "__main__":
    main()
