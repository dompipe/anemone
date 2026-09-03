#!/usr/bin/env python3
"""Compatibility entrypoint for populate_mmap_store.py.

The existing NCBI helper intentionally exposes ensure_source() with keyword-only
arguments.  The mmap population module is kept focused on store logic; this
entrypoint adapts that call without changing the legacy builder API.
"""
from __future__ import annotations

import populate_mmap_store as target
from ncbi_source import SOURCE_DB, ensure_source as _ensure_source


def _compat_ensure_source(db_path=SOURCE_DB, *, rebuild=False, **kwargs):
    return _ensure_source(db_path=db_path, rebuild=rebuild, **kwargs)


target.ensure_source = _compat_ensure_source

if __name__ == "__main__":
    raise SystemExit(target.main())
