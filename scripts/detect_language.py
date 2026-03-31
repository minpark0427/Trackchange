"""
detect_language.py — Detect document language by checking for Korean characters.

Any Korean character (가-힣) → "ko", otherwise → "en".
"""

import json
import re
import sys


def detect_language_from_text(text: str) -> str:
    """Return 'ko' if any Korean character found, else 'en'."""
    if re.search(r"[가-힣]", text):
        return "ko"
    return "en"


def detect_language(blocks_path: str) -> str:
    """Detect language from blocks.json file."""
    blocks = json.load(open(blocks_path, encoding="utf-8"))
    for block in blocks:
        text = block.get("text", "")
        if re.search(r"[가-힣]", text):
            return "ko"
    return "en"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python detect_language.py <blocks.json>")
        sys.exit(1)
    print(detect_language(sys.argv[1]))
