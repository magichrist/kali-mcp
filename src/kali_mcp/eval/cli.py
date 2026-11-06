"""CLI entry point for running the Phase 6 agent evaluation suite.

Usage:
    python -m kali_mcp.eval.cli --models small,medium,large --interfaces v1,v2 --targets juice_shop,dvwa
    python -m kali_mcp.eval.cli --help
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from kali_mcp.eval import LAB_TARGETS, EvalSuite


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kali-mcp-eval",
        description="Run Kali MCP v2.0.0 agent evaluation suite (Phase 6).",
    )
    parser.add_argument(
        "--models",
        default="small,medium,large",
        help="Comma-separated model names (default: small,medium,large)",
    )
    parser.add_argument(
        "--interfaces",
        default="v1,v2",
        help="Comma-separated interfaces: v1, v2 (default: v1,v2)",
    )
    parser.add_argument(
        "--targets",
        default="juice_shop,dvwa,metasploitable",
        help="Comma-separated lab target names (default: juice_shop,dvwa,metasploitable)",
    )
    parser.add_argument(
        "--workflow",
        default="web_assessment",
        help="Assessment workflow to run (default: web_assessment)",
    )
    parser.add_argument(
        "--output-dir",
        default="eval_results",
        help="Directory for evaluation results (default: eval_results)",
    )
    parser.add_argument(
        "--check-criteria",
        action="store_true",
        help="Check v2.0.0 success criteria after running",
    )
    return parser


async def main_async(args: argparse.Namespace) -> int:
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    interfaces = [i.strip() for i in args.interfaces.split(",") if i.strip()]
    targets = [t.strip() for t in args.targets.split(",") if t.strip()]

    # Validate targets exist in ground truth
    unknown = [t for t in targets if t not in LAB_TARGETS]
    if unknown:
        print(f"Unknown targets: {unknown}", file=sys.stderr)
        print(f"Available: {', '.join(LAB_TARGETS)}", file=sys.stderr)
        return 1

    suite = EvalSuite(output_dir=args.output_dir)
    results = await suite.run_matrix(
        models=models,
        interfaces=interfaces,
        targets=targets,
        workflow=args.workflow,
    )

    print(f"\nEvaluation complete: {len(results)} runs")
    print(f"Results written to: {args.output_dir}/")

    if args.check_criteria:
        criteria = suite.check_success_criteria(results)
        print("\nSuccess Criteria:")
        for name, passed in criteria.items():
            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] {name}")

        all_passed = all(criteria.values())
        print(f"\nOverall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
        return 0 if all_passed else 1

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())