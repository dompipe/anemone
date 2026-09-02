#!/usr/bin/env python3
"""Build and manipulate the Anemone SQLite taxonomy database.

The physical hierarchy is split across adjacent-rank tables:
KINGDOM_PHYLUM -> PHYLUM_FAMILY -> FAMILY_ORDER -> ORDER_GENUS ->
GENUS_SPECIES -> SPECIES_TYPE -> TYPE_NAME.

Each parent page contains at most 25 children. Descriptors are normalized and
may be attached at every taxonomic level, then inherited downward. A lower
node's explicit descriptor state overrides an inherited state.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path
from typing import Iterable, Iterator, Optional

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE / "anemone_taxonomy.sqlite3"
SCHEMA = HERE / "schema.sql"
DEFAULT_BUDGET_GIB = 35.0
DEFAULT_PAGE_SIZE = 4096
CHILDREN_PER_PAGE = 25

RANKS = ("kingdom", "phylum", "family", "order", "genus", "species", "type", "name")

EDGE = {
    ("kingdom", "phylum"): ("KINGDOM_PHYLUM", "kingdom_id", "phylum_id"),
    ("phylum", "family"): ("PHYLUM_FAMILY", "phylum_id", "family_id"),
    ("family", "order"): ("FAMILY_ORDER", "family_id", "order_id"),
    ("order", "genus"): ("ORDER_GENUS", "order_id", "genus_id"),
    ("genus", "species"): ("GENUS_SPECIES", "genus_id", "species_id"),
    ("species", "type"): ("SPECIES_TYPE", "species_id", "type_id"),
    ("type", "name"): ("TYPE_NAME", "type_id", "name_id"),
}

WORD_RE = re.compile(r"[^\s]+")


def byte_budget(gib: float) -> int:
    if gib <= 0:
        raise ValueError("budget must be greater than zero")
    return int(gib * 1024 ** 3)


def max_pages_for(gib: float, page_size: int = DEFAULT_PAGE_SIZE) -> int:
    return byte_budget(gib) // page_size


def connect(db_path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db(db_path: Path, budget_gib: float = DEFAULT_BUDGET_GIB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    new_db = not db_path.exists() or db_path.stat().st_size == 0
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    if new_db:
        db.execute(f"PRAGMA page_size={DEFAULT_PAGE_SIZE}")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    page_size = int(db.execute("PRAGMA page_size").fetchone()[0])
    db.execute(f"PRAGMA max_page_count={max_pages_for(budget_gib, page_size)}")
    db.commit()
    return db


def normalize_descriptor(text: str) -> str:
    value = " ".join(text.strip().lower().split())
    words = WORD_RE.findall(value)
    if not 2 <= len(words) <= 3:
        raise ValueError(f"descriptor must contain 2-3 words: {text!r}")
    return value


def get_taxon(db: sqlite3.Connection, taxon_id: int) -> sqlite3.Row:
    row = db.execute("SELECT * FROM TAXON WHERE taxon_id=?", (taxon_id,)).fetchone()
    if row is None:
        raise KeyError(f"unknown taxon_id {taxon_id}")
    return row


def upsert_taxon(
    db: sqlite3.Connection,
    rank: str,
    canonical_name: str,
    *,
    common_name: Optional[str] = None,
    scientific_name: Optional[str] = None,
    source: Optional[str] = None,
    source_ref: Optional[str] = None,
) -> int:
    rank = rank.lower()
    if rank not in RANKS:
        raise ValueError(f"invalid rank: {rank}")
    canonical_name = " ".join(canonical_name.strip().split())
    db.execute(
        """
        INSERT INTO TAXON(rank, canonical_name, common_name, scientific_name, source, source_ref)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(rank, canonical_name) DO UPDATE SET
            common_name=COALESCE(excluded.common_name, TAXON.common_name),
            scientific_name=COALESCE(excluded.scientific_name, TAXON.scientific_name),
            source=COALESCE(excluded.source, TAXON.source),
            source_ref=COALESCE(excluded.source_ref, TAXON.source_ref)
        """,
        (rank, canonical_name, common_name, scientific_name, source, source_ref),
    )
    row = db.execute(
        "SELECT taxon_id FROM TAXON WHERE rank=? AND canonical_name=?",
        (rank, canonical_name),
    ).fetchone()
    return int(row[0])


def next_slot(db: sqlite3.Connection, table: str, parent_col: str, parent_id: int) -> tuple[int, int]:
    row = db.execute(
        f"SELECT page_no, slot_no FROM {table} WHERE {parent_col}=? ORDER BY page_no DESC, slot_no DESC LIMIT 1",
        (parent_id,),
    ).fetchone()
    if row is None:
        return 0, 1
    page_no, slot_no = int(row[0]), int(row[1])
    if slot_no < CHILDREN_PER_PAGE:
        return page_no, slot_no + 1
    return page_no + 1, 1


def link_taxa(db: sqlite3.Connection, parent_id: int, child_id: int) -> tuple[int, int]:
    parent = get_taxon(db, parent_id)
    child = get_taxon(db, child_id)
    key = (parent["rank"], child["rank"])
    if key not in EDGE:
        raise ValueError(f"ranks are not adjacent: {key[0]} -> {key[1]}")
    table, parent_col, child_col = EDGE[key]
    existing = db.execute(
        f"SELECT page_no, slot_no FROM {table} WHERE {parent_col}=? AND {child_col}=?",
        (parent_id, child_id),
    ).fetchone()
    if existing:
        return int(existing[0]), int(existing[1])
    page_no, slot_no = next_slot(db, table, parent_col, parent_id)
    db.execute(
        f"INSERT INTO {table}({parent_col}, {child_col}, page_no, slot_no) VALUES(?,?,?,?)",
        (parent_id, child_id, page_no, slot_no),
    )
    return page_no, slot_no


def add_child(
    db: sqlite3.Connection,
    parent_id: int,
    child_rank: str,
    child_name: str,
    **taxon_fields,
) -> int:
    child_id = upsert_taxon(db, child_rank, child_name, **taxon_fields)
    link_taxa(db, parent_id, child_id)
    return child_id


def descriptor_id(db: sqlite3.Connection, text: str) -> int:
    text = normalize_descriptor(text)
    count = len(WORD_RE.findall(text))
    db.execute(
        "INSERT INTO DESCRIPTOR(descriptor_text, word_count) VALUES(?,?) ON CONFLICT(descriptor_text) DO NOTHING",
        (text, count),
    )
    return int(db.execute("SELECT descriptor_id FROM DESCRIPTOR WHERE descriptor_text=?", (text,)).fetchone()[0])


def set_descriptor(
    db: sqlite3.Connection,
    taxon_id: int,
    text: str,
    *,
    kind: str = "trait",
    state: str = "present",
    inheritable: bool = True,
    confidence: float = 1.0,
    source: Optional[str] = None,
    source_ref: Optional[str] = None,
) -> int:
    if kind not in {"trait", "phenotype"}:
        raise ValueError("kind must be trait or phenotype")
    if state not in {"present", "absent", "variable"}:
        raise ValueError("state must be present, absent, or variable")
    did = descriptor_id(db, text)
    db.execute(
        """
        INSERT INTO TAXON_DESCRIPTOR(
            taxon_id, descriptor_id, kind, state, inheritable, confidence, source, source_ref
        ) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(taxon_id, descriptor_id, kind) DO UPDATE SET
            state=excluded.state,
            inheritable=excluded.inheritable,
            confidence=excluded.confidence,
            source=COALESCE(excluded.source, TAXON_DESCRIPTOR.source),
            source_ref=COALESCE(excluded.source_ref, TAXON_DESCRIPTOR.source_ref)
        """,
        (taxon_id, did, kind, state, int(inheritable), confidence, source, source_ref),
    )
    return did


def ancestor_rows(db: sqlite3.Connection, taxon_id: int) -> list[sqlite3.Row]:
    """Return self followed by ancestors, nearest first."""
    return db.execute(
        """
        WITH RECURSIVE ancestry(taxon_id, depth) AS (
            SELECT ?, 0
            UNION ALL
            SELECT e.parent_id, ancestry.depth + 1
            FROM ancestry
            JOIN TAXON_EDGE e ON e.child_id = ancestry.taxon_id
        )
        SELECT t.*, ancestry.depth
        FROM ancestry JOIN TAXON t USING(taxon_id)
        ORDER BY ancestry.depth ASC
        """,
        (taxon_id,),
    ).fetchall()


def effective_descriptors(db: sqlite3.Connection, taxon_id: int) -> list[dict]:
    """Resolve inherited descriptors; nearest explicit state wins."""
    ancestors = ancestor_rows(db, taxon_id)
    resolved: dict[tuple[int, str], dict] = {}
    for node in ancestors:  # nearest first means first occurrence wins
        rows = db.execute(
            """
            SELECT td.*, d.descriptor_text
            FROM TAXON_DESCRIPTOR td
            JOIN DESCRIPTOR d USING(descriptor_id)
            WHERE td.taxon_id=?
            """,
            (node["taxon_id"],),
        ).fetchall()
        for row in rows:
            if node["depth"] > 0 and not row["inheritable"]:
                continue
            key = (row["descriptor_id"], row["kind"])
            if key in resolved:
                continue
            resolved[key] = {
                "descriptor": row["descriptor_text"],
                "kind": row["kind"],
                "state": row["state"],
                "from_taxon_id": node["taxon_id"],
                "from_rank": node["rank"],
                "from_name": node["canonical_name"],
                "depth": node["depth"],
                "confidence": row["confidence"],
            }
    return sorted(resolved.values(), key=lambda x: (x["kind"], x["descriptor"]))


def compare_requested(db: sqlite3.Connection, taxon_id: int, requested: Iterable[str]) -> dict:
    effective = {d["descriptor"]: d for d in effective_descriptors(db, taxon_id)}
    result = {"present": [], "absent": [], "variable": [], "unknown": []}
    for raw in requested:
        text = normalize_descriptor(raw)
        item = effective.get(text)
        if item is None:
            result["unknown"].append(text)
        else:
            result[item["state"]].append(text)
    return result


def database_status(db: sqlite3.Connection, db_path: Path) -> dict:
    page_size = int(db.execute("PRAGMA page_size").fetchone()[0])
    page_count = int(db.execute("PRAGMA page_count").fetchone()[0])
    max_page_count = int(db.execute("PRAGMA max_page_count").fetchone()[0])
    main_bytes = page_size * page_count
    max_bytes = page_size * max_page_count
    wal = Path(str(db_path) + "-wal")
    return {
        "page_size": page_size,
        "page_count": page_count,
        "max_page_count": max_page_count,
        "main_bytes": main_bytes,
        "max_bytes": max_bytes,
        "main_gib": main_bytes / 1024 ** 3,
        "max_gib": max_bytes / 1024 ** 3,
        "wal_bytes": wal.stat().st_size if wal.exists() else 0,
    }


def cli() -> int:
    parser = argparse.ArgumentParser(description="Anemone SQLite taxonomy database")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--budget-gib", type=float, default=DEFAULT_BUDGET_GIB)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("status")
    args = parser.parse_args()

    db = init_db(args.db, args.budget_gib)
    if args.command == "init":
        print(f"initialized {args.db}")
    elif args.command == "status":
        status = database_status(db, args.db)
        print(f"database: {args.db}")
        print(f"size: {status['main_gib']:.6f} GiB")
        print(f"hard limit: {status['max_gib']:.3f} GiB")
        print(f"page size: {status['page_size']} bytes")
        print(f"pages: {status['page_count']:,} / {status['max_page_count']:,}")
        print(f"wal: {status['wal_bytes'] / 1024 ** 2:.3f} MiB")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
