#!/usr/bin/env python3
"""Sharded mmap-oriented physical store for Anemone taxonomy v3.

The logical taxonomy is unchanged.  The physical representation is split into
rank databases and transition databases:

  rank_00_kingdom.sqlite3 ... rank_08_name.sqlite3
  edge_00_kingdom_phylum.sqlite3 ... edge_07_type_name.sqlite3
  catalog.sqlite3

A child constraint is materialized in the transition database immediately below
its rank table.  That means a query can filter children by effective traits,
phenotypes, origin/source constraints, confidence, and novelty before reading a
full child row.

Global taxon ids encode their owning rank in the high byte.  No catalog lookup
is needed to decide which mmap shard owns an id.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

HERE = Path(__file__).resolve().parent
DEFAULT_STORE = HERE / "anemone_taxonomy.mmap"
DEFAULT_BUDGET_GIB = 35.0
DEFAULT_MMAP_GIB = 4.0
PAGE_SIZE = 32768
CHILDREN_PER_PAGE = 25

RANKS = (
    "kingdom", "phylum", "class", "order", "family",
    "genus", "species", "type", "name",
)
RANK_CODE = {rank: i + 1 for i, rank in enumerate(RANKS)}
CODE_RANK = {code: rank for rank, code in RANK_CODE.items()}
NEXT_RANK = {RANKS[i]: RANKS[i + 1] for i in range(len(RANKS) - 1)}
WORD_RE = re.compile(r"[a-z0-9][a-z0-9'_-]*", re.I)

# Low 56 bits are a shard-local monotonically increasing row id.
LOCAL_MASK = (1 << 56) - 1


def encode_taxon_id(rank: str, local_id: int) -> int:
    if rank not in RANK_CODE:
        raise ValueError("unknown rank: %s" % rank)
    if local_id < 1 or local_id > LOCAL_MASK:
        raise ValueError("local id out of range")
    return (RANK_CODE[rank] << 56) | local_id


def decode_taxon_id(taxon_id: int) -> tuple[str, int]:
    code = (int(taxon_id) >> 56) & 0xFF
    rank = CODE_RANK.get(code)
    if rank is None:
        raise ValueError("taxon id has unknown rank code: %s" % taxon_id)
    return rank, int(taxon_id) & LOCAL_MASK


def rank_db_name(rank: str) -> str:
    return "rank_%02d_%s.sqlite3" % (RANKS.index(rank), rank)


def edge_db_name(parent_rank: str, child_rank: str) -> str:
    return "edge_%02d_%s_%s.sqlite3" % (RANKS.index(parent_rank), parent_rank, child_rank)


def byte_budget(gib: float) -> int:
    return int(float(gib) * 1024 ** 3)


def mmap_bytes(gib: float) -> int:
    return int(float(gib) * 1024 ** 3)


def _connect(path: Path, *, build: bool, mmap_gib: float) -> sqlite3.Connection:
    db = sqlite3.connect(str(path), timeout=60.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=OFF")  # cross-file references are checked in code
    db.execute("PRAGMA temp_store=MEMORY")
    db.execute("PRAGMA cache_size=-131072")  # ~128 MiB/shard when hot
    db.execute("PRAGMA mmap_size=%d" % mmap_bytes(mmap_gib))
    if build:
        db.execute("PRAGMA journal_mode=OFF")
        db.execute("PRAGMA synchronous=OFF")
        db.execute("PRAGMA locking_mode=EXCLUSIVE")
    else:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
    return db


CATALOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS META(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ID_ALLOC(
    rank TEXT PRIMARY KEY,
    next_local_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS TAXON_INDEX(
    taxon_id INTEGER PRIMARY KEY,
    rank TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    common_name TEXT,
    scientific_name TEXT,
    parent_id INTEGER,
    origin_kind TEXT NOT NULL,
    source TEXT,
    source_ref TEXT,
    source_rank TEXT,
    UNIQUE(rank, canonical_name)
);
CREATE INDEX IF NOT EXISTS idx_catalog_rank_name
ON TAXON_INDEX(rank, canonical_name);
CREATE INDEX IF NOT EXISTS idx_catalog_parent
ON TAXON_INDEX(parent_id, taxon_id);
CREATE INDEX IF NOT EXISTS idx_catalog_source_ref
ON TAXON_INDEX(source, source_ref);
CREATE TABLE IF NOT EXISTS BUILD_QUEUE(
    taxon_id INTEGER PRIMARY KEY,
    next_rank TEXT,
    target_children INTEGER NOT NULL DEFAULT 25,
    populated_children INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_build_queue_status_priority
ON BUILD_QUEUE(status, priority, taxon_id);
CREATE TABLE IF NOT EXISTS BUILD_STAT(
    stat_key TEXT PRIMARY KEY,
    stat_value TEXT NOT NULL
);
"""

