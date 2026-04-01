"""
generate_rows.py — Claude CLI parallel row generation with retry.

Groups change candidates by section_path, sends each group to Claude Code CLI
for structured 5-column row generation, then merges results.
"""

import argparse
import json
import logging
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from scripts.detect_language import detect_language

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
MAX_CANDIDATES_PER_CALL = 30
MAX_RETRIES = 2


def _load_system_prompt(language: str) -> str:
    """Load system prompt and substitute language instruction."""
    prompt_path = PROMPTS_DIR / "change_row_system.txt"
    text = prompt_path.read_text(encoding="utf-8")

    if language == "ko":
        lang_instruction = "한국어로 작성하되, 해시/키/좌표 등 기술 식별자는 원문 그대로 유지하세요."
    else:
        lang_instruction = "Write in English. Keep technical identifiers (hashes, keys, coordinates) as-is."

    return text.replace("{LANGUAGE_INSTRUCTION}", lang_instruction)


def _load_schema() -> str:
    """Load JSON schema as inline string for --json-schema."""
    schema_path = PROMPTS_DIR / "change_row_schema.json"
    schema = json.load(open(schema_path, encoding="utf-8"))
    return json.dumps(schema)


def _build_user_prompt(section_path: str, candidates: list) -> str:
    """Build user prompt for a section group."""
    candidates_json = json.dumps(candidates, ensure_ascii=False, indent=2)
    return f"""The following are change candidates for section "{section_path}".

[Change Candidates (JSON)]
{candidates_json}

Generate comparison table rows. IMPORTANT RULES:

1. AGGRESSIVE MERGING: Merge ALL candidates that share the same logical change theme into ONE row.
   - All SOA (Schedule of Activities) table changes → ideally 1 row per Part (Part A, Part B, etc.)
   - All terminology changes (e.g., 위험성→위해성) across a section → 1 row
   - All table renumbering → 1 row
   - PK sampling time changes → 1 row
   - The goal is MINIMUM rows. A section with 10+ candidates should produce 1-3 rows, NOT 10.

2. FORMAT:
   - page: Use "page_hint" value. If empty, leave blank.
   - item: Section hierarchy: "N. Top Section\\n\\nN.M. Sub Section"
   - previous_version: Key changed content quoted concisely. Use "(...중략...)" for long text.
   - current_version: Key changed content quoted concisely. Use "(...중략...)" for long text.
   - note: Brief reason for change.

3. SKIP whitespace-only or trivial spacing differences."""


def _call_claude_cli(user_prompt: str, system_prompt: str, schema_str: str) -> dict:
    """Call Claude Code CLI and return parsed structured output."""
    cmd = [
        "claude", "-p", user_prompt,
        "--output-format", "json",
        "--json-schema", schema_str,
        "--append-system-prompt", system_prompt,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed (exit {result.returncode}): {result.stderr[:500]}")

    response = json.loads(result.stdout)

    # structured_output contains the schema-enforced result
    structured = response.get("structured_output")
    if not structured:
        raise ValueError("No structured_output in response")

    if isinstance(structured, str):
        structured = json.loads(structured)

    rows = structured.get("rows")
    if rows is None:
        raise ValueError("No 'rows' in structured_output")

    return rows


def generate_rows_for_section(section_path: str, candidates: list, language: str) -> list:
    """Generate rows for a single section (with retry)."""
    system_prompt = _load_system_prompt(language)
    schema_str = _load_schema()
    user_prompt = _build_user_prompt(section_path, candidates)

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            rows = _call_claude_cli(user_prompt, system_prompt, schema_str)
            log.info(f"  [{section_path[:50]}] → {len(rows)} rows (attempt {attempt})")
            return rows
        except Exception as e:
            log.warning(f"  [{section_path[:50]}] attempt {attempt} failed: {e}")
            if attempt > MAX_RETRIES:
                log.error(f"  [{section_path[:50]}] FAILED after {MAX_RETRIES + 1} attempts")
                return []

    return []


def _split_large_group(candidates: list) -> list:
    """Split candidate list into sub-groups of MAX_CANDIDATES_PER_CALL."""
    if len(candidates) <= MAX_CANDIDATES_PER_CALL:
        return [candidates]
    groups = []
    for i in range(0, len(candidates), MAX_CANDIDATES_PER_CALL):
        groups.append(candidates[i:i + MAX_CANDIDATES_PER_CALL])
    return groups


def generate_all_rows(
    candidates_path: str,
    blocks_path: str,
    max_workers: int = 3,
) -> list:
    """
    Generate comparison table rows for all change candidates.

    Returns list of row dicts with 5 fields each.
    """
    candidates = json.load(open(candidates_path, encoding="utf-8"))
    language = detect_language(blocks_path)
    log.info(f"Detected language: {language}")
    log.info(f"Total candidates: {len(candidates)}")

    # Build section order lookup from candidates' position in the list
    # (candidates are already in document order from Phase 2)
    section_order = {}
    for idx, c in enumerate(candidates):
        sp = c["section_path"]
        if sp not in section_order:
            section_order[sp] = idx

    # Group by section_path
    groups = defaultdict(list)
    for c in candidates:
        groups[c["section_path"]].append(c)

    log.info(f"Section groups: {len(groups)}")

    # Build work items (split large groups), preserving section order
    work_items = []
    sorted_section_paths = sorted(groups.keys(), key=lambda sp: section_order.get(sp, 999999))
    for section_path in sorted_section_paths:
        section_candidates = groups[section_path]
        sub_groups = _split_large_group(section_candidates)
        for i, sub in enumerate(sub_groups):
            label = section_path if len(sub_groups) == 1 else f"{section_path} (part {i+1})"
            work_items.append((label, sub))

    log.info(f"Work items (after splitting): {len(work_items)}")

    # Parallel execution — tag rows with section order for sorting
    all_rows = []  # list of (sort_key, row)
    failed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_info = {}
        for wi_idx, (label, sub_candidates) in enumerate(work_items):
            future = executor.submit(
                generate_rows_for_section, label, sub_candidates, language
            )
            # Use section_order + work_item index for stable sort
            sort_key = section_order.get(label.split(" (part")[0], 999999)
            future_to_info[future] = (label, sort_key, wi_idx)

        for future in as_completed(future_to_info):
            label, sort_key, wi_idx = future_to_info[future]
            try:
                rows = future.result()
                if rows:
                    for row in rows:
                        all_rows.append((sort_key, wi_idx, row))
                else:
                    failed += 1
            except Exception as e:
                log.error(f"  [{label[:50]}] unexpected error: {e}")
                failed += 1

    # Sort by document order
    all_rows.sort(key=lambda x: (x[0], x[1]))
    all_rows = [row for _, _, row in all_rows]

    log.info(f"Total rows generated: {len(all_rows)}")
    if failed:
        log.warning(f"Failed groups: {failed}")

    return all_rows


def main():
    parser = argparse.ArgumentParser(description="Generate comparison table rows via Claude CLI")
    parser.add_argument("--candidates", required=True, help="Path to change_candidates.json")
    parser.add_argument("--blocks", required=True, help="Path to blocks.json (for language detection)")
    parser.add_argument("--out", required=True, help="Output path for change_rows.json")
    parser.add_argument("--max-workers", type=int, default=3, help="Max parallel Claude CLI calls")
    args = parser.parse_args()

    rows = generate_all_rows(args.candidates, args.blocks, args.max_workers)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    print(f"[generate_rows] {len(rows)} rows written to {out_path}")


if __name__ == "__main__":
    main()
