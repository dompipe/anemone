#!/usr/bin/env python3
"""Populate Anemone's 25-way taxonomy database from current source data.

The geometric target is 25 children at each of eight transitions below every
kingdom (25^8 leaf capacity per kingdom), but the build is source-faithful and
hard-capped by SQLite at the configured size (35 GiB by default).

Scientific ranks come from NCBI Taxonomy. Compact traits/phenotypes are mined
from Anemone's local encyclopedia and accepted only when semantically new
relative to inherited ancestor descriptors.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from encyclopedia_miner import EncyclopediaMiner, INDEX_DB, build_index
from ncbi_source import NCBISource, SOURCE_DB, ensure_source
from taxonomy_db import (
    CHILDREN_PER_PAGE,
    DEFAULT_BUDGET_GIB,
    DEFAULT_DB,
    EDGE,
    NEXT_RANK,
    RANKS,
    add_child,
    database_status,
    get_taxon,
    init_db,
    set_descriptor,
    upsert_taxon,
)

LEAF_CAPACITY_PER_KINGDOM = CHILDREN_PER_PAGE ** 8
NODE_CAPACITY_BELOW_KINGDOM = sum(CHILDREN_PER_PAGE ** i for i in range(1, 9))

SOURCE_RANKS = {
    "phylum": ("phylum",),
    "class": ("class",),
    "order": ("order",),
    "family": ("family",),
    "genus": ("genus",),
    "species": ("species",),
    "type": (
        "subspecies", "varietas", "forma", "strain", "isolate",
        "serotype", "serogroup", "biotype", "genotype", "morph",
        "pathogroup", "forma specialis",
    ),
}


def parse_ncbi_ref(source_ref: str | None) -> int | None:
    if not source_ref or not source_ref.startswith("ncbi:"):
        return None
    try:
        return int(source_ref.split(":", 1)[1])
    except ValueError:
        return None


def edge_count(db: sqlite3.Connection, parent_id: int, parent_rank: str) -> int:
    child_rank = NEXT_RANK.get(parent_rank)
    if child_rank is None:
        return 0
    table, parent_col, _ = EDGE[(parent_rank, child_rank)]
    return int(
        db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {parent_col}=?",
            (parent_id,),
        ).fetchone()[0]
    )


def queue_taxon(db: sqlite3.Connection, taxon_id: int, *, priority: int = 0) -> None:
    taxon = get_taxon(db, taxon_id)
    next_rank = NEXT_RANK.get(taxon["rank"])
    if next_rank is None:
        return
    existing = edge_count(db, taxon_id, taxon["rank"])
    db.execute(
        """
        INSERT INTO BUILD_QUEUE(
            taxon_id,next_rank,target_children,populated_children,status,priority
        ) VALUES(?,?,?,?,?,?)
        ON CONFLICT(taxon_id) DO UPDATE SET
            next_rank=excluded.next_rank,
            target_children=excluded.target_children,
            populated_children=MAX(BUILD_QUEUE.populated_children, excluded.populated_children),
            priority=MIN(BUILD_QUEUE.priority, excluded.priority),
            status=CASE
                WHEN BUILD_QUEUE.status='complete' THEN 'complete'
                ELSE 'pending'
            END,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            taxon_id,
            next_rank,
            CHILDREN_PER_PAGE,
            existing,
            "complete" if existing >= CHILDREN_PER_PAGE else "pending",
            priority,
        ),
    )


