"""Code-notes system for the anemone engine.

Provides a lightweight annotation layer over the codebase: JSON-backed documents
with curated inline code text, tags and freeform notes.  The module is stdlib-only
and safe to import even when `data/code_notes.json` is absent.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Default path for the notes file (workspace-relative).
_NOTES_PATH = Path('data') / 'code_notes.json'


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_raw(notes_path: Path | None = None) -> dict:
    """Return the parsed notes JSON or raise a descriptive RuntimeError."""
    p = notes_path or _NOTES_PATH
    if not p.exists():
        raise RuntimeError(f'Code-notes file not found: {p}')
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'Code-notes file is not valid JSON ({p}): {exc}') from exc
    if not isinstance(data, dict):
        raise RuntimeError(f'Code-notes file must be a JSON object, got {type(data).__name__}')
    return data


def _read_text_for_doc(doc: dict, base_dir: Path | None = None) -> str:
    """Read the source text slice defined by doc[path] + doc[range]."""
    path_str = doc.get('path', '')
    rng = doc.get('range') or {}
    start = int(rng.get('start', 1))
    end = int(rng.get('end', start))

    if base_dir:
        src = base_dir / path_str
    else:
        src = Path(path_str)

    if not src.exists():
        raise FileNotFoundError(f'Source file not found: {src}')

    lines = src.read_text(encoding='utf-8').splitlines(keepends=True)
    total = len(lines)
    s = max(1, start) - 1
    e = min(total, end)
    if s >= total:
        raise ValueError(f'Range start {start} exceeds file length {total} in {src}')
    return ''.join(lines[s:e])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_notes(notes_path: Path | None = None) -> dict:
    """Load and return the full notes data dict.

    Raises RuntimeError with an actionable message on failure.
    """
    return _load_raw(notes_path)


def list_documents(notes_path: Path | None = None) -> list[dict]:
    """Return a compact list of documents: id, title, path:range, tags."""
    data = _load_raw(notes_path)
    result = []
    for doc in data.get('documents', []):
        rng = doc.get('range') or {}
        result.append({
            'id': doc.get('id', ''),
            'title': doc.get('title', ''),
            'location': f"{doc.get('path', '')}:{rng.get('start', '?')}-{rng.get('end', '?')}",
            'tags': doc.get('tags', []),
        })
    return result


def get_document(doc_id: str, notes_path: Path | None = None) -> dict:
    """Return the full document dict for *doc_id*.

    Raises KeyError if not found.
    """
    data = _load_raw(notes_path)
    for doc in data.get('documents', []):
        if doc.get('id') == doc_id:
            return doc
    raise KeyError(f'No code-note found with id: {doc_id!r}')


def search_documents(term: str, notes_path: Path | None = None) -> list[dict]:
    """Return compact doc entries where *term* matches id/title/tags/notes/text/path."""
    data = _load_raw(notes_path)
    t = term.lower()
    results = []
    for doc in data.get('documents', []):
        haystack = ' '.join([
            doc.get('id', ''),
            doc.get('title', ''),
            doc.get('path', ''),
            doc.get('text', ''),
            ' '.join(doc.get('tags', [])),
            ' '.join(doc.get('notes', [])),
        ]).lower()
        if t in haystack:
            rng = doc.get('range') or {}
            results.append({
                'id': doc.get('id', ''),
                'title': doc.get('title', ''),
                'location': f"{doc.get('path', '')}:{rng.get('start', '?')}-{rng.get('end', '?')}",
                'tags': doc.get('tags', []),
            })
    return results


def refresh_notes(notes_path: Path | None = None, base_dir: Path | None = None) -> dict:
    """Regenerate `text` fields from the current working tree and update `generated_at`.

    Returns the updated data dict (also writes it back to disk).
    Errors for individual documents are collected and stored in `_refresh_errors`.
    """
    p = notes_path or _NOTES_PATH
    data = _load_raw(p)
    errors: list[str] = []
    for doc in data.get('documents', []):
        try:
            doc['text'] = _read_text_for_doc(doc, base_dir)
        except Exception as exc:
            errors.append(f"{doc.get('id', '?')}: {exc}")
    data['generated_at'] = datetime.now(timezone.utc).isoformat()
    data['_refresh_errors'] = errors
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    return data


# ---------------------------------------------------------------------------
# Human-readable formatting helpers (for chat output)
# ---------------------------------------------------------------------------

def _fmt_list(docs: list[dict]) -> str:
    if not docs:
        return 'No code notes found.'
    lines = [f'Code notes ({len(docs)}):']
    for d in docs:
        tags = ', '.join(d.get('tags', [])) or '—'
        lines.append(f"  [{d['id']}]  {d['title']}")
        lines.append(f"    {d['location']}  tags: {tags}")
    return '\n'.join(lines)


def _fmt_document(doc: dict) -> str:
    rng = doc.get('range') or {}
    lines = [
        f"ID:    {doc.get('id', '')}",
        f"Title: {doc.get('title', '')}",
        f"File:  {doc.get('path', '')}  lines {rng.get('start', '?')}-{rng.get('end', '?')}",
        f"Tags:  {', '.join(doc.get('tags', [])) or '—'}",
    ]
    notes = doc.get('notes', [])
    if notes:
        lines.append('Notes:')
        for n in notes:
            lines.append(f'  • {n}')
    text = doc.get('text', '').strip()
    if text:
        lines.append('Code:')
        lines.append('```')
        lines.append(text)
        lines.append('```')
    return '\n'.join(lines)


def _fmt_search(results: list[dict], term: str) -> str:
    if not results:
        return f'No code notes matching "{term}".'
    lines = [f'Search results for "{term}" ({len(results)} match(es)):']
    for d in results:
        tags = ', '.join(d.get('tags', [])) or '—'
        lines.append(f"  [{d['id']}]  {d['title']}  ({d['location']})  tags: {tags}")
    return '\n'.join(lines)


HELP_TEXT = """\
Code-notes commands:
  list notes / notes list       – list all annotated code chunks
  notes <id>                    – show notes + code for a document
  notes info <id>               – show metadata only (no code)
  search notes <term>           – search notes by keyword
  notes tags                    – list tags and document counts
  refresh notes                 – rebuild inline code text from current files
  help notes                    – show this help
