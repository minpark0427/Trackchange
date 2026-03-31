"""
diff_headers.py — Header/Footer text diff between old/new DOCX versions.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import diff_match_patch as dmp_module

from scripts.schema import make_candidate


def _normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def run_header_diff(old_hf_path: str, new_hf_path: str) -> list:
    """Compare header/footer texts using diff-match-patch."""
    old_hf = json.load(open(old_hf_path, encoding="utf-8"))
    new_hf = json.load(open(new_hf_path, encoding="utf-8"))
    dmp = dmp_module.diff_match_patch()

    candidates = []
    all_parts = set(list(old_hf.keys()) + list(new_hf.keys()))

    for part in sorted(all_parts):
        old_entry = old_hf.get(part)
        new_entry = new_hf.get(part)

        old_text = _normalize_text(old_entry["text"]) if old_entry else ""
        new_text = _normalize_text(new_entry["text"]) if new_entry else ""

        if old_text == new_text:
            continue

        if old_entry and new_entry:
            diffs = dmp.diff_main(old_text, new_text)
            dmp.diff_cleanupSemantic(diffs)
            patches = dmp.patch_make(old_text, diffs)
            patch_text = dmp.patch_toText(patches)

            candidates.append(make_candidate(
                section_path="(header_footer)",
                object_type="header_footer",
                change_type="modify",
                location_hint=part,
                before=old_text[:500],
                after=new_text[:500],
                evidence=patch_text[:500],
                confidence=1.0,
            ))
        elif old_entry:
            candidates.append(make_candidate(
                section_path="(header_footer)",
                object_type="header_footer",
                change_type="delete",
                location_hint=part,
                before=old_text[:500],
                evidence=f"header/footer removed: {part}",
                confidence=1.0,
            ))
        else:
            candidates.append(make_candidate(
                section_path="(header_footer)",
                object_type="header_footer",
                change_type="add",
                location_hint=part,
                after=new_text[:500],
                evidence=f"header/footer added: {part}",
                confidence=1.0,
            ))

    print(f"[diff_headers] {len(candidates)} header/footer change candidates")
    for c in candidates:
        print(f"  {c['change_type']}: {c['location_hint']}")

    return candidates


def main():
    parser = argparse.ArgumentParser(description="Header/Footer diff")
    parser.add_argument("--old-hf", required=True)
    parser.add_argument("--new-hf", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    candidates = run_header_diff(args.old_hf, args.new_hf)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
