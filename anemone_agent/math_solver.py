"""Safe, tool-backed math solver with unit support and annotated output.

Provides:
- ``evaluate_expression`` – safe symbolic/numeric evaluation via sympy.
- ``convert_units``        – unit conversion via pint (optional dependency).
- ``solve_schema``         – executes a structured Math Schema (from LLM extraction).
- ``render_annotated``     – student-style annotated solution text.
- ``render_json``          – machine-readable JSON output.
- ``render_latex``         – LaTeX-style formatted output.
- ``is_math_query``        – heuristic auto-detection of math queries.
"""

from __future__ import annotations

import json
import re
import threading
from typing import Any, Dict, List, Optional

from sympy import N, Eq, solve as sympy_solve, sympify, SympifyError

# ---------------------------------------------------------------------------
# Optional pint dependency for unit support
# ---------------------------------------------------------------------------
try:
    import pint as _pint

    _ureg = _pint.UnitRegistry()
    _PINT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ureg = None  # type: ignore[assignment]
    _PINT_AVAILABLE = False

# ---------------------------------------------------------------------------
# Safety constants
# ---------------------------------------------------------------------------
MAX_EXPR_LENGTH = 500
MAX_COMPUTE_STEPS = 50
TIMEOUT_SECONDS = 5

# Patterns that must never appear in an expression fed to sympy.
_UNSAFE_PATTERN = re.compile(
    r"\b(import|exec|eval|open|compile|getattr|setattr|delattr|globals|locals|"
    r"vars|dir|help|print|input|callable|type|classmethod|staticmethod|"
    r"__[a-zA-Z_]+__)\b"
)


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------
class MathSolverError(Exception):
    """Raised for validation or computation errors."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _run_with_timeout(fn, timeout: int = TIMEOUT_SECONDS):
    """Run *fn* in a daemon thread; raise TimeoutError if it takes too long.

    Note: the daemon thread continues executing after the timeout is raised.
    This is acceptable for pure sympy arithmetic (no shared state mutation).
    For more aggressive isolation, callers may use multiprocessing instead.
    """
    result: Dict[str, Any] = {}

    def _worker():
        try:
            result["value"] = fn()
        except Exception as exc:  # noqa: BLE001
            result["error"] = exc

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"Math evaluation timed out after {timeout}s.")
    if "error" in result:
        raise result["error"]
    return result.get("value")


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------
def evaluate_expression(expr: str) -> Dict[str, Any]:
    """Safely evaluate a math expression and return a structured result.

    Parameters
    ----------
    expr:
        A mathematical expression string, e.g. ``"2 + 3 * 4"`` or ``"60 * 1.5"``.

    Returns
    -------
    dict with keys ``expression``, ``result`` (float), ``symbolic`` (str).

    Raises
    ------
    MathSolverError
        If the expression is empty, too long, contains unsafe patterns, or
        cannot be evaluated.
    """
    expr = (expr or "").strip()
    if not expr:
        raise MathSolverError("Empty expression.")
    if len(expr) > MAX_EXPR_LENGTH:
        raise MathSolverError(
            f"Expression too long ({len(expr)} chars; max {MAX_EXPR_LENGTH})."
        )
    if _UNSAFE_PATTERN.search(expr):
        raise MathSolverError("Unsafe expression: forbidden keyword detected.")

    def _eval():
        sym = sympify(expr, evaluate=True)
        numeric = float(N(sym))
        return sym, numeric

    try:
        sym, numeric = _run_with_timeout(_eval)
    except TimeoutError as exc:
        raise MathSolverError(str(exc)) from exc
    except (SympifyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise MathSolverError(f"Could not evaluate expression '{expr}': {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise MathSolverError(f"Unexpected error evaluating '{expr}': {exc}") from exc

    return {"expression": expr, "result": numeric, "symbolic": str(sym)}


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------
def convert_units(value: float, from_unit: str, to_unit: str) -> Dict[str, Any]:
    """Convert *value* from *from_unit* to *to_unit* using pint.

    Raises
    ------
    MathSolverError
        If pint is not installed or the conversion fails.
    """
    if not _PINT_AVAILABLE:
        raise MathSolverError(
            "pint is not installed. Install it with: pip install pint"
        )
    try:
        qty = _ureg.Quantity(value, from_unit)
        converted = qty.to(to_unit)
        return {
            "value": value,
            "from_unit": from_unit,
            "to_unit": to_unit,
            "result": float(converted.magnitude),
            "result_with_unit": str(converted),
        }
    except _pint.errors.DimensionalityError as exc:
        raise MathSolverError(
            f"Incompatible units '{from_unit}' → '{to_unit}': {exc}"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise MathSolverError(f"Unit conversion failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Schema solver (word-problem pipeline)
# ---------------------------------------------------------------------------
def solve_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Execute compute steps from a structured Math Schema.

    The *schema* dict may contain:

    - ``given``         – ``{variable: numeric_value, ...}``
    - ``unknowns``      – ``[variable_name, ...]``
    - ``compute_steps`` – list of step dicts (see below)
    - ``assumptions``   – list of assumption strings
    - ``answer_unit``   – string unit for the final answer
    - ``sanity_check``  – expression string to verify the answer

    Each step dict may contain:

    - ``expression``  – math expression (may reference variables)
    - ``assign``      – variable name to store the result in
    - ``description`` – human-readable step description
    - ``unit``        – unit label for the result (display only)
    - ``from_unit``   – source unit for conversion
    - ``to_unit``     – target unit for conversion

    Returns
    -------
    dict with ``given``, ``unknowns``, ``steps``, ``answer``,
    ``answer_unit``, ``answer_var``, ``assumptions``, ``sanity_check``.
    """
    given = dict(schema.get("given") or {})
    unknowns: List[str] = list(schema.get("unknowns") or [])
    compute_steps: List[Dict[str, Any]] = list(schema.get("compute_steps") or [])

    if len(compute_steps) > MAX_COMPUTE_STEPS:
        raise MathSolverError(
            f"Too many compute steps ({len(compute_steps)}; max {MAX_COMPUTE_STEPS})."
        )

    env: Dict[str, Any] = {k: v for k, v in given.items() if isinstance(v, (int, float))}
    steps: List[Dict[str, Any]] = []

    for i, step in enumerate(compute_steps, 1):
        step_expr: str = str(step.get("expression") or "").strip()
        step_assign: Optional[str] = step.get("assign") or None
        step_desc: str = str(step.get("description") or f"Step {i}")
        step_unit: Optional[str] = step.get("unit") or None
        from_unit: Optional[str] = step.get("from_unit") or None
        to_unit: Optional[str] = step.get("to_unit") or None

        if not step_expr:
            continue

        # Substitute known numeric variables into the expression
        subst_expr = _substitute(step_expr, env)

        result_val: Optional[float] = None
        err_msg: Optional[str] = None
        converted: Optional[Dict[str, Any]] = None

        try:
            eval_result = evaluate_expression(subst_expr)
            result_val = eval_result["result"]
        except MathSolverError as exc:
            err_msg = str(exc)

        # Unit conversion (only when result is available)
        if result_val is not None and from_unit and to_unit and _PINT_AVAILABLE:
            try:
                converted = convert_units(result_val, from_unit, to_unit)
                result_val = converted["result"]
                step_unit = to_unit
            except MathSolverError:
                pass  # keep unconverted value

        if step_assign is not None and result_val is not None:
            env[step_assign] = result_val

        steps.append(
            {
                "step": i,
                "description": step_desc,
                "expression": step_expr,
                "substituted": subst_expr,
                "result": result_val,
                "unit": step_unit,
                "converted": converted,
                "error": err_msg,
            }
        )

    # Determine final answer
    final_var: Optional[str] = unknowns[0] if unknowns else None
    final_value: Optional[float] = env.get(final_var) if final_var else None
    answer_unit: Optional[str] = schema.get("answer_unit") or None

    # Sanity check
    sanity_str: Optional[str] = schema.get("sanity_check") or None
    sanity_result: Optional[Dict[str, Any]] = None
    if sanity_str and final_value is not None:
        check_env = dict(env)
        if final_var:
            check_env[final_var] = final_value
        try:
            sanity_subst = _substitute(sanity_str, check_env)
            sanity_result = evaluate_expression(sanity_subst)
        except MathSolverError:
            pass

    return {
        "given": given,
        "unknowns": unknowns,
        "steps": steps,
        "answer": final_value,
        "answer_unit": answer_unit,
        "answer_var": final_var,
        "assumptions": list(schema.get("assumptions") or []),
        "sanity_check": sanity_result,
    }


