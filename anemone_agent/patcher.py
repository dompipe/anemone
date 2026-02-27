"""Patch parsing and safe application.

Supports unified diff format (``diff --git ...`` or plain ``---``/``+++`` headers)
as well as a simple JSON file-edit format for completeness.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional


class PatchError(ValueError):
    """Raised when a patch cannot be parsed or applied safely."""


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def is_safe_path(base: Path, candidate: Path) -> bool:
    """Return True only if *candidate* resolves inside *base*."""
    try:
        candidate.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def safe_write(base: Path, rel_path: str, content: str) -> None:
    """Write *content* to *rel_path* relative to *base*, after safety check."""
    target = (base / rel_path).resolve()
    if not is_safe_path(base, target):
        raise PatchError(
            f"Path traversal blocked: '{rel_path}' resolves outside repo root."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def safe_delete(base: Path, rel_path: str) -> None:
    """Delete *rel_path* relative to *base* after safety check."""
    target = (base / rel_path).resolve()
    if not is_safe_path(base, target):
        raise PatchError(
            f"Path traversal blocked: '{rel_path}' resolves outside repo root."
        )
    if target.exists():
        target.unlink()


# ---------------------------------------------------------------------------
# JSON edit format
# ---------------------------------------------------------------------------

def apply_json_edits(base: Path, edits: List[Dict]) -> List[str]:
    """Apply a list of JSON edit dicts.

    Each dict may have keys:
      - ``action``: "create" | "update" | "delete"  (default "update")
      - ``path``: relative file path
      - ``content``: new file content (for create/update)
    Returns list of affected paths.
    """
    affected: List[str] = []
    for edit in edits:
        action = edit.get("action", "update").lower()
        path = edit.get("path", "")
        if not path:
            raise PatchError("Edit entry missing 'path' field.")
        if action in ("create", "update"):
            content = edit.get("content", "")
            safe_write(base, path, content)
        elif action == "delete":
            safe_delete(base, path)
        else:
            raise PatchError(f"Unknown edit action: '{action}'")
        affected.append(path)
    return affected


# ---------------------------------------------------------------------------
# Unified diff parsing + application
# ---------------------------------------------------------------------------

_DIFF_FILE_HEADER = re.compile(
    r"^(?:diff --git a/\S+ b/(\S+)|---\s+(?:a/)?(\S+)|\+\+\+\s+(?:b/)?(\S+))"
)
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _parse_unified_diff(patch_text: str) -> Dict[str, str]:
    """Parse a unified diff and return ``{filename: new_content}`` mapping.

    Only handles simple add/remove/context lines; binary diffs are skipped.
    Supports ``diff --git`` headers as well as plain ``---``/``+++`` headers.
    For *new* files (``--- /dev/null``) the old content is treated as empty.
    """
    result: Dict[str, str] = {}
    lines = patch_text.splitlines(keepends=True)

    i = 0
    current_file: Optional[str] = None
    old_lines: List[str] = []

    while i < len(lines):
        line = lines[i]

        # diff --git a/foo b/foo
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/\S+ b/(\S+)", line)
            if m:
                current_file = m.group(1)
                old_lines = []
            i += 1
            continue

        # --- a/foo  or  --- /dev/null
        if line.startswith("--- "):
            i += 1
            continue

        # +++ b/foo
        if line.startswith("+++ "):
            m = re.match(r"\+\+\+ (?:b/)?(\S+)", line)
            if m:
                target = m.group(1)
                if target != "/dev/null":
                    current_file = target
                    # Try to read existing file content for patching
                    old_lines = []  # will be rebuilt from context lines
            i += 1
            continue

        # @@ -L,S +L,S @@
        hm = _HUNK_HEADER.match(line)
        if hm and current_file is not None:
            # Apply this hunk using the running old_lines list
            old_start = int(hm.group(1))
            i += 1
            hunk_old: List[str] = []
            hunk_new: List[str] = []
            while i < len(lines) and not lines[i].startswith(("@@", "diff ", "--- ", "+++ ")):
                hl = lines[i]
                if hl.startswith(" "):
                    hunk_old.append(hl[1:])
                    hunk_new.append(hl[1:])
                elif hl.startswith("-"):
                    hunk_old.append(hl[1:])
                elif hl.startswith("+"):
                    hunk_new.append(hl[1:])
                elif hl.startswith("\\"):
                    pass  # "No newline at end of file"
                i += 1

            # Locate the hunk in old_lines and replace
            insert_pos = old_start - 1  # 1-based → 0-based
            if insert_pos < 0:
                insert_pos = 0
            # Find contiguous match of hunk_old starting near insert_pos
            matched = _find_hunk_position(old_lines, hunk_old, insert_pos)
            if matched is None:
                matched = insert_pos  # best-effort fallback

            old_lines = (
                old_lines[:matched]
                + hunk_new
                + old_lines[matched + len(hunk_old):]
            )
            result[current_file] = "".join(old_lines)
            continue

        i += 1

    return result


def _find_hunk_position(
    file_lines: List[str], hunk_old: List[str], hint: int
) -> Optional[int]:
    """Find the best position in *file_lines* to apply *hunk_old*."""
    if not hunk_old:
        return hint
    n = len(hunk_old)
    # Search near hint first, then broaden
    for delta in range(max(len(file_lines), 20) + 1):
        for pos in [hint + delta, hint - delta]:
            if 0 <= pos <= len(file_lines) - n:
                if file_lines[pos : pos + n] == hunk_old:
                    return pos
    return None


def apply_unified_diff(base: Path, patch_text: str) -> List[str]:
    """Parse *patch_text* as a unified diff and write files to *base*.

    Returns a list of modified relative paths.
    """
    file_map = _parse_unified_diff(patch_text)
    affected: List[str] = []
    for rel_path, content in file_map.items():
        safe_write(base, rel_path, content)
        affected.append(rel_path)
    return affected


# ---------------------------------------------------------------------------
# Auto-detect and apply patches from LLM output
# ---------------------------------------------------------------------------

def extract_and_apply(base: Path, llm_output: str, dry_run: bool = False) -> List[str]:
    """Extract patch(es) from LLM output and apply them.

    Looks for:
    1. A fenced ``json`` block containing a list of edit dicts.
    2. A unified diff (``diff --git`` or ``--- a/``/ ``+++ b/`` headers) anywhere
       in the output, optionally in a fenced code block.

    Returns a list of affected relative paths (empty if nothing found).
    """
    affected: List[str] = []

    # 1. Try JSON edits
    json_blocks = re.findall(r"```json\s*([\s\S]+?)```", llm_output, re.IGNORECASE)
    for block in json_blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            if dry_run:
                for edit in data:
                    affected.append(edit.get("path", "?"))
            else:
                affected.extend(apply_json_edits(base, data))
            return affected

    # 2. Try unified diff (in fenced block or raw)
    diff_blocks = re.findall(
        r"```(?:diff|patch)?\s*([\s\S]+?)```", llm_output, re.IGNORECASE
    )
    candidates = diff_blocks if diff_blocks else [llm_output]
    for candidate in candidates:
        if "diff --git" in candidate or ("--- " in candidate and "+++ " in candidate):
            if dry_run:
                parsed = _parse_unified_diff(candidate)
                affected.extend(parsed.keys())
            else:
                affected.extend(apply_unified_diff(base, candidate))
            return affected

    return affected
