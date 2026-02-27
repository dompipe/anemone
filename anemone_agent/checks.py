"""Run ruff and pytest checks and return structured results."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import List


@dataclass
class CheckResult:
    tool: str
    passed: bool
    stdout: str
    stderr: str
    returncode: int
    skipped: bool = False
    skip_reason: str = ""

    def summary(self) -> str:
        if self.skipped:
            return f"[{self.tool}] SKIPPED – {self.skip_reason}"
        status = "PASSED" if self.passed else "FAILED"
        return f"[{self.tool}] {status} (exit {self.returncode})"

    def feedback(self) -> str:
        """Return a compact feedback string suitable for inclusion in the next prompt."""
        if self.skipped:
            return ""
        parts = [self.summary()]
        if self.stdout.strip():
            parts.append(self.stdout.strip())
        if self.stderr.strip():
            parts.append(self.stderr.strip())
        return "\n".join(parts)


def _run(cmd: List[str], cwd: str, timeout: int = 120) -> CheckResult:
    tool = cmd[0]
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CheckResult(
            tool=tool,
            passed=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
            returncode=proc.returncode,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            tool=tool,
            passed=False,
            stdout="",
            stderr=f"{tool} timed out after {timeout}s",
            returncode=-1,
        )


def run_ruff(repo_root: str, timeout: int = 60) -> CheckResult:
    """Run ``ruff check .`` in *repo_root*."""
    if not shutil.which("ruff"):
        return CheckResult(
            tool="ruff",
            passed=True,
            stdout="",
            stderr="",
            returncode=0,
            skipped=True,
            skip_reason="ruff not found – install with `pip install ruff`",
        )
    return _run(["ruff", "check", "."], cwd=repo_root, timeout=timeout)


def run_pytest(repo_root: str, timeout: int = 120) -> CheckResult:
    """Run ``pytest`` in *repo_root*."""
    if not shutil.which("pytest"):
        return CheckResult(
            tool="pytest",
            passed=True,
            stdout="",
            stderr="",
            returncode=0,
            skipped=True,
            skip_reason="pytest not found – install with `pip install pytest`",
        )
    return _run(["pytest", "--tb=short", "-q"], cwd=repo_root, timeout=timeout)


def run_checks(
    repo_root: str,
    run_ruff_check: bool = True,
    run_pytest_check: bool = True,
    ruff_timeout: int = 60,
    pytest_timeout: int = 120,
) -> List[CheckResult]:
    """Run enabled checks and return results in order."""
    results: List[CheckResult] = []
    if run_ruff_check:
        results.append(run_ruff(repo_root, timeout=ruff_timeout))
    if run_pytest_check:
        results.append(run_pytest(repo_root, timeout=pytest_timeout))
    return results


def checks_passed(results: List[CheckResult]) -> bool:
    """Return True if all non-skipped checks passed."""
    return all(r.passed for r in results)
