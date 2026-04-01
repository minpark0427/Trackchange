"""
cli.py — Unified CLI entry point for trackchange.

Usage:
  trackchange compare --old V1.docx --new V2.docx --out work/
  trackchange validate --reference ref.docx --generated work/output/gen.docx --out-dir work/validation/
  trackchange validate --reference ref.docx --generated-json work/rows/change_rows.json --out-dir work/validation/ --llm
"""

import argparse
import subprocess
import sys
from pathlib import Path


def cmd_compare(args):
    """Run full pipeline: Phase 1 → 2 → 3 → 4."""
    work = Path(args.out)
    old_docx = args.old
    new_docx = args.new
    workers = str(args.max_workers)

    scripts_dir = Path(__file__).parent

    steps = [
        ("Phase 1: Section Split", [
            sys.executable, str(scripts_dir / "run_split.py"),
            "--old", old_docx, "--new", new_docx, "--out", str(work),
        ]),
        ("Phase 2: Diff Detection", [
            sys.executable, str(scripts_dir / "run_diff.py"),
            "--work-dir", str(work),
            "--out", str(work / "diff" / "change_candidates.json"),
        ]),
        ("Phase 3: Row Generation (Claude CLI)", [
            sys.executable, str(scripts_dir / "run_rows.py"),
            "--work-dir", str(work),
            "--out", str(work / "rows" / "change_rows.json"),
            "--max-workers", workers,
        ]),
        ("Phase 4: DOCX Export", [
            sys.executable, str(scripts_dir / "run_export.py"),
            "--work-dir", str(work),
            "--out-dir", str(work / "output"),
        ]),
    ]

    for phase_name, cmd in steps:
        print(f"\n{'='*60}")
        print(f"  {phase_name}")
        print(f"{'='*60}\n")
        result = subprocess.run(cmd, cwd=str(scripts_dir.parent))
        if result.returncode != 0:
            print(f"\nError: {phase_name} failed (exit {result.returncode})", file=sys.stderr)
            sys.exit(result.returncode)

    print(f"\nDone. Output: {work / 'output'}")


def cmd_validate(args):
    """Run Phase 5: validation."""
    scripts_dir = Path(__file__).parent
    cmd = [
        sys.executable, str(scripts_dir / "run_validate.py"),
        "--reference", args.reference,
        "--out-dir", args.out_dir,
    ]
    if args.generated:
        cmd += ["--generated", args.generated]
    if args.generated_json:
        cmd += ["--generated-json", args.generated_json]
    if args.llm:
        cmd += ["--llm"]

    result = subprocess.run(cmd, cwd=str(scripts_dir.parent))
    sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(
        prog="trackchange",
        description="DOCX Comparison Table of Change generator for clinical trial protocols",
        epilog="Examples:\n"
               "  trackchange compare --old V1.docx --new V2.docx --out work/\n"
               "  trackchange validate --reference ref.docx --generated-json work/rows/change_rows.json --out-dir work/validation/ --llm",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # compare
    p_compare = sub.add_parser("compare", help="Generate comparison table (Phase 1-4)")
    p_compare.add_argument("--old", required=True, help="Path to old version DOCX")
    p_compare.add_argument("--new", required=True, help="Path to new version DOCX")
    p_compare.add_argument("--out", required=True, help="Work directory for outputs")
    p_compare.add_argument("--max-workers", type=int, default=3, help="Max parallel Claude CLI calls (default: 3)")

    # validate
    p_validate = sub.add_parser("validate", help="Validate against reference (Phase 5)")
    p_validate.add_argument("--reference", required=True, help="Human-authored reference comparison table DOCX")
    p_validate.add_argument("--generated", help="Generated comparison table DOCX")
    p_validate.add_argument("--generated-json", help="change_rows.json (alternative to --generated)")
    p_validate.add_argument("--out-dir", required=True, help="Output directory for validation report")
    p_validate.add_argument("--llm", action="store_true", help="Enable LLM semantic evaluation (requires Claude CLI)")

    args = parser.parse_args()

    if args.command == "compare":
        cmd_compare(args)
    elif args.command == "validate":
        cmd_validate(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
