"""
diff_text.py — Paragraph-level text diff with move detection.

Uses diff-match-patch for character-level diffs within matched paragraphs.
Uses difflib.SequenceMatcher for paragraph-level alignment.
"""

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import diff_match_patch as dmp_module

from scripts.schema import make_candidate


def _normalize_text(text: str) -> str:
    """Normalize text for comparison: collapse whitespace, strip control chars."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _get_section_blocks(blocks, start_idx, end_idx):
    """Get blocks for a section by index range."""
    return [b for b in blocks if start_idx <= b["idx"] < end_idx]


# TOC and list-of-tables/figures styles to skip in diff
_SKIP_STYLES = {
    "TOC1", "TOC2", "TOC3", "TOC4", "TOC5", "TOC6", "TOC7", "TOC8", "TOC9",
    "toc1", "toc2", "toc3", "toc4", "toc5", "toc6", "toc7", "toc8", "toc9",
    "10", "21", "31", "40", "50", "6", "70", "80", "90",  # numeric TOC style IDs
    "aa",  # list of tables/figures style
}


def _get_paragraphs(section_blocks):
    """Extract paragraph blocks (text only, skip headings and TOC entries)."""
    return [
        b for b in section_blocks
        if b["type"] == "paragraph"
        and not b.get("heading_level")
        and b.get("style") not in _SKIP_STYLES
    ]


def _diff_paragraphs(old_paras, new_paras, section_path):
    """
    Diff paragraphs within a matched section pair.
    Returns list of change candidates.
    """
    candidates = []
    dmp = dmp_module.diff_match_patch()

    # Normalize texts
    old_texts = [_normalize_text(p.get("text", "")) for p in old_paras]
    new_texts = [_normalize_text(p.get("text", "")) for p in new_paras]

    # Filter out empty paragraphs for alignment
    old_indexed = [(i, t) for i, t in enumerate(old_texts) if t]
    new_indexed = [(i, t) for i, t in enumerate(new_texts) if t]

    old_content = [t for _, t in old_indexed]
    new_content = [t for _, t in new_indexed]

    # Align paragraphs using SequenceMatcher on text list
    sm = SequenceMatcher(None, old_content, new_content)
    opcodes = sm.get_opcodes()

    deleted_texts = []  # (text, old_idx) for move detection
    added_texts = []    # (text, new_idx) for move detection

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue

        elif tag == "replace":
            # Paired paragraphs that differ — character-level diff
            for oi, ni in zip(range(i1, i2), range(j1, j2)):
                old_t = old_content[oi]
                new_t = new_content[ni]
                if old_t == new_t:
                    continue
                diffs = dmp.diff_main(old_t, new_t)
                dmp.diff_cleanupSemantic(diffs)
                patches = dmp.patch_make(old_t, diffs)
                patch_text = dmp.patch_toText(patches)

                old_orig_idx = old_indexed[oi][0]
                new_orig_idx = new_indexed[ni][0]

                candidates.append(make_candidate(
                    section_path=section_path,
                    object_type="text",
                    change_type="modify",
                    location_hint=f"old_para_idx={old_paras[old_orig_idx]['idx']},new_para_idx={new_paras[new_orig_idx]['idx']}",
                    before=old_t,
                    after=new_t,
                    evidence=patch_text[:500],
                    confidence=1.0,
                ))

            # Leftover unmatched in replace range
            if i2 - i1 > j2 - j1:
                for oi in range(j2 - j1 + i1, i2):
                    old_orig_idx = old_indexed[oi][0]
                    deleted_texts.append((old_content[oi], old_paras[old_orig_idx]["idx"]))
            elif j2 - j1 > i2 - i1:
                for ni in range(i2 - i1 + j1, j2):
                    new_orig_idx = new_indexed[ni][0]
                    added_texts.append((new_content[ni], new_paras[new_orig_idx]["idx"]))

        elif tag == "delete":
            for oi in range(i1, i2):
                old_orig_idx = old_indexed[oi][0]
                deleted_texts.append((old_content[oi], old_paras[old_orig_idx]["idx"]))

        elif tag == "insert":
            for ni in range(j1, j2):
                new_orig_idx = new_indexed[ni][0]
                added_texts.append((new_content[ni], new_paras[new_orig_idx]["idx"]))

    # Move detection: match deleted/added with high similarity
    MOVE_THRESHOLD = 0.9
    used_added = set()

    for del_text, del_idx in deleted_texts:
        best_ratio = 0.0
        best_add = None
        best_add_i = None
        for ai, (add_text, add_idx) in enumerate(added_texts):
            if ai in used_added:
                continue
            ratio = SequenceMatcher(None, del_text, add_text).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_add = (add_text, add_idx)
                best_add_i = ai

        if best_add and best_ratio >= MOVE_THRESHOLD:
            used_added.add(best_add_i)
            candidates.append(make_candidate(
                section_path=section_path,
                object_type="text",
                change_type="move",
                location_hint=f"old_para_idx={del_idx},new_para_idx={best_add[1]}",
                before=del_text,
                after=best_add[0],
                evidence=f"similarity={best_ratio:.3f}",
                move_from=f"para_idx={del_idx}",
                move_to=f"para_idx={best_add[1]}",
                confidence=best_ratio,
            ))
        else:
            candidates.append(make_candidate(
                section_path=section_path,
                object_type="text",
                change_type="delete",
                location_hint=f"old_para_idx={del_idx}",
                before=del_text,
                evidence="paragraph removed",
                confidence=1.0,
            ))

    for ai, (add_text, add_idx) in enumerate(added_texts):
        if ai in used_added:
            continue
        candidates.append(make_candidate(
            section_path=section_path,
            object_type="text",
            change_type="add",
            location_hint=f"new_para_idx={add_idx}",
            after=add_text,
            evidence="paragraph added",
            confidence=1.0,
        ))

    return candidates


def run_text_diff(work_dir: str) -> list:
    """
    Run text diff on all matched section pairs.
    Returns list of change candidates.
    """
    work = Path(work_dir)
    matched_pairs = json.load(open(work / "matched_pairs.json", encoding="utf-8"))
    old_blocks = json.load(open(work / "old" / "blocks.json", encoding="utf-8"))
    new_blocks = json.load(open(work / "new" / "blocks.json", encoding="utf-8"))
    old_sections = json.load(open(work / "old" / "section_index.json", encoding="utf-8"))
    new_sections = json.load(open(work / "new" / "section_index.json", encoding="utf-8"))

    # Build section lookup
    old_sec_map = {s["section_id"]: s for s in old_sections}
    new_sec_map = {s["section_id"]: s for s in new_sections}

    all_candidates = []

    for pair in matched_pairs:
        match_type = pair["match_type"]

        if match_type == "old_only":
            # Entire section deleted
            old_sec = old_sec_map[pair["old_section_id"]]
            section_blocks = _get_section_blocks(old_blocks, old_sec["start_block_idx"], old_sec["end_block_idx"])
            paras = _get_paragraphs(section_blocks)
            for p in paras:
                text = _normalize_text(p.get("text", ""))
                if text:
                    all_candidates.append(make_candidate(
                        section_path=pair["old_section_path"],
                        object_type="text",
                        change_type="delete",
                        location_hint=f"old_para_idx={p['idx']}",
                        before=text,
                        evidence="section deleted",
                        confidence=1.0,
                    ))
            continue

        if match_type == "new_only":
            # Entire section added
            new_sec = new_sec_map[pair["new_section_id"]]
            section_blocks = _get_section_blocks(new_blocks, new_sec["start_block_idx"], new_sec["end_block_idx"])
            paras = _get_paragraphs(section_blocks)
            for p in paras:
                text = _normalize_text(p.get("text", ""))
                if text:
                    all_candidates.append(make_candidate(
                        section_path=pair["new_section_path"],
                        object_type="text",
                        change_type="add",
                        location_hint=f"new_para_idx={p['idx']}",
                        after=text,
                        evidence="section added",
                        confidence=1.0,
                    ))
            continue

        # Matched pair — diff paragraphs
        old_sec = old_sec_map[pair["old_section_id"]]
        new_sec = new_sec_map[pair["new_section_id"]]

        old_section_blocks = _get_section_blocks(old_blocks, old_sec["start_block_idx"], old_sec["end_block_idx"])
        new_section_blocks = _get_section_blocks(new_blocks, new_sec["start_block_idx"], new_sec["end_block_idx"])

        old_paras = _get_paragraphs(old_section_blocks)
        new_paras = _get_paragraphs(new_section_blocks)

        section_path = pair.get("new_section_path") or pair.get("old_section_path")
        candidates = _diff_paragraphs(old_paras, new_paras, section_path)
        all_candidates.extend(candidates)

    print(f"[diff_text] {len(all_candidates)} text change candidates")
    types = {}
    for c in all_candidates:
        types[c["change_type"]] = types.get(c["change_type"], 0) + 1
    for t, n in sorted(types.items()):
        print(f"  {t}: {n}")

    return all_candidates


def main():
    parser = argparse.ArgumentParser(description="Text diff with move detection")
    parser.add_argument("--work-dir", required=True, help="Work directory with Phase 1 outputs")
    parser.add_argument("--out", required=True, help="Output path for text_candidates.json")
    args = parser.parse_args()

    candidates = run_text_diff(args.work_dir)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
