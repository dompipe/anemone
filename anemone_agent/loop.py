"""Agent loop: plan → act → check → iterate."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .checks import CheckResult, checks_passed, run_checks
from .context import build_context_block, gather_context
from .ollama import OllamaProvider
from .patcher import PatchError, extract_and_apply

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an expert software engineer working on a Python project.
When asked to perform a coding task you MUST respond with file edits.

Prefer outputting edits as a unified diff enclosed in a ```diff ... ``` fenced block.
Alternatively, you may output a JSON array enclosed in a ```json ... ``` fenced block
where each element has: {"action": "create"|"update"|"delete", "path": "...", "content": "..."}.

Only output the edits – do not include any other prose outside the fenced block unless
asked for a plan.
"""

_PLAN_PROMPT = """\
Given the task below and the repository context, produce a concise numbered plan
(max 10 steps) describing what code changes are needed. Do NOT write any code yet.

TASK:
{task}

CONTEXT:
{context}
"""

_ACT_PROMPT = """\
Now implement the plan using file edits.

TASK:
{task}

PLAN:
{plan}

CONTEXT:
{context}

Output ONLY the file edits (unified diff or JSON array as described). No prose.
"""

_FIX_PROMPT = """\
The previous edits caused check failures. Fix them.

TASK:
{task}

CHECK FAILURES:
{failures}

CONTEXT:
{context}

Output ONLY the corrective file edits. No prose.
"""


@dataclass
class IterationResult:
    iteration: int
    plan: str
    affected_files: List[str]
    check_results: List[CheckResult]
    success: bool


@dataclass
class AgentResult:
    task: str
    iterations: List[IterationResult] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None


def run_agent(
    task: str,
    repo_root: str = ".",
    model: str = "llama3.1",
    ollama_url: str = "http://localhost:11434",
    max_iterations: int = 5,
    run_ruff: bool = True,
    run_pytest: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
) -> AgentResult:
    """Execute the full agent loop and return an :class:`AgentResult`."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    provider = OllamaProvider(base_url=ollama_url, model=model)
    base = Path(repo_root).resolve()
    result = AgentResult(task=task)

    # ── gather initial context ──────────────────────────────────────────────
    ctx_files = gather_context(repo_root)
    context_block = build_context_block(ctx_files)

    # ── planning step ───────────────────────────────────────────────────────
    plan_msg = _PLAN_PROMPT.format(task=task, context=context_block)
    logger.info("Requesting plan from Ollama (%s)…", model)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": plan_msg},
    ]
    try:
        plan = provider.chat(messages)
    except Exception as exc:
        result.error = str(exc)
        return result

    logger.info("Plan:\n%s", plan)

    # ── iteration loop ──────────────────────────────────────────────────────
    failure_feedback = ""
    for iteration in range(1, max_iterations + 1):
        logger.info("── Iteration %d / %d ──", iteration, max_iterations)

        # Refresh context on each iteration to pick up previous edits
        ctx_files = gather_context(repo_root)
        context_block = build_context_block(ctx_files)

        if iteration == 1:
            act_msg = _ACT_PROMPT.format(
                task=task, plan=plan, context=context_block
            )
        else:
            act_msg = _FIX_PROMPT.format(
                task=task, failures=failure_feedback, context=context_block
            )

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": act_msg},
        ]

        try:
            llm_output = provider.chat(messages)
        except Exception as exc:
            result.error = str(exc)
            return result

        logger.debug("LLM output:\n%s", llm_output)

        # Apply patches
        try:
            affected = extract_and_apply(base, llm_output, dry_run=dry_run)
        except PatchError as exc:
            logger.warning("Patch error: %s", exc)
            affected = []

        if not affected:
            logger.info("No file edits detected in LLM output.")

        # Run checks
        check_results = run_checks(
            repo_root,
            run_ruff_check=run_ruff,
            run_pytest_check=run_pytest,
        )

        success = checks_passed(check_results)

        iter_result = IterationResult(
            iteration=iteration,
            plan=plan if iteration == 1 else "",
            affected_files=affected,
            check_results=check_results,
            success=success,
        )
        result.iterations.append(iter_result)

        if success:
            result.success = True
            logger.info("All checks passed on iteration %d.", iteration)
            break

        # Build failure feedback for next iteration
        failure_feedback = "\n\n".join(
            r.feedback() for r in check_results if not r.passed and not r.skipped
        )
        logger.info("Checks failed; will iterate.\n%s", failure_feedback)

    return result