RANK_SCHEMA = """
CREATE TABLE IF NOT EXISTS TAXON(
    local_id INTEGER PRIMARY KEY,
    taxon_id INTEGER NOT NULL UNIQUE,
    canonical_name TEXT NOT NULL UNIQUE,
    common_name TEXT,
    scientific_name TEXT,
    parent_id INTEGER,
    origin_kind TEXT NOT NULL,
    source TEXT,
    source_ref TEXT,
    source_rank TEXT
);
CREATE INDEX IF NOT EXISTS idx_taxon_parent ON TAXON(parent_id, local_id);
CREATE INDEX IF NOT EXISTS idx_taxon_source_ref ON TAXON(source, source_ref);
CREATE TABLE IF NOT EXISTS ALIAS(
    alias TEXT NOT NULL,
    local_id INTEGER NOT NULL,
    alias_kind TEXT NOT NULL DEFAULT 'common',
    source TEXT,
    source_ref TEXT,
    PRIMARY KEY(alias, local_id)
);
CREATE INDEX IF NOT EXISTS idx_alias_lookup ON ALIAS(alias, local_id);
CREATE TABLE IF NOT EXISTS LOCAL_DESCRIPTOR(
    local_id INTEGER NOT NULL,
    descriptor_text TEXT NOT NULL,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    inheritable INTEGER NOT NULL DEFAULT 1,
    confidence REAL NOT NULL DEFAULT 1.0,
    novelty_score REAL NOT NULL DEFAULT 1.0,
    semantic_key TEXT,
    source TEXT,
    source_ref TEXT,
    PRIMARY KEY(local_id, descriptor_text, kind)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_local_descriptor_text
ON LOCAL_DESCRIPTOR(descriptor_text, state, kind, local_id);
CREATE TABLE IF NOT EXISTS LOCAL_CONDITION(
    condition_id INTEGER PRIMARY KEY,
    local_id INTEGER NOT NULL,
    note TEXT,
    source TEXT,
    source_ref TEXT
);
CREATE TABLE IF NOT EXISTS CONDITION_TERM(
    condition_id INTEGER NOT NULL,
    descriptor_text TEXT NOT NULL,
    test TEXT NOT NULL,
    PRIMARY KEY(condition_id, descriptor_text, test)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS CONDITION_EFFECT(
    condition_id INTEGER NOT NULL,
    descriptor_text TEXT NOT NULL,
    action TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'trait',
    PRIMARY KEY(condition_id, descriptor_text, action, kind)
) WITHOUT ROWID;
"""

EDGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS EDGE(
    parent_id INTEGER NOT NULL,
    child_id INTEGER NOT NULL,
    page_no INTEGER NOT NULL DEFAULT 0,
    slot_no INTEGER NOT NULL,
    PRIMARY KEY(parent_id, child_id),
    UNIQUE(parent_id, page_no, slot_no)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_edge_parent_slot
ON EDGE(parent_id, page_no, slot_no, child_id);
CREATE INDEX IF NOT EXISTS idx_edge_child
ON EDGE(child_id, parent_id);

-- Effective constraints are projected here, one physical level below TAXON.
-- origin_taxon_id preserves where an inherited constraint first came from.
CREATE TABLE IF NOT EXISTS CHILD_CONSTRAINT(
    parent_id INTEGER NOT NULL,
    child_id INTEGER NOT NULL,
    constraint_type TEXT NOT NULL,
    constraint_key TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'present',
    text_value TEXT NOT NULL DEFAULT '',
    num_value REAL,
    inheritable INTEGER NOT NULL DEFAULT 1,
    confidence REAL NOT NULL DEFAULT 1.0,
    novelty_score REAL NOT NULL DEFAULT 1.0,
    origin_taxon_id INTEGER NOT NULL,
    source TEXT,
    source_ref TEXT,
    PRIMARY KEY(parent_id, child_id, constraint_type, constraint_key)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_constraint_filter
ON CHILD_CONSTRAINT(parent_id, constraint_type, constraint_key, state, child_id);
CREATE INDEX IF NOT EXISTS idx_constraint_text
ON CHILD_CONSTRAINT(constraint_type, constraint_key, state, text_value, child_id);
CREATE INDEX IF NOT EXISTS idx_constraint_child
ON CHILD_CONSTRAINT(child_id, constraint_type, constraint_key);
"""


@dataclass(frozen=True)
class ShardSpec:
    kind: str
    name: str
    path: Path
    parent_rank: Optional[str] = None
    child_rank: Optional[str] = None
    rank: Optional[str] = None


class MMapTaxonomyStore:
    def __init__(
        self,
        root: Path = DEFAULT_STORE,
        *,
        build: bool = False,
        mmap_gib: float = DEFAULT_MMAP_GIB,
    ) -> None:
        self.root = Path(root)
        self.build = bool(build)
        self.mmap_gib = float(mmap_gib)
        self._db: dict[str, sqlite3.Connection] = {}
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        path = self.root / "store.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    @classmethod
    def create(
        cls,
        root: Path,
        *,
        budget_gib: float = DEFAULT_BUDGET_GIB,
        mmap_gib: float = DEFAULT_MMAP_GIB,
        overwrite_empty: bool = False,
    ) -> "MMapTaxonomyStore":
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        manifest_path = root / "store.json"
        if manifest_path.exists() and not overwrite_empty:
            return cls(root, build=True, mmap_gib=mmap_gib)

        specs: list[dict] = []
        catalog_path = root / "catalog.sqlite3"
        cls._init_file(catalog_path, CATALOG_SCHEMA, mmap_gib=mmap_gib)
        specs.append({"kind": "catalog", "file": catalog_path.name})

        for rank in RANKS:
            path = root / rank_db_name(rank)
            cls._init_file(path, RANK_SCHEMA, mmap_gib=mmap_gib)
            specs.append({"kind": "rank", "rank": rank, "file": path.name})

        for parent in RANKS[:-1]:
            child = NEXT_RANK[parent]
            path = root / edge_db_name(parent, child)
            cls._init_file(path, EDGE_SCHEMA, mmap_gib=mmap_gib)
            specs.append({
                "kind": "edge", "parent_rank": parent,
                "child_rank": child, "file": path.name,
            })

        # max_page_count is a hard virtual ceiling per shard, not eager allocation.
        # Weight by geometric depth so deeper ranks/edges can consume most capacity.
        weighted = []
        for spec in specs:
            if spec["kind"] == "catalog":
                weight = 1.0
            elif spec["kind"] == "rank":
                weight = float(25 ** RANKS.index(spec["rank"]))
            else:
                weight = float(25 ** (RANKS.index(spec["child_rank"]))) * 1.35
            weighted.append(weight)
        total_weight = sum(weighted)
        total_bytes = byte_budget(budget_gib)
        min_bytes = 64 * 1024 * 1024
        for spec, weight in zip(specs, weighted):
            path = root / spec["file"]
            allocation = max(min_bytes, int(total_bytes * (weight / total_weight)))
            db = sqlite3.connect(str(path))
            page_size = int(db.execute("PRAGMA page_size").fetchone()[0])
            max_pages = max(1024, allocation // page_size)
            db.execute("PRAGMA max_page_count=%d" % max_pages)
            db.commit()
            db.close()
            spec["budget_bytes"] = max_pages * page_size

        manifest = {
            "schema_version": 3,
            "layout": "sharded-mmap-constraints-below-rank",
            "page_size": PAGE_SIZE,
            "mmap_bytes": mmap_bytes(mmap_gib),
            "budget_gib": float(budget_gib),
            "children_per_page": CHILDREN_PER_PAGE,
            "id_encoding": "high-byte-rank + low-56-bit-local-id",
            "ranks": list(RANKS),
            "shards": specs,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        store = cls(root, build=True, mmap_gib=mmap_gib)
        cat = store.catalog()
        cat.executemany(
            "INSERT OR IGNORE INTO ID_ALLOC(rank,next_local_id) VALUES(?,1)",
            [(r,) for r in RANKS],
        )
        for key, value in (
            ("schema_version", "3"),
            ("layout", manifest["layout"]),
            ("budget_gib", str(budget_gib)),
            ("mmap_bytes", str(manifest["mmap_bytes"])),
        ):
            cat.execute("INSERT OR REPLACE INTO META(key,value) VALUES(?,?)", (key, value))
        cat.commit()
        return store

    @staticmethod
    def _init_file(path: Path, schema: str, *, mmap_gib: float) -> None:
        new = not path.exists() or path.stat().st_size == 0
        db = sqlite3.connect(str(path))
        if new:
            db.execute("PRAGMA page_size=%d" % PAGE_SIZE)
        db.execute("PRAGMA journal_mode=OFF")
        db.execute("PRAGMA synchronous=OFF")
        db.execute("PRAGMA temp_store=MEMORY")
        db.execute("PRAGMA mmap_size=%d" % mmap_bytes(mmap_gib))
        db.executescript(schema)
        db.commit()
        db.close()

    def _open(self, key: str, path: Path) -> sqlite3.Connection:
        db = self._db.get(key)
        if db is None:
            db = _connect(path, build=self.build, mmap_gib=self.mmap_gib)
            self._db[key] = db
        return db

    def catalog(self) -> sqlite3.Connection:
        return self._open("catalog", self.root / "catalog.sqlite3")

    def rank_db(self, rank: str) -> sqlite3.Connection:
        if rank not in RANKS:
            raise ValueError("unknown rank: %s" % rank)
        return self._open("rank:" + rank, self.root / rank_db_name(rank))

    def edge_db(self, parent_rank: str, child_rank: str) -> sqlite3.Connection:
        if NEXT_RANK.get(parent_rank) != child_rank:
            raise ValueError("non-adjacent ranks: %s -> %s" % (parent_rank, child_rank))
        key = "edge:%s:%s" % (parent_rank, child_rank)
        return self._open(key, self.root / edge_db_name(parent_rank, child_rank))

    def db_for_taxon(self, taxon_id: int) -> sqlite3.Connection:
        rank, _ = decode_taxon_id(taxon_id)
        return self.rank_db(rank)

    def allocate_id(self, rank: str) -> tuple[int, int]:
        cat = self.catalog()
        row = cat.execute("SELECT next_local_id FROM ID_ALLOC WHERE rank=?", (rank,)).fetchone()
        if row is None:
            raise RuntimeError("rank allocator missing: %s" % rank)
        local = int(row[0])
        cat.execute("UPDATE ID_ALLOC SET next_local_id=? WHERE rank=?", (local + 1, rank))
        return encode_taxon_id(rank, local), local

    def get_taxon(self, taxon_id: int) -> sqlite3.Row:
        rank, local = decode_taxon_id(taxon_id)
        row = self.rank_db(rank).execute("SELECT * FROM TAXON WHERE local_id=?", (local,)).fetchone()
        if row is None:
            raise KeyError("unknown taxon_id %s" % taxon_id)
        return row

    def find_taxon(self, rank: str, canonical_name: str) -> Optional[int]:
        row = self.catalog().execute(
            "SELECT taxon_id FROM TAXON_INDEX WHERE rank=? AND canonical_name=?",
            (rank, canonical_name),
        ).fetchone()
        return int(row[0]) if row else None

    def upsert_taxon(
        self,
        rank: str,
        canonical_name: str,
        *,
        parent_id: Optional[int] = None,
        common_name: Optional[str] = None,
        scientific_name: Optional[str] = None,
        source: Optional[str] = None,
        source_ref: Optional[str] = None,
        origin_kind: str = "scientific",
        source_rank: Optional[str] = None,
    ) -> int:
        canonical_name = " ".join(canonical_name.strip().split())
        existing = self.find_taxon(rank, canonical_name)
        if existing is not None:
            return existing
        taxon_id, local = self.allocate_id(rank)
        rdb = self.rank_db(rank)
        rdb.execute(
            """INSERT INTO TAXON(
                 local_id,taxon_id,canonical_name,common_name,scientific_name,
                 parent_id,origin_kind,source,source_ref,source_rank
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (local, taxon_id, canonical_name, common_name, scientific_name,
             parent_id, origin_kind, source, source_ref, source_rank),
        )
        self.catalog().execute(
            """INSERT INTO TAXON_INDEX(
                 taxon_id,rank,canonical_name,common_name,scientific_name,
                 parent_id,origin_kind,source,source_ref,source_rank
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (taxon_id, rank, canonical_name, common_name, scientific_name,
             parent_id, origin_kind, source, source_ref, source_rank),
        )
        return taxon_id

    def next_slot(self, parent_id: int, parent_rank: str, child_rank: str) -> tuple[int, int]:
        edb = self.edge_db(parent_rank, child_rank)
        row = edb.execute(
            "SELECT page_no,slot_no FROM EDGE WHERE parent_id=? ORDER BY page_no DESC,slot_no DESC LIMIT 1",
            (parent_id,),
        ).fetchone()
        if row is None:
            return 0, 1
        page_no, slot_no = int(row[0]), int(row[1])
        return (page_no, slot_no + 1) if slot_no < CHILDREN_PER_PAGE else (page_no + 1, 1)

    def link(self, parent_id: int, child_id: int) -> tuple[int, int]:
        parent_rank, _ = decode_taxon_id(parent_id)
        child_rank, _ = decode_taxon_id(child_id)
        if NEXT_RANK.get(parent_rank) != child_rank:
            raise ValueError("non-adjacent ranks: %s -> %s" % (parent_rank, child_rank))
        edb = self.edge_db(parent_rank, child_rank)
        existing = edb.execute(
            "SELECT page_no,slot_no FROM EDGE WHERE parent_id=? AND child_id=?",
            (parent_id, child_id),
        ).fetchone()
        if existing:
            return int(existing[0]), int(existing[1])
        page_no, slot_no = self.next_slot(parent_id, parent_rank, child_rank)
        edb.execute(
            "INSERT INTO EDGE(parent_id,child_id,page_no,slot_no) VALUES(?,?,?,?)",
            (parent_id, child_id, page_no, slot_no),
        )
        # Structural constraints are indexed immediately below the child table.
        child = self.get_taxon(child_id)
        for key, value in (
            ("rank", child_rank),
            ("origin_kind", child["origin_kind"]),
            ("source_rank", child["source_rank"] or ""),
        ):
            self._put_constraint(
                edb, parent_id, child_id,
                constraint_type="structural", constraint_key=key,
                text_value=str(value), origin_taxon_id=child_id,
            )
        return page_no, slot_no

    def add_child(self, parent_id: int, child_rank: str, child_name: str, **fields) -> int:
        parent_rank, _ = decode_taxon_id(parent_id)
        if NEXT_RANK.get(parent_rank) != child_rank:
            raise ValueError("%s expects %s" % (parent_rank, NEXT_RANK.get(parent_rank)))
        child_id = self.upsert_taxon(child_rank, child_name, parent_id=parent_id, **fields)
        self.link(parent_id, child_id)
        return child_id

    @staticmethod
    def normalize_descriptor(text: str) -> str:
        value = " ".join(text.strip().lower().split())
        words = WORD_RE.findall(value)
        if not 2 <= len(words) <= 3:
            raise ValueError("descriptor must contain 2-3 words: %r" % text)
        return " ".join(words)

    @staticmethod
    def semantic_key(text: str) -> str:
        stems = []
        for word in MMapTaxonomyStore.normalize_descriptor(text).split():
            stem = word
            for suffix in ("ing", "ed", "es", "s"):
                if len(stem) > len(suffix) + 3 and stem.endswith(suffix):
                    stem = stem[:-len(suffix)]
                    break
            stems.append(stem)
        return " ".join(sorted(set(stems)))

    def _put_constraint(
        self,
        edb: sqlite3.Connection,
        parent_id: int,
        child_id: int,
        *,
        constraint_type: str,
        constraint_key: str,
        state: str = "present",
        text_value: str = "",
        num_value: Optional[float] = None,
        inheritable: bool = True,
        confidence: float = 1.0,
        novelty_score: float = 1.0,
        origin_taxon_id: int,
        source: Optional[str] = None,
        source_ref: Optional[str] = None,
    ) -> None:
        edb.execute(
            """INSERT OR REPLACE INTO CHILD_CONSTRAINT(
                 parent_id,child_id,constraint_type,constraint_key,state,text_value,
                 num_value,inheritable,confidence,novelty_score,origin_taxon_id,
                 source,source_ref
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (parent_id, child_id, constraint_type, constraint_key, state, text_value,
             num_value, int(inheritable), confidence, novelty_score, origin_taxon_id,
             source, source_ref),
        )

    def local_descriptors(self, taxon_id: int) -> list[sqlite3.Row]:
        rank, local = decode_taxon_id(taxon_id)
        return self.rank_db(rank).execute(
            "SELECT * FROM LOCAL_DESCRIPTOR WHERE local_id=? ORDER BY kind,descriptor_text",
            (local,),
        ).fetchall()

    def effective_constraints(self, taxon_id: int) -> list[dict]:
        """Read already-materialized effective constraints for a child.

        Root kingdoms have no parent transition, so only their local descriptors
        are returned.  Every lower rank is O(1): the child id tells us exactly
        which edge shard contains its effective constraint projection.
        """
        rank, _ = decode_taxon_id(taxon_id)
        if rank == "kingdom":
            out = []
            for row in self.local_descriptors(taxon_id):
                out.append(dict(row))
            return out
        child_index = RANKS.index(rank)
        parent_rank = RANKS[child_index - 1]
        edb = self.edge_db(parent_rank, rank)
        return [dict(r) for r in edb.execute(
            "SELECT * FROM CHILD_CONSTRAINT WHERE child_id=? ORDER BY constraint_type,constraint_key",
            (taxon_id,),
        ).fetchall()]

    def set_descriptor(
        self,
        taxon_id: int,
        text: str,
        *,
        kind: str = "trait",
        state: str = "present",
        inheritable: bool = True,
        confidence: float = 1.0,
        novelty_score: float = 1.0,
        source: Optional[str] = None,
        source_ref: Optional[str] = None,
    ) -> None:
        text = self.normalize_descriptor(text)
        rank, local = decode_taxon_id(taxon_id)
        rdb = self.rank_db(rank)
        rdb.execute(
            """INSERT OR REPLACE INTO LOCAL_DESCRIPTOR(
                 local_id,descriptor_text,kind,state,inheritable,confidence,
                 novelty_score,semantic_key,source,source_ref
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (local, text, kind, state, int(inheritable), confidence,
             novelty_score, self.semantic_key(text), source, source_ref),
        )
        if rank == "kingdom":
            return
        parent_rank = RANKS[RANKS.index(rank) - 1]
        child = self.get_taxon(taxon_id)
        parent_id = int(child["parent_id"])
        edb = self.edge_db(parent_rank, rank)
        self._put_constraint(
            edb, parent_id, taxon_id,
            constraint_type=kind,
            constraint_key=text,
            state=state,
            text_value=text,
            inheritable=inheritable,
            confidence=confidence,
            novelty_score=novelty_score,
            origin_taxon_id=taxon_id,
            source=source,
            source_ref=source_ref,
        )

    def inherit_parent_constraints(self, parent_id: int, child_id: int) -> int:
        """Materialize inheritable parent constraints one level below the child.

        This is deliberate write-time amplification: it removes recursive
        inheritance work from the read path.
        """
        parent_rank, _ = decode_taxon_id(parent_id)
        child_rank, _ = decode_taxon_id(child_id)
        target = self.edge_db(parent_rank, child_rank)
        count = 0
        if parent_rank == "kingdom":
            source_rows = []
            for row in self.local_descriptors(parent_id):
                if int(row["inheritable"]):
                    source_rows.append({
                        "constraint_type": row["kind"],
                        "constraint_key": row["descriptor_text"],
                        "state": row["state"],
                        "text_value": row["descriptor_text"],
                        "num_value": None,
                        "inheritable": row["inheritable"],
                        "confidence": row["confidence"],
                        "novelty_score": row["novelty_score"],
                        "origin_taxon_id": parent_id,
                        "source": row["source"],
                        "source_ref": row["source_ref"],
                    })
        else:
            grand_rank = RANKS[RANKS.index(parent_rank) - 1]
            src = self.edge_db(grand_rank, parent_rank)
            source_rows = [dict(r) for r in src.execute(
                """SELECT constraint_type,constraint_key,state,text_value,num_value,
                          inheritable,confidence,novelty_score,origin_taxon_id,source,source_ref
                   FROM CHILD_CONSTRAINT
                   WHERE child_id=? AND inheritable=1
                     AND constraint_type IN ('trait','phenotype')""",
                (parent_id,),
            ).fetchall()]
        for row in source_rows:
            self._put_constraint(
                target, parent_id, child_id,
                constraint_type=row["constraint_type"],
                constraint_key=row["constraint_key"],
                state=row["state"],
                text_value=row["text_value"],
                num_value=row.get("num_value"),
                inheritable=bool(row["inheritable"]),
                confidence=float(row["confidence"]),
                novelty_score=float(row["novelty_score"]),
                origin_taxon_id=int(row["origin_taxon_id"]),
                source=row.get("source"),
                source_ref=row.get("source_ref"),
            )
            count += 1
        return count

    def children(
        self,
        parent_id: int,
        *,
        constraint_type: Optional[str] = None,
        constraint_key: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 25,
    ) -> list[int]:
        parent_rank, _ = decode_taxon_id(parent_id)
        child_rank = NEXT_RANK.get(parent_rank)
        if child_rank is None:
            return []
        edb = self.edge_db(parent_rank, child_rank)
        if constraint_key is None:
            rows = edb.execute(
                "SELECT child_id FROM EDGE WHERE parent_id=? ORDER BY page_no,slot_no LIMIT ?",
                (parent_id, int(limit)),
            ).fetchall()
        else:
            sql = """SELECT e.child_id
                     FROM CHILD_CONSTRAINT c
                     JOIN EDGE e ON e.parent_id=c.parent_id AND e.child_id=c.child_id
                     WHERE c.parent_id=? AND c.constraint_key=?"""
            params: list[object] = [parent_id, constraint_key]
            if constraint_type is not None:
                sql += " AND c.constraint_type=?"
                params.append(constraint_type)
            if state is not None:
                sql += " AND c.state=?"
                params.append(state)
            sql += " ORDER BY e.page_no,e.slot_no LIMIT ?"
            params.append(int(limit))
            rows = edb.execute(sql, params).fetchall()
        return [int(r[0]) for r in rows]

    def lineage(self, taxon_id: int) -> list[sqlite3.Row]:
        out = []
        current: Optional[int] = taxon_id
        while current is not None:
            row = self.get_taxon(current)
            out.append(row)
            current = int(row["parent_id"]) if row["parent_id"] is not None else None
        out.reverse()
        return out

    def edge_count(self, parent_id: int) -> int:
        parent_rank, _ = decode_taxon_id(parent_id)
        child_rank = NEXT_RANK.get(parent_rank)
        if child_rank is None:
            return 0
        return int(self.edge_db(parent_rank, child_rank).execute(
            "SELECT COUNT(*) FROM EDGE WHERE parent_id=?", (parent_id,)
        ).fetchone()[0])

    def commit(self) -> None:
        for db in self._db.values():
            db.commit()

    def close(self) -> None:
        for db in self._db.values():
            try:
                db.commit()
            finally:
                db.close()
        self._db.clear()

    def status(self) -> dict:
        shards = []
        total = 0
        for spec in self.manifest.get("shards", []):
            path = self.root / spec["file"]
            size = path.stat().st_size if path.exists() else 0
            total += size
            shards.append({**spec, "bytes": size})
        cat = self.catalog()
        return {
            "schema_version": 3,
            "root": str(self.root),
            "total_bytes": total,
            "total_gib": total / 1024 ** 3,
            "taxa": int(cat.execute("SELECT COUNT(*) FROM TAXON_INDEX").fetchone()[0]),
            "queue_pending": int(cat.execute("SELECT COUNT(*) FROM BUILD_QUEUE WHERE status='pending'").fetchone()[0]),
            "shards": shards,
        }


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--store", type=Path, default=DEFAULT_STORE)
    c.add_argument("--budget-gib", type=float, default=DEFAULT_BUDGET_GIB)
    c.add_argument("--mmap-gib", type=float, default=DEFAULT_MMAP_GIB)
    s = sub.add_parser("status")
    s.add_argument("--store", type=Path, default=DEFAULT_STORE)
    args = p.parse_args()
    if args.cmd == "create":
        store = MMapTaxonomyStore.create(args.store, budget_gib=args.budget_gib, mmap_gib=args.mmap_gib)
        print(json.dumps(store.status(), indent=2))
        store.close()
        return 0
    store = MMapTaxonomyStore(args.store, build=False)
    print(json.dumps(store.status(), indent=2))
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
