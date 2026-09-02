#!/usr/bin/env python3
"""Build Anemone's global lexical index from all readable knowledge sources.

Outputs (repo root):
  word_freq.txt          one normalized term per line; backwards compatible
  word_freq_counts.tsv   term, corpus occurrence count, source-file count
  word_freq.meta.json    build provenance and corpus statistics

The builder scans knowledge and source code because Anemone reasons about both.
It also reads lexical columns from generated SQLite stores (taxonomy names,
aliases, descriptors, NCBI names, encyclopedia terms) without treating database
bytes as ordinary text. Additional repositories such as CNGN can be supplied
with --extra-root.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

VERSION = 2

TEXT_EXTENSIONS = {
    ".json", ".jsonl", ".txt", ".md", ".rst", ".csv", ".tsv",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".sql",
    ".py", ".php", ".js", ".mjs", ".cjs", ".jx", ".pasm",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".java", ".go", ".rs",
    ".html", ".htm", ".css", ".scss", ".xml", ".tex",
}
SQLITE_EXTENSIONS = {".sqlite3", ".sqlite", ".db"}

SKIP_DIR_NAMES = {
    ".git", ".github-cache", ".idea", ".vscode", "__pycache__",
    "node_modules", "vendor", "venv", ".venv", "env", ".env",
    "build", "dist", "target", ".buildozer", "Python-3.10.13",
    "cache", ".cache", "coverage", ".pytest_cache", ".mypy_cache",
    "_external", "tmp", "temp",
}
# SQLite caches contain vocabulary not always preserved in checked-in text, so
# cache directories are allowed for the database-specific pass.
SQLITE_SKIP_DIR_NAMES = SKIP_DIR_NAMES - {"cache", ".cache"}

SKIP_FILE_NAMES = {
    "word_freq.txt", "word_freq_counts.tsv", "word_freq.meta.json",
}

RAW_TOKEN_RE = re.compile(r"[^\W\s]+(?:[-'][^\W\s]+)*", re.UNICODE)
CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def normalize_piece(piece: str) -> str:
    piece = unicodedata.normalize("NFKC", piece).strip("_'-. ").lower()
    if not piece:
        return ""
    piece = "".join(ch for ch in piece if ch.isalnum() or ch == "'")
    if not piece or not any(ch.isalpha() for ch in piece):
        return ""
    if len(piece) > 96:
        return ""
    return piece


def lexical_terms(raw: str) -> Iterator[str]:
    """Yield compound identifiers and their useful lexical components."""
    raw = unicodedata.normalize("NFKC", raw)
    for token in RAW_TOKEN_RE.findall(raw):
        compound = normalize_piece(token.replace("_", ""))
        if compound:
            yield compound

        camel_split = CAMEL_BOUNDARY_RE.sub(" ", token)
        for piece in re.split(r"[_\-']+|\s+", camel_split):
            norm = normalize_piece(piece)
            if norm:
                yield norm


def _walk_files(root: Path, skip_dirs: set) -> Iterator[Path]:
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in skip_dirs and not d.startswith(".git")
        )
        base = Path(dirpath)
        for name in sorted(filenames):
            yield base / name


def iter_text_files(root: Path) -> Iterator[Path]:
    for path in _walk_files(root, SKIP_DIR_NAMES):
        if path.name in SKIP_FILE_NAMES or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        try:
            if path.is_file() and path.stat().st_size:
                yield path
        except OSError:
            continue


def iter_sqlite_files(root: Path) -> Iterator[Path]:
    for path in _walk_files(root, SQLITE_SKIP_DIR_NAMES):
        if path.suffix.lower() not in SQLITE_EXTENSIONS:
            continue
        try:
            if path.is_file() and path.stat().st_size:
                yield path
        except OSError:
            continue


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


def sqlite_queries(table_names: set) -> List[Tuple[str, str]]:
    """Return label/query pairs for lexical, non-binary SQLite knowledge."""
    queries: List[Tuple[str, str]] = []
    if "TAXON" in table_names:
        queries.append((
            "taxon",
            "SELECT canonical_name, common_name, scientific_name, source_rank FROM TAXON",
        ))
    if "TAXON_ALIAS" in table_names:
        queries.append(("taxon_alias", "SELECT alias, alias_kind FROM TAXON_ALIAS"))
    if "DESCRIPTOR" in table_names:
        queries.append(("descriptor", "SELECT descriptor_text, semantic_key FROM DESCRIPTOR"))
    if "SOURCE_NAME" in table_names:
        queries.append(("source_name", "SELECT name, name_class FROM SOURCE_NAME"))
    if "ENTRY" in table_names:
        # ENTRY.text generally duplicates checked-in encyclopedia corpora; use
        # the indexed term and source path so frequency is not multiplied by a
        # derived cache copy of the whole article text.
        queries.append(("entry_term", "SELECT term, source_file FROM ENTRY"))
    return queries


def iter_sqlite_values(path: Path) -> Iterator[Tuple[str, str]]:
    """Yield (logical-source, text) from known Anemone SQLite schemas."""
    uri = "file:{}?mode=ro".format(path.resolve().as_posix())
    db = None
    try:
        db = sqlite3.connect(uri, uri=True, timeout=1.0)
        tables = {
            str(row[0])
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for query_label, query in sqlite_queries(tables):
            try:
                cur = db.execute(query)
                while True:
                    rows = cur.fetchmany(10000)
                    if not rows:
                        break
                    for row in rows:
                        for value in row:
                            if value is not None:
                                yield query_label, str(value)
            except sqlite3.Error:
                continue
    except sqlite3.Error:
        return
    finally:
        if db is not None:
            try:
                db.close()
            except sqlite3.Error:
                pass


def build(roots: Sequence[Tuple[str, Path]]) -> Tuple[Counter, Counter, Dict[str, object]]:
    counts: Counter = Counter()
    source_counts: Counter = Counter()
    source_files = 0
    text_files = 0
    sqlite_files = 0
    sqlite_rows_or_values = 0
    bytes_scanned = 0
    sqlite_bytes_present = 0
    tokens_scanned = 0
    per_root_files: Dict[str, int] = Counter()

    for label, root in roots:
        if not root.exists():
            continue

        for path in iter_text_files(root):
            source_files += 1
            text_files += 1
            per_root_files[label] += 1
            try:
                bytes_scanned += path.stat().st_size
            except OSError:
                pass

            seen_here = set()
            for chunk in read_chunks(path):
                for term in lexical_terms(chunk):
                    counts[term] += 1
                    tokens_scanned += 1
                    seen_here.add(term)
            for term in seen_here:
                source_counts[term] += 1

        # SQLite is a separate pass because cache dirs are intentionally absent
        # from the plain-text pass.
        for path in iter_sqlite_files(root):
            source_files += 1
            sqlite_files += 1
            per_root_files[label] += 1
            try:
                sqlite_bytes_present += path.stat().st_size
            except OSError:
                pass

            # Count each logical table/query as part of this database source,
            # but source_files for a term increments only once per database.
            seen_here = set()
            for _query_label, value in iter_sqlite_values(path):
                sqlite_rows_or_values += 1
                for term in lexical_terms(value):
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
        "text_files": text_files,
        "sqlite_files": sqlite_files,
        "sqlite_values_scanned": sqlite_rows_or_values,
        "text_bytes_scanned": bytes_scanned,
        "sqlite_bytes_present": sqlite_bytes_present,
        "roots": [
            {"label": label, "path": str(root.resolve()), "files": int(per_root_files.get(label, 0))}
            for label, root in roots
            if root.exists()
        ],
        "extensions": sorted(TEXT_EXTENSIONS),
        "sqlite_extensions": sorted(SQLITE_EXTENSIONS),
        "policy": {
            "case": "lowercase NFKC",
            "requires_alpha": True,
            "max_term_length": 96,
            "includes_source_code": True,
            "includes_generated_taxonomy_sqlite": True,
            "includes_sqlite_aliases_descriptors_names": True,
            "derived_encyclopedia_cache_terms_only": True,
            "compound_identifiers": True,
            "split_identifiers": True,
        },
    }
    return counts, source_counts, meta


def write_outputs(repo: Path, counts: Counter, source_counts: Counter, meta: Dict[str, object]) -> None:
    vocab_path = repo / "word_freq.txt"
    counts_path = repo / "word_freq_counts.tsv"
    meta_path = repo / "word_freq.meta.json"

    words = sorted(counts)
    vocab_path.write_text("\n".join(words) + "\n", encoding="utf-8")

    with counts_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("word\tcount\tsource_files\n")
        for word in words:
            fh.write("{}\t{}\t{}\n".format(word, counts[word], source_counts[word]))

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


def main(argv: Optional[Sequence[str]] = None) -> int:
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
        "word_freq: {:,} unique terms, {:,} token occurrences, {:,} sources".format(
            len(counts), int(meta["tokens_scanned"]), int(meta["source_files"])
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
