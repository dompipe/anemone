"""Context gathering: collect relevant files from the repo."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

# Patterns for auto-included config/meta files
_AUTO_INCLUDE_NAMES = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "README.md",
    "README.rst",
    "README.txt",
    "INSTALL.md",
    "STRUCTURE.md",
    ".gitignore",
}
_REQUIREMENTS_PREFIX = "requirements"
_MAX_FILE_BYTES = 32_000   # per-file limit
_MAX_TOTAL_BYTES = 128_000  # total context limit


def _is_safe_path(base: Path, target: Path) -> bool:
    """Return True if *target* is inside *base* (no path-traversal)."""
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def gather_context(
    repo_root: str,
    extra_paths: List[str] | None = None,
    max_file_bytes: int = _MAX_FILE_BYTES,
    max_total_bytes: int = _MAX_TOTAL_BYTES,
) -> List[Tuple[str, str]]:
    """Return a list of (relative_path, content) pairs.

    Auto-includes common config files that exist inside *repo_root*.
    *extra_paths* can request additional files (must stay within repo_root).
    """
    base = Path(repo_root).resolve()
    seen: set[Path] = set()
    collected: List[Tuple[str, str]] = []
    total = 0

    def _add(path: Path) -> None:
        nonlocal total
        if path in seen:
            return
        seen.add(path)
        if not path.is_file():
            return
        if not _is_safe_path(base, path):
            return
        size = path.stat().st_size
        if size > max_file_bytes:
            return
        if total + size > max_total_bytes:
            return
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        total += size
        rel = str(path.relative_to(base))
        collected.append((rel, content))

    # Auto-include known config files
    for name in sorted(_AUTO_INCLUDE_NAMES):
        _add(base / name)

    # requirements*.txt
    for p in sorted(base.glob("requirements*.txt")):
        _add(p)

    # Extra paths requested externally
    for ep in extra_paths or []:
        candidate = (base / ep).resolve()
        if _is_safe_path(base, candidate):
            _add(candidate)

    return collected


def build_context_block(files: List[Tuple[str, str]]) -> str:
    """Render a list of (path, content) pairs as a readable block for the LLM."""
    parts: List[str] = []
    for path, content in files:
        parts.append(f"### FILE: {path}\n```\n{content}\n```")
    return "\n\n".join(parts)