def next_pending(db: sqlite3.Connection) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT q.*, t.rank, t.canonical_name, t.common_name,
               t.scientific_name, t.source_ref
        FROM BUILD_QUEUE q
        JOIN TAXON t USING(taxon_id)
        WHERE q.status='pending'
        ORDER BY q.priority, t.taxon_id
        LIMIT 1
        """
    ).fetchone()


def enrich_taxon(
    db: sqlite3.Connection,
    miner: EncyclopediaMiner | None,
    taxon_id: int,
    *,
    descriptor_limit: int,
) -> int:
    if miner is None or descriptor_limit <= 0:
        return 0
    taxon = get_taxon(db, taxon_id)
    aliases = [
        value
        for value in (taxon["common_name"], taxon["scientific_name"])
        if value and value != taxon["canonical_name"]
    ]
    candidates = miner.descriptors_for(
        taxon["canonical_name"],
        *aliases,
        limit=max(descriptor_limit * 3, descriptor_limit),
    )
    inserted = 0
    for item in candidates:
        if inserted >= descriptor_limit:
            break
        did = set_descriptor(
            db,
            taxon_id,
            item["descriptor"],
            kind=item["kind"],
            state=item["state"],
            inheritable=True,
            confidence=float(item["score"]),
            source="anemone-encyclopedia",
            source_ref=item.get("source_file"),
            require_novel=True,
            min_novelty=0.35,
        )
        if did is not None:
            inserted += 1
    return inserted


def seed_kingdoms(
    db: sqlite3.Connection,
    source: NCBISource,
    miner: EncyclopediaMiner | None,
    *,
    kingdom_limit: int | None,
    descriptor_limit: int,
) -> int:
    count = 0
    for item in source.kingdoms(limit=kingdom_limit):
        name = item["scientific_name"]
        taxon_id = upsert_taxon(
            db,
            "kingdom",
            name,
            common_name=item.get("common_name"),
            scientific_name=name,
            source="NCBI Taxonomy",
            source_ref=f"ncbi:{item['tax_id']}",
            origin_kind="scientific",
            source_rank="kingdom",
        )
        enrich_taxon(
            db,
            miner,
            taxon_id,
            descriptor_limit=descriptor_limit,
        )
        queue_taxon(db, taxon_id, priority=0)
        count += 1
    db.execute(
        """INSERT OR REPLACE INTO BUILD_STAT(stat_key,stat_value)
           VALUES('kingdom_count',?)""",
        (str(count),),
    )
    db.execute(
        """INSERT OR REPLACE INTO BUILD_STAT(stat_key,stat_value)
           VALUES('leaf_capacity_per_kingdom',?)""",
        (str(LEAF_CAPACITY_PER_KINGDOM),),
    )
    db.execute(
        """INSERT OR REPLACE INTO BUILD_STAT(stat_key,stat_value)
           VALUES('node_capacity_below_kingdom',?)""",
        (str(NODE_CAPACITY_BELOW_KINGDOM),),
    )
    db.commit()
    return count


def source_children(
    source: NCBISource,
    parent: sqlite3.Row,
    next_rank: str,
    *,
    limit: int,
) -> list[dict]:
    tax_id = parse_ncbi_ref(parent["source_ref"])
    if tax_id is None:
        return []
    if next_rank == "name":
        return [
            {
                "tax_id": tax_id,
                "rank": "name",
                "scientific_name": item["name"],
                "common_name": None,
                "name_class": item["name_class"],
            }
            for item in source.names(tax_id, limit=limit)
        ]
    target = SOURCE_RANKS.get(next_rank)
    if not target:
        return []
    return source.nearest_descendants(tax_id, target, limit=limit)


def add_source_child(
    db: sqlite3.Connection,
    parent_id: int,
    next_rank: str,
    item: dict,
) -> int:
    name = item["scientific_name"]
    source_tax_id = item.get("tax_id")
    if next_rank == "name":
        source_ref = (
            f"ncbi-name:{source_tax_id}:{item.get('name_class','alias')}:{name}"
        )
        origin_kind = "projected"
        source_rank = item.get("name_class", "name")
    else:
        source_ref = f"ncbi:{source_tax_id}"
        origin_kind = "scientific" if item.get("rank") == next_rank else "projected"
        source_rank = item.get("rank")

    return add_child(
        db,
        parent_id,
        next_rank,
        name,
        common_name=item.get("common_name"),
        scientific_name=name if next_rank != "name" else None,
        source="NCBI Taxonomy",
        source_ref=source_ref,
        origin_kind=origin_kind,
        source_rank=source_rank,
    )


def mark_queue(
    db: sqlite3.Connection,
    taxon_id: int,
    *,
    populated: int,
    status: str,
) -> None:
    db.execute(
        """
        UPDATE BUILD_QUEUE
        SET populated_children=?, status=?, updated_at=CURRENT_TIMESTAMP
        WHERE taxon_id=?
        """,
        (populated, status, taxon_id),
    )


def budget_near_limit(
    db: sqlite3.Connection,
    db_path: Path,
    *,
    headroom: float = 0.985,
) -> bool:
    status = database_status(db, db_path)
    if not status["max_bytes"]:
        return False
    return status["main_bytes"] >= int(status["max_bytes"] * headroom)


def populate(
    db: sqlite3.Connection,
    db_path: Path,
    source: NCBISource,
    miner: EncyclopediaMiner | None,
    *,
    descriptor_limit: int = 10,
    max_nodes: int = 0,
    commit_every: int = 500,
) -> dict:
    created = 0
    expanded = 0
    descriptor_assignments = 0

    while True:
        if max_nodes and created >= max_nodes:
            break
        if budget_near_limit(db, db_path):
            db.execute(
                """UPDATE BUILD_QUEUE
                   SET status='budget_stop', updated_at=CURRENT_TIMESTAMP
                   WHERE status IN ('pending','running')"""
            )
            db.commit()
            break

        row = next_pending(db)
        if row is None:
            break

        parent_id = int(row["taxon_id"])
        next_rank = str(row["next_rank"])
        parent_rank = str(row["rank"])
        db.execute(
            """UPDATE BUILD_QUEUE SET status='running',updated_at=CURRENT_TIMESTAMP
               WHERE taxon_id=?""",
            (parent_id,),
        )

        existing = edge_count(db, parent_id, parent_rank)
        needed = max(0, CHILDREN_PER_PAGE - existing)
        candidates = source_children(source, row, next_rank, limit=needed)

        for item in candidates:
            if budget_near_limit(db, db_path):
                break
            try:
                child_id = add_source_child(db, parent_id, next_rank, item)
            except sqlite3.IntegrityError:
                continue
            created += 1
            descriptor_assignments += enrich_taxon(
                db,
                miner,
                child_id,
                descriptor_limit=descriptor_limit,
            )
            if next_rank != "name":
                queue_taxon(
                    db,
                    child_id,
                    priority=RANKS.index(next_rank),
                )
            if max_nodes and created >= max_nodes:
                break

        total = edge_count(db, parent_id, parent_rank)
        status = "complete" if total >= CHILDREN_PER_PAGE else "source_exhausted"
        if budget_near_limit(db, db_path):
            status = "budget_stop"
        mark_queue(db, parent_id, populated=total, status=status)
        expanded += 1

        if expanded % commit_every == 0:
            db.commit()
            db.execute("PRAGMA wal_checkpoint(PASSIVE)")

    db.commit()
    status = database_status(db, db_path)
    return {
        "created": created,
        "expanded": expanded,
        "descriptor_assignments": descriptor_assignments,
        "database": status,
    }


def reopen_budget_stops(db: sqlite3.Connection) -> int:
    cursor = db.execute(
        """UPDATE BUILD_QUEUE
           SET status='pending',updated_at=CURRENT_TIMESTAMP
           WHERE status='budget_stop'"""
    )
    db.commit()
    return cursor.rowcount


def print_summary(result: dict) -> None:
    dbs = result["database"]
    print(f"created taxa: {result['created']:,}")
    print(f"expanded parents: {result['expanded']:,}")
    print(f"new descriptor assignments: {result['descriptor_assignments']:,}")
    print(f"total taxa: {dbs['taxa']:,}")
    print(f"total descriptor assignments: {dbs['descriptors']:,}")
    print(f"database: {dbs['main_gib']:.3f} / {dbs['max_gib']:.3f} GiB")


def cli() -> int:
    parser = argparse.ArgumentParser(description="Populate Anemone 25-way taxonomy")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--budget-gib", type=float, default=DEFAULT_BUDGET_GIB)
    parser.add_argument("--source-db", type=Path, default=SOURCE_DB)
    parser.add_argument("--encyclopedia-db", type=Path, default=INDEX_DB)
    parser.add_argument("--kingdom-limit", type=int, default=None)
    parser.add_argument("--descriptors-per-node", type=int, default=10)
    parser.add_argument("--max-nodes", type=int, default=0)
    parser.add_argument("--commit-every", type=int, default=500)
    parser.add_argument("--skip-encyclopedia", action="store_true")
    parser.add_argument("--reopen-budget-stop", action="store_true")
    parser.add_argument("--rebuild-source", action="store_true")
    args = parser.parse_args()

    ensure_source(db_path=args.source_db, rebuild=args.rebuild_source)
    if not args.skip_encyclopedia:
        build_index(args.encyclopedia_db)

    db = init_db(args.db, args.budget_gib)
    source = NCBISource(args.source_db)
    miner = None if args.skip_encyclopedia else EncyclopediaMiner(args.encyclopedia_db)
    try:
        if args.reopen_budget_stop:
            reopen_budget_stops(db)
        if db.execute("SELECT COUNT(*) FROM TAXON WHERE rank='kingdom'").fetchone()[0] == 0:
            kingdoms = seed_kingdoms(
                db,
                source,
                miner,
                kingdom_limit=args.kingdom_limit,
                descriptor_limit=args.descriptors_per_node,
            )
            print(f"seeded kingdoms: {kingdoms:,}")
        result = populate(
            db,
            args.db,
            source,
            miner,
            descriptor_limit=args.descriptors_per_node,
            max_nodes=args.max_nodes,
            commit_every=args.commit_every,
        )
        print_summary(result)
    finally:
        if miner is not None:
            miner.close()
        source.close()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
