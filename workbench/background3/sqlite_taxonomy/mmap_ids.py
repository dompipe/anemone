#!/usr/bin/env python3
"""JavaScript-safe rank-address ids for the mmap taxonomy store.

49 local bits provide 562,949,953,421,311 rows per rank.  With rank codes 1..9
in the high portion, every taxon id remains below 2^53-1 and is therefore exact
in SQLite INTEGER, PHP int, Python int, and browser JavaScript Number.
"""
from __future__ import annotations

RANKS = (
    "kingdom", "phylum", "class", "order", "family",
    "genus", "species", "type", "name",
)
RANK_CODE = {rank: i + 1 for i, rank in enumerate(RANKS)}
CODE_RANK = {code: rank for rank, code in RANK_CODE.items()}
LOCAL_BITS = 49
RANK_UNIT = 1 << LOCAL_BITS
LOCAL_MASK = RANK_UNIT - 1
MAX_SAFE_TAXON_ID = 9 * RANK_UNIT + LOCAL_MASK


def encode_taxon_id(rank: str, local_id: int) -> int:
    code = RANK_CODE.get(rank)
    if code is None:
        raise ValueError("unknown rank: %s" % rank)
    if local_id < 1 or local_id > LOCAL_MASK:
        raise ValueError("local id out of range")
    value = code * RANK_UNIT + int(local_id)
    if value > (1 << 53) - 1:
        raise OverflowError("taxon id exceeds JavaScript safe integer range")
    return value


def decode_taxon_id(taxon_id: int) -> tuple[str, int]:
    value = int(taxon_id)
    code = value // RANK_UNIT
    rank = CODE_RANK.get(code)
    if rank is None:
        raise ValueError("taxon id has unknown rank code: %s" % value)
    return rank, value - code * RANK_UNIT


def apply(module=None) -> None:
    """Patch mmap_store's global id functions before ids are allocated/read."""
    if module is None:
        import mmap_store as module
    module.LOCAL_MASK = LOCAL_MASK
    module.encode_taxon_id = encode_taxon_id
    module.decode_taxon_id = decode_taxon_id