def _substitute(expr: str, env: Dict[str, Any]) -> str:
    """Replace bare variable names in *expr* with their numeric values from *env*."""
    result = expr
    # Sort by descending length so longer names are substituted first
    for var in sorted(env.keys(), key=len, reverse=True):
        val = env[var]
        if isinstance(val, (int, float)):
            result = re.sub(
                r"(?<![a-zA-Z_0-9])" + re.escape(var) + r"(?![a-zA-Z_0-9])",
                str(val),
                result,
            )
    return result


# ---------------------------------------------------------------------------
# Output renderers
# ---------------------------------------------------------------------------
def render_annotated(result: Dict[str, Any]) -> str:
    """Render a solved math result as a student-style annotated solution."""
    lines: List[str] = []
    lines.append("=" * 52)
    lines.append("  MATH SOLUTION")
    lines.append("=" * 52)

    given = result.get("given") or {}
    if given:
        lines.append("\nGiven:")
        for var, val in given.items():
            lines.append(f"  {var} = {val}")

    unknowns = result.get("unknowns") or []
    if unknowns:
        lines.append("\nFind:")
        for u in unknowns:
            lines.append(f"  {u}")

    steps = result.get("steps") or []
    if steps:
        lines.append("\nSolution Steps:")
        for s in steps:
            n = s.get("step", "?")
            desc = s.get("description", "")
            expr = s.get("expression", "")
            subst = s.get("substituted", "")
            val = s.get("result")
            unit = s.get("unit") or ""
            err = s.get("error")
            conv = s.get("converted")

            lines.append(f"\n  Step {n}: {desc}")
            if expr and expr != subst:
                lines.append(f"    Formula:    {expr}")
                lines.append(f"    Substitute: {subst}")
            elif expr:
                lines.append(f"    Evaluate:   {expr}")

            if err:
                lines.append(f"    ERROR: {err}")
            elif val is not None:
                val_str = f"{val:.6g}"
                if unit:
                    val_str += f" {unit}"
                lines.append(f"    Result:     {val_str}")

            if conv:
                lines.append(f"    Converted:  {conv.get('result_with_unit', '')}")

    lines.append("\n" + "-" * 52)
    answer = result.get("answer")
    answer_unit = result.get("answer_unit") or ""
    answer_var = result.get("answer_var") or "answer"
    if answer is not None:
        ans_str = f"{answer:.6g}"
        if answer_unit:
            ans_str += f" {answer_unit}"
        lines.append(f"  ANSWER:  {answer_var} = {ans_str}")
    else:
        lines.append("  ANSWER:  (could not determine)")

    assumptions = result.get("assumptions") or []
    if assumptions:
        lines.append("\nAssumptions:")
        for a in assumptions:
            lines.append(f"  - {a}")

    sanity = result.get("sanity_check")
    if sanity:
        lines.append(
            f"\nSanity check:  {sanity.get('expression', '')} = {sanity.get('result', '')}"
        )

    lines.append("=" * 52)
    return "\n".join(lines)


