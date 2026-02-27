"""CLI entry point for the Anemone coding agent."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, Optional

from .loop import run_agent
from .ollama import OllamaError

#: Math output mode choices
MATH_MODES = ("off", "auto", "annotated", "json", "latex")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anemone",
        description=(
            "Anemone – a local Ollama-backed coding agent that plans, edits, "
            "and iterates on your codebase."
        ),
    )
    parser.add_argument(
        "task",
        nargs="?",
        help="Natural-language task description (also accepts --task).",
    )
    parser.add_argument("--task", dest="task_flag", metavar="TASK", default=None)
    parser.add_argument(
        "--model",
        default=os.environ.get("ANEMONE_MODEL", "llama3.1"),
        help="Ollama model name (default: llama3.1).",
    )
    parser.add_argument(
        "--ollama-url",
        default=os.environ.get("ANEMONE_OLLAMA_URL", "http://localhost:11434"),
        help="Ollama base URL (default: http://localhost:11434).",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=int(os.environ.get("ANEMONE_MAX_ITERATIONS", "5")),
        help="Maximum agent iterations (default: 5).",
    )
    parser.add_argument(
        "--repo-root",
        default=os.environ.get("ANEMONE_REPO_ROOT", "."),
        help="Root directory of the target repository (default: .).",
    )
    parser.add_argument(
        "--no-ruff",
        action="store_true",
        help="Disable ruff check.",
    )
    parser.add_argument(
        "--no-pytest",
        action="store_true",
        help="Disable pytest.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print patches without applying them.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging.",
    )
    parser.add_argument(
        "--math",
        choices=MATH_MODES,
        default=os.environ.get("ANEMONE_MATH", "auto"),
        metavar="MODE",
        help=(
            "Math solving mode: off | auto | annotated | json | latex "
            "(default: auto).  In 'auto' mode the agent detects math queries "
            "and solves them locally with sympy+pint without needing Ollama."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Resolve task from positional or --task flag
    task = args.task or args.task_flag
    if not task:
        parser.error("Please provide a task description (positional or --task).")

    # ── Math shortcut ────────────────────────────────────────────────────────
    math_mode = args.math
    if math_mode != "off":
        from .math_solver import is_math_query, MathSolverError

        _is_math = (math_mode != "auto") or is_math_query(task)
        if _is_math:
            _exit = _handle_math_task(task, math_mode)
            if _exit is not None:
                return _exit

    # ── Normal coding-agent flow ─────────────────────────────────────────────
    print(f"[anemone] Task: {task}")
    print(f"[anemone] Model: {args.model}  URL: {args.ollama_url}")
    if args.dry_run:
        print("[anemone] DRY RUN – patches will be printed but not applied.")

    try:
        result = run_agent(
            task=task,
            repo_root=args.repo_root,
            model=args.model,
            ollama_url=args.ollama_url,
            max_iterations=args.max_iterations,
            run_ruff=not args.no_ruff,
            run_pytest=not args.no_pytest,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
    except OllamaError as exc:
        print(f"\n[anemone] ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[anemone] Interrupted.", file=sys.stderr)
        return 130

    if result.error:
        print(f"\n[anemone] ERROR: {result.error}", file=sys.stderr)
        return 1

    print()
    for ir in result.iterations:
        if ir.plan:
            print(f"[anemone] PLAN:\n{ir.plan}\n")
        print(f"[anemone] Iteration {ir.iteration}: files edited: {ir.affected_files}")
        for cr in ir.check_results:
            print(f"  {cr.summary()}")
            if not cr.passed and not cr.skipped:
                if cr.stdout.strip():
                    print(cr.stdout.strip())
                if cr.stderr.strip():
                    print(cr.stderr.strip())

    if result.success:
        print("\n[anemone] ✓ Task complete – all checks passed.")
        return 0
    else:
        print(
            f"\n[anemone] ✗ Max iterations ({args.max_iterations}) reached without all checks passing.",
            file=sys.stderr,
        )
        return 1


def _handle_math_task(task: str, math_mode: str) -> int | None:
    """Attempt to solve *task* as a math expression.

    Returns an exit code (int) when the task has been handled, or ``None``
    if the task should fall through to the normal coding-agent flow.
    """
    from .math_solver import (
        MathSolverError,
        evaluate_expression,
        render_annotated,
        render_json,
        render_latex,
    )

    # Try direct expression evaluation first
    try:
        result_dict = evaluate_expression(task)
    except MathSolverError:
        # Not a plain expression – fall through to the agent loop
        return None

    # Build a minimal schema result for rendering
    schema_result = {
        "given": {},
        "unknowns": ["result"],
        "steps": [
            {
                "step": 1,
                "description": "Evaluate expression",
                "expression": task,
                "substituted": task,
                "result": result_dict["result"],
                "unit": None,
                "converted": None,
                "error": None,
            }
        ],
        "answer": result_dict["result"],
        "answer_unit": None,
        "answer_var": "result",
        "assumptions": [],
        "sanity_check": None,
    }

    _render_and_print(schema_result, math_mode)
    return 0


def _render_and_print(result: Dict[str, Any], math_mode: str) -> None:
    """Print *result* according to *math_mode*."""
    from .math_solver import render_annotated, render_json, render_latex

    if math_mode == "json":
        print(render_json(result))
    elif math_mode == "latex":
        print(render_latex(result))
    else:
        # annotated is the default for "annotated" and "auto"
        print(render_annotated(result))


if __name__ == "__main__":
    sys.exit(main())
