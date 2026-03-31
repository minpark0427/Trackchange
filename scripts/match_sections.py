"""
match_sections.py — old/new section_index.json → matched_pairs.json

Matches old↔new sections using priority:
  1. Exact match (heading_text, case-insensitive, whitespace-normalized)
  2. Number match (section_path number prefix)
  3. Fuzzy match (difflib.SequenceMatcher ratio >= 0.8)
  4. Unmatched (old_only / new_only)
"""

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path


def _normalize_text(text: str) -> str:
    """Normalize text for comparison: lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _extract_number_prefix(section_path: str) -> str:
    """
    Extract the leading number prefix from section_path.
    E.g. "5.1 Identity of IP" -> "5.1"
         "1. Introduction > 1.2. Overview" -> "1.2"  (use last segment)
    Returns empty string if no number found.
    """
    # Use the last segment of the path for the deepest number
    last_segment = section_path.split(">")[-1].strip()
    m = re.match(r"^([\d]+(?:\.[\d]+)*\.?)\s", last_segment)
    if m:
        # Normalize: strip trailing dot
        return m.group(1).rstrip(".")
    return ""


def _fuzzy_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def match_sections(old_path: str, new_path: str, out_path: str):
    old_sections = json.load(open(old_path, encoding="utf-8"))
    new_sections = json.load(open(new_path, encoding="utf-8"))

    # Only match non-excluded sections
    old_active = [s for s in old_sections if not s.get("excluded")]
    new_active = [s for s in new_sections if not s.get("excluded")]

    pairs = []
    old_unmatched = list(old_active)
    new_unmatched = list(new_active)

    # --- Pass 1: Exact match on heading_text ---
    old_by_text = {}
    for s in old_unmatched:
        key = _normalize_text(s["heading_text"])
        old_by_text.setdefault(key, []).append(s)

    new_still_unmatched = []
    for new_sec in new_unmatched:
        key = _normalize_text(new_sec["heading_text"])
        if key in old_by_text and old_by_text[key]:
            old_sec = old_by_text[key].pop(0)
            pairs.append({
                "match_type": "exact",
                "old_section_id": old_sec["section_id"],
                "new_section_id": new_sec["section_id"],
                "old_section_path": old_sec["section_path"],
                "new_section_path": new_sec["section_path"],
                "similarity": 1.0,
            })
        else:
            new_still_unmatched.append(new_sec)

    # Rebuild old_unmatched from what's left in old_by_text
    old_still_unmatched = [s for lst in old_by_text.values() for s in lst]

    # --- Pass 2: Number prefix match ---
    old_by_number = {}
    for s in old_still_unmatched:
        num = _extract_number_prefix(s["section_path"])
        if num:
            old_by_number.setdefault(num, []).append(s)

    new_still_unmatched2 = []
    for new_sec in new_still_unmatched:
        num = _extract_number_prefix(new_sec["section_path"])
        if num and num in old_by_number and old_by_number[num]:
            old_sec = old_by_number[num].pop(0)
            # Also remove from old_still_unmatched tracking
            pairs.append({
                "match_type": "number",
                "old_section_id": old_sec["section_id"],
                "new_section_id": new_sec["section_id"],
                "old_section_path": old_sec["section_path"],
                "new_section_path": new_sec["section_path"],
                "similarity": 0.9,
            })
        else:
            new_still_unmatched2.append(new_sec)

    old_still_unmatched2 = [s for lst in old_by_number.values() for s in lst]

    # --- Pass 3: Fuzzy match ---
    FUZZY_THRESHOLD = 0.8
    used_old = set()
    new_still_unmatched3 = []

    for new_sec in new_still_unmatched2:
        best_ratio = 0.0
        best_old = None
        new_norm = _normalize_text(new_sec["heading_text"])
        for old_sec in old_still_unmatched2:
            if old_sec["section_id"] in used_old:
                continue
            old_norm = _normalize_text(old_sec["heading_text"])
            ratio = _fuzzy_ratio(new_norm, old_norm)
            if ratio > best_ratio:
                best_ratio = ratio
                best_old = old_sec

        if best_old and best_ratio >= FUZZY_THRESHOLD:
            used_old.add(best_old["section_id"])
            pairs.append({
                "match_type": "fuzzy",
                "old_section_id": best_old["section_id"],
                "new_section_id": new_sec["section_id"],
                "old_section_path": best_old["section_path"],
                "new_section_path": new_sec["section_path"],
                "similarity": round(best_ratio, 3),
            })
        else:
            new_still_unmatched3.append(new_sec)

    old_still_unmatched3 = [s for s in old_still_unmatched2 if s["section_id"] not in used_old]

    # --- Pass 4: Unmatched ---
    for old_sec in old_still_unmatched3:
        pairs.append({
            "match_type": "old_only",
            "old_section_id": old_sec["section_id"],
            "new_section_id": None,
            "old_section_path": old_sec["section_path"],
            "new_section_path": None,
            "similarity": 0.0,
        })

    for new_sec in new_still_unmatched3:
        pairs.append({
            "match_type": "new_only",
            "old_section_id": None,
            "new_section_id": new_sec["section_id"],
            "old_section_path": None,
            "new_section_path": new_sec["section_path"],
            "similarity": 0.0,
        })

    # Write output
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(pairs, f, ensure_ascii=False, indent=2)

    # Print summary
    exact = sum(1 for p in pairs if p["match_type"] == "exact")
    number = sum(1 for p in pairs if p["match_type"] == "number")
    fuzzy = sum(1 for p in pairs if p["match_type"] == "fuzzy")
    old_only = sum(1 for p in pairs if p["match_type"] == "old_only")
    new_only = sum(1 for p in pairs if p["match_type"] == "new_only")

    print(f"[match_sections]")
    print(f"  old active sections: {len(old_active)}")
    print(f"  new active sections: {len(new_active)}")
    print(f"  total pairs:  {len(pairs)}")
    print(f"  exact:        {exact}")
    print(f"  number:       {number}")
    print(f"  fuzzy:        {fuzzy}")
    print(f"  old_only:     {old_only}")
    print(f"  new_only:     {new_only}")

    return pairs


def main():
    parser = argparse.ArgumentParser(description="Match old↔new sections")
    parser.add_argument("--old", required=True, help="Path to old section_index.json")
    parser.add_argument("--new", required=True, help="Path to new section_index.json")
    parser.add_argument("--out", required=True, help="Output path for matched_pairs.json")
    args = parser.parse_args()

    if not Path(args.old).exists():
        print(f"Error: {args.old} not found", file=sys.stderr)
        sys.exit(1)
    if not Path(args.new).exists():
        print(f"Error: {args.new} not found", file=sys.stderr)
        sys.exit(1)

    match_sections(args.old, args.new, args.out)


if __name__ == "__main__":
    main()
