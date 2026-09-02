#!/usr/bin/env python3
"""Build Anemone's global lexical index from all readable knowledge sources.

Outputs (repo root):
  word_freq.txt          one normalized term per line; backwards compatible
  word_freq_counts.tsv   term, corpus occurrence count, source-file count
  word_freq.meta.json    build provenance and corpus statistics

The builder intentionally scans knowledge *and* source code because Anemone also
reasons about code/algorithms. Binary/generated/runtime directories are skipped.
Additional repositories (for example CNGN) can be supplied with --extra-root.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Sequence, Tuple

VERSION = 1

TEXT_EXTENSIONS = {
    ".json", ".jsonl", ".txt", ".md", ".rst", ".csv", ".tsv",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".sql",
    ".py", ".php", ".js", ".mjs", ".cjs", ".jx", ".pasm",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".java", ".go", ".rs",
    ".html", ".htm", ".css", ".scss", ".xml", ".tex",
}

SKIP_DIR_NAMES = {
    ".git", ".github-cache", ".idea", ".vscode", "__pycache__",
    "node_modules", "vendor", "venv", ".venv", "env", ".env",
    "build", "dist", "target", ".buildozer", "Python-3.10.13",
    "cache", ".cache", "coverage", ".pytest_cache", ".mypy_cache",
    "_external", "tmp", "temp",
}

SKIP_FILE_NAMES = {
    "word_freq.txt", "word_freq_counts.tsv", "word_freq.meta.json",
}

# Whole textual identifiers first; split into useful lexical pieces below.
RAW_TOKEN_RE = re.compile(r"[^\W\s]+(?:[-'][^\W\s]+)*", re.UNICODE)
CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def normalize_piece(piece: str) -> str:
    piece = unicodedata.normalize("NFKC", piece).strip("_'-. ").lower()
    if not piece:
        return ""
    # Retain letters/digits only after identifier separators have been split.
    piece = "".join(ch for ch in piece if ch.isalnum() or ch in {"'"})
    if not piece or not any(ch.isalpha() for ch in piece):
        return ""
    if len(piece) > 96:
        return ""
    return piece


def lexical_terms(raw: str) -> Iterator[str]:
    """Yield both compound identifiers and their lexical components."""
    raw = unicodedata.normalize("NFKC", raw)
    for token in RAW_TOKEN_RE.findall(raw):
        # Preserve useful alphabetic compounds such as xray-like identifiers
        # but split snake_case, kebab-case and CamelCase into lookup words.
        compound = normalize_piece(token.replace("_", ""))
        if compound:
            yield compound

        camel_split = CAMEL_BOUNDARY_RE.sub(" ", token)
        for piece in re.split(r"[_\-']+|\s+", camel_split):
            norm = normalize_piece(piece)
            if norm:
                yield norm


def iter_text_files(root: Path, explicit_extra: bool = False) -> Iterator[Path]:
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(str(root)):
        # Extra roots are allowed to have their own .git directory, but it is
        # never useful lexical content.
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIR_NAMES and not d.startswith(".git")
        )
        base = Path(dirpath)
        for name in sorted(filenames):
            if name in SKIP_FILE_NAMES:
                continue
            path = base / name
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            try:
                if not path.is_file() or path.stat().st_size == 0:
                    continue
            except OSError:
                continue
            yield path


def read_chunks(path: Path, chunk_size: int = 1024 * 1024) -> Iterator[str]:
    """Read large UTF-8-ish corpora without loading them fully into memory."""
    carry = ""
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                text = carry + chunk
                # Avoid cutting a lexical token at a chunk boundary.
                cut = len(text)
                while cut > 0 and (text[cut - 1].isalnum() or text[cut - 1] in "_-'" ):
                    cut -= 1
                if cut == 0:
                    carry = text
                    continue
                yield text[:cut]
                carry = text[cut:]
            if carry:
                yield carry
    except (OSError, UnicodeError):
        return


def source_label(path: Path, roots: Sequence[Tuple[str, Path]]) -> str:
    resolved = path.resolve()
    for label, root in roots:
        try:
            rel = resolved.relative_to(root.resolve())
            return f"{label}:{rel.as_posix()}"
        except ValueError:
            continue
    return str(path)


def build(roots: Sequence[Tuple[str, Path]]) -> Tuple[Counter, Counter, Dict[str, object]]:
    counts: Counter = Counter()
    source_counts: Counter = Counter()
    source_files = 0
    bytes_scanned = 0
    tokens_scanned = 0
    per_root_files: Dict[str, int] = Counter()

    for label, root in roots:
        if not root.exists():
            continue
        for path in iter_text_files(root, explicit_extra=(label != "anemone")):
            source_files += 1
            per_root_files[label] += 1
            try:
                bytes_scanned += path.stat().st_size
            except OSError:
                pass

            # last_source avoids a potentially huge set-of-sources per word.
            seen_here = set()
            for chunk in read_chunks(path):
                for term in lexical_terms(chunk):
                    counts[term] += 1
                    tokens_scanned += 1
                    seen_here.add(term)
            for term in seen_here:
                source_counts[term] += 1

    meta = {
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "unique_terms": len(counts),
        "tokens_scanned": tokens_scanned,
        "source_files": source_files,
        "bytes_scanned": bytes_scanned,
        "roots": [
            {"label": label, "path": str(root.resolve()), "files": int(per_root_files.get(label, 0))}
            for label, root in roots
            if root.exists()
        ],
        "extensions": sorted(TEXT_EXTENSIONS),
        "policy": {
            "case": "lowercase NFKC",
            "requires_alpha": True,
            "max_term_length": 96,
            "includes_source_code": True,
            "compound_identifiers": True,
            "split_identifiers": True,
        },
    }
    return counts, source_counts, meta


def write_outputs(repo: Path, counts: Counter, source_counts: Counter, meta: Dict[str, object]) -> None:
    vocab_path = repo / "word_freq.txt"
    counts_path = repo / "word_freq_counts.tsv"
    meta_path = repo / "word_freq.meta.json"

    # Alphabetical order keeps diffs deterministic and binary-search friendly.
    words = sorted(counts)
    vocab_path.write_text("\n".join(words) + "\n", encoding="utf-8")

    with counts_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("word\tcount\tsource_files\n")
        for word in words:
            fh.write(f"{word}\t{counts[word]}\t{source_counts[word]}\n")

    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument(
        "--extra-root",
        action="append",
        default=[],
        help="Additional readable corpus/code root, e.g. ../CNGN. May repeat.",
    )
    parser.add_argument(
        "--extra-label",
        action="append",
        default=[],
        help="Label matching each --extra-root. Defaults to directory name.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repo = Path(args.repo).resolve()
    roots: List[Tuple[str, Path]] = [("anemone", repo)]
    labels = list(args.extra_label)
    for i, raw in enumerate(args.extra_root):
        path = Path(raw).resolve()
        label = labels[i] if i < len(labels) and labels[i] else path.name.lower()
        roots.append((label, path))

    counts, source_counts, meta = build(roots)
    if not counts:
        raise SystemExit("No vocabulary terms were found; refusing to overwrite word_freq.txt")
    write_outputs(repo, counts, source_counts, meta)
    print(
        "word_freq: "
        f"{len(counts):,} unique terms, "
        f"{meta['tokens_scanned']:,} token occurrences, "
        f"{meta['source_files']:,} source files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
