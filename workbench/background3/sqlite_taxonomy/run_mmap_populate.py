#!/usr/bin/env python3
"""Compatibility entrypoint for the v3 mmap taxonomy builder."""
from __future__ import annotations

import mmap_store
from mmap_ids import apply as apply_safe_ids

# Patch the store before populate_mmap_store imports encode/decode by value.
apply_safe_ids(mmap_store)

import populate_mmap_store as target
from ncbi_source import SOURCE_DB, ensure_source as _ensure_source


def _compat_ensure_source(db_path=SOURCE_DB, *, rebuild=False, **kwargs):
    return _ensure_source(db_path=db_path, rebuild=rebuild, **kwargs)


target.ensure_source = _compat_ensure_source

if __name__ == "__main__":
    raise SystemExit(target.main())
