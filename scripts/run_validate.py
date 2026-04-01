"""
run_validate.py — Phase 5: Validate generated comparison table against human reference.

Usage:
  python3 scripts/run_validate.py \
    --reference "ref_comparison_table.docx" \
    --generated "work/output/generated.docx" \
    --out-dir work/validation/

  # With LLM semantic evaluation:
  python3 scripts/run_validate.py \
    --reference "ref_comparison_table.docx" \
    --generated-json "work/rows/change_rows.json" \
    --out-dir work/validation/ --llm
"""

import argparse
import json
import logging
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Phase 5: Validate comparison table against reference")
    parser.add_argument("--reference", required=True, help="Path to human-authored reference DOCX")
    parser.add_argument("--generated", help="Path to generated comparison table DOCX")
    parser.add_argument("--generated-json", help="Path to change_rows.json (alternative to --generated)")
    parser.add_argument("--out-dir", required=True, help="Output directory for validation report")
    parser.add_argument("--llm", action="store_true", help="Enable LLM-based semantic evaluation (uses Claude CLI)")
    args = parser.parse_args()

    if not args.generated and not args.generated_json:
        print("Error: provide --generated (DOCX) or --generated-json", file=sys.stderr)
        sys.exit(1)

    ref_path = Path(args.reference)
    if not ref_path.exists():
        print(f"Error: Reference file not found: {ref_path}", file=sys.stderr)
        sys.exit(1)

    # Setup logging for LLM mode
    if args.llm:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        from scripts.validate_table import (
            read_docx_table, read_json_rows, match_rows,
            generate_report, print_summary, llm_score_matches,
        )
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.validate_table import (
            read_docx_table, read_json_rows, match_rows,
            generate_report, print_summary, llm_score_matches,
        )

    steps = 4 if args.llm else 3

    print("=" * 60)
    print("Phase 5: Validation Report")
    if args.llm:
        print("  (LLM semantic evaluation enabled)")
    print("=" * 60)
    print()

    # Step 1: Read reference
    print(f"[Step 1/{steps}] Reading reference DOCX...")
    ref_rows = read_docx_table(str(ref_path))
    print(f"  Reference rows: {len(ref_rows)}")
    print()

    # Step 2: Read generated
    print(f"[Step 2/{steps}] Reading generated output...")
    if args.generated_json:
        gen_path = args.generated_json
        gen_rows = read_json_rows(gen_path)
    else:
        gen_path = args.generated
        if not Path(gen_path).exists():
            print(f"Error: Generated file not found: {gen_path}", file=sys.stderr)
            sys.exit(1)
        gen_rows = read_docx_table(gen_path)
    print(f"  Generated rows: {len(gen_rows)}")
    print()

    # Step 3: Match and score (text-based)
    print(f"[Step 3/{steps}] Matching and scoring (text-based)...")
    match_results, used_gen = match_rows(ref_rows, gen_rows)
    report = generate_report(ref_rows, gen_rows, match_results, used_gen, str(ref_path), str(gen_path))
    print()

    # Step 4 (optional): LLM semantic evaluation
    if args.llm:
        print(f"[Step 4/{steps}] LLM semantic evaluation...")
        report = llm_score_matches(report, gen_rows)
        print()

    # Print summary
    print_summary(report)

    # Write output
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "validation_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 60)
    print(f"Output: {report_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