""".strip()


def handle_notes_command(user_input: str, notes_path: Path | None = None, base_dir: Path | None = None) -> str | None:
    """Parse *user_input* for a notes command and return a human-readable response.

    Returns None if the input is not a notes command.
    """
    cmd = user_input.strip()
    low = cmd.lower()

    # --- help ---
    if low in ('help notes', 'notes help'):
        return HELP_TEXT

    # --- list ---
    if low in ('list notes', 'notes list'):
        try:
            docs = list_documents(notes_path)
            return _fmt_list(docs)
        except RuntimeError as exc:
            return str(exc)

    # --- tags ---
    if low in ('notes tags', 'list notes tags'):
        try:
            data = load_notes(notes_path)
            counts: dict[str, int] = {}
            for doc in data.get('documents', []):
                for tag in doc.get('tags', []):
                    counts[tag] = counts.get(tag, 0) + 1
            if not counts:
                return 'No tags found.'
            lines = ['Tags:']
            for tag, cnt in sorted(counts.items()):
                lines.append(f'  {tag}: {cnt}')
            return '\n'.join(lines)
        except RuntimeError as exc:
            return str(exc)

    # --- refresh ---
    if low in ('refresh notes', 'notes refresh'):
        try:
            data = refresh_notes(notes_path, base_dir)
            errs = data.get('_refresh_errors', [])
            n = len(data.get('documents', []))
            msg = f'Refreshed {n} document(s). generated_at updated.'
            if errs:
                msg += '\nWarnings:\n' + '\n'.join(f'  {e}' for e in errs)
            return msg
        except RuntimeError as exc:
            return str(exc)

    # --- search ---
    import re
    m_search = re.match(r'^search\s+notes\s+(.+)$', low)
    if m_search:
        term = m_search.group(1).strip()
        try:
            results = search_documents(term, notes_path)
            return _fmt_search(results, term)
        except RuntimeError as exc:
            return str(exc)

    # --- notes info <id> ---
    m_info = re.match(r'^notes\s+info\s+(\S+)$', low)
    if m_info:
        doc_id = m_info.group(1)
        try:
            doc = get_document(doc_id, notes_path)
            rng = doc.get('range') or {}
            lines = [
                f"ID:    {doc.get('id', '')}",
                f"Title: {doc.get('title', '')}",
                f"File:  {doc.get('path', '')}  lines {rng.get('start', '?')}-{rng.get('end', '?')}",
                f"Tags:  {', '.join(doc.get('tags', [])) or '—'}",
            ]
            notes = doc.get('notes', [])
            if notes:
                lines.append('Notes:')
                for n in notes:
                    lines.append(f'  • {n}')
            return '\n'.join(lines)
        except (RuntimeError, KeyError) as exc:
            return str(exc)

    # --- notes <id> ---
    m_id = re.match(r'^notes\s+(\S+)$', low)
    if m_id:
        doc_id = m_id.group(1)
        # avoid treating non-id words as ids (e.g. "notes list" already handled)
        try:
            doc = get_document(doc_id, notes_path)
            return _fmt_document(doc)
        except (RuntimeError, KeyError) as exc:
            return str(exc)

    return None
