#!/usr/bin/env python3
"""Runtime bootstrap for Anemone's generated global vocabulary."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple


def _cngn_roots(repo: Path) -> List[Tuple[str, Path]]:
    candidates = []
    env = os.getenv("CNGN_ROOT", "").strip()
    if env:
        candidates.append(Path(env))
    candidates.extend((repo.parent / "CNGN", repo.parent / "cngn"))

    out: List[Tuple[str, Path]] = []
    seen = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        out.append(("cngn", resolved))
    return out


def ensure_word_freq(repo: Path = None, force: bool = False) -> Path:
    repo = (repo or Path(__file__).resolve().parent).resolve()
    vocab = repo / "word_freq.txt"
    counts = repo / "word_freq_counts.tsv"
    meta = repo / "word_freq.meta.json"

    if not force and vocab.is_file() and counts.is_file() and meta.is_file():
        return vocab

    from tools.build_word_freq import build, write_outputs

    roots = [("anemone", repo)] + _cngn_roots(repo)
    word_counts, source_counts, metadata = build(roots)
    if not word_counts:
        raise RuntimeError("Anemone vocabulary builder found no readable terms")
    write_outputs(repo, word_counts, source_counts, metadata)
    return vocab


if __name__ == "__main__":
    path = ensure_word_freq(force="--force" in os.sys.argv)
    print(path)
