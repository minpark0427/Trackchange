"""
diff_media.py — Image SHA-256 hash comparison between old/new DOCX versions.
"""

import argparse
import json
import sys
from pathlib import Path

from scripts.schema import make_candidate


def run_media_diff(old_media_path: str, new_media_path: str) -> list:
    """Compare media inventories by filename and SHA-256 hash."""
    old_media = json.load(open(old_media_path, encoding="utf-8"))
    new_media = json.load(open(new_media_path, encoding="utf-8"))

    candidates = []
    all_files = set(list(old_media.keys()) + list(new_media.keys()))

    for fname in sorted(all_files):
        old_entry = old_media.get(fname)
        new_entry = new_media.get(fname)

        if old_entry and new_entry:
            if old_entry["sha256"] != new_entry["sha256"]:
                candidates.append(make_candidate(
                    section_path="(media)",
                    object_type="image",
                    change_type="modify",
                    location_hint=fname,
                    before=f"sha256={old_entry['sha256'][:16]}... size={old_entry['size']}",
                    after=f"sha256={new_entry['sha256'][:16]}... size={new_entry['size']}",
                    evidence=f"old_hash={old_entry['sha256']}, new_hash={new_entry['sha256']}, old_size={old_entry['size']}, new_size={new_entry['size']}",
                    confidence=1.0,
                ))
        elif old_entry and not new_entry:
            candidates.append(make_candidate(
                section_path="(media)",
                object_type="image",
                change_type="delete",
                location_hint=fname,
                before=f"sha256={old_entry['sha256'][:16]}... size={old_entry['size']}",
                evidence=f"image removed: {fname}",
                confidence=1.0,
            ))
        else:
            candidates.append(make_candidate(
                section_path="(media)",
                object_type="image",
                change_type="add",
                location_hint=fname,
                after=f"sha256={new_entry['sha256'][:16]}... size={new_entry['size']}",
                evidence=f"image added: {fname}",
                confidence=1.0,
            ))

    print(f"[diff_media] {len(candidates)} media change candidates")
    for c in candidates:
        print(f"  {c['change_type']}: {c['location_hint']}")

    return candidates


def main():
    parser = argparse.ArgumentParser(description="Media hash diff")
    parser.add_argument("--old-media", required=True)
    parser.add_argument("--new-media", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    candidates = run_media_diff(args.old_media, args.new_media)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