def render_json(result: Dict[str, Any]) -> str:
    """Render a solved math result as formatted JSON."""
    return json.dumps(result, indent=2, default=str)


def render_latex(result: Dict[str, Any]) -> str:
    """Render a solved math result with LaTeX-style formatting."""
    lines: List[str] = []

    given = result.get("given") or {}
    if given:
        lines.append(r"\textbf{Given:}")
        for var, val in given.items():
            lines.append(f"  ${var} = {val}$")

    steps = result.get("steps") or []
    if steps:
        lines.append(r"\textbf{Solution Steps:}")
        for s in steps:
            desc = s.get("description", "")
            expr = s.get("expression", "")
            val = s.get("result")
            unit = s.get("unit") or ""
            n = s.get("step", "?")
            lines.append(f"  {n}. {desc}")
            if expr:
                lines.append(f"  $${expr}$$")
            if val is not None:
                val_str = f"{val:.6g}"
                if unit:
                    val_str += r"\,\text{" + unit + "}"
                lines.append(f"  $= {val_str}$")

    answer = result.get("answer")
    answer_unit = result.get("answer_unit") or ""
    answer_var = result.get("answer_var") or "answer"
    if answer is not None:
        ans_str = f"{answer:.6g}"
        if answer_unit:
            ans_str += r"\,\text{" + answer_unit + "}"
        lines.append(r"\textbf{Answer:} " + f"${answer_var} = {ans_str}$")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------
_MATH_KEYWORDS = frozenset(
    [
        "how many",
        "how much",
        "calculate",
        "compute",
        "solve",
        "find",
        "what is",
        "evaluate",
        "convert",
        "mph",
        "km/h",
        "meters",
        "feet",
        "miles",
        "kilograms",
        "pounds",
        "liters",
        "gallons",
        "celsius",
        "fahrenheit",
        "distance",
        "speed",
        "time",
        "rate",
        "total",
        "sum",
        "product",
        "average",
        "percent",
        "area",
        "volume",
        "angle",
        "temperature",
        "weight",
        "mass",
    ]
)


def is_math_query(text: str) -> bool:
    """Return True if *text* looks like a math word problem or computation."""
    lower = (text or "").lower()
    has_numbers = bool(re.search(r"\d", text))
    has_keyword = any(kw in lower for kw in _MATH_KEYWORDS)
    has_operator = any(c in text for c in "+-*/=^")
    return has_numbers and (has_keyword or has_operator)
