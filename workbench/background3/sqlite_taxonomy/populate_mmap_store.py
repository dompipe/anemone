#!/usr/bin/env python3
"""Populate Anemone's v3 sharded mmap taxonomy store.

This preserves the source-faithful NCBI + semantic descriptor population model
while changing the physical write path:

* rank rows go to one rank shard,
* parent/child edges go to one transition shard,
* inheritable descriptors are projected into CHILD_CONSTRAINT at write time,
* reads therefore avoid recursive inheritance joins.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Optional

from encyclopedia_miner import EncyclopediaMiner, INDEX_DB, build_index
from mmap_store import (
    CHILDREN_PER_PAGE,
    DEFAULT_BUDGET_GIB,
    DEFAULT_MMAP_GIB,
    DEFAULT_STORE,
    NEXT_RANK,
    RANKS,
    MMapTaxonomyStore,
    decode_taxon_id,
)
from ncbi_source import NCBISource, SOURCE_DB, ensure_source

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


def parse_ncbi_ref(source_ref: Optional[str]) -> Optional[int]:
    if not source_ref or not source_ref.startswith("ncbi:"):
        return None
    try:
        return int(source_ref.split(":", 1)[1])
    except ValueError:
        return None


def descriptor_tokens(text: str) -> frozenset[str]:
    return frozenset(MMapTaxonomyStore.semantic_key(text).split())


def descriptor_similarity(a: str, b: str) -> float:
    aa, bb = descriptor_tokens(a), descriptor_tokens(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / len(aa | bb)


def effective_descriptor_texts(store: MMapTaxonomyStore, taxon_id: int) -> list[str]:
    rank, _ = decode_taxon_id(taxon_id)
    if rank == "kingdom":
        return [str(r["descriptor_text"]) for r in store.local_descriptors(taxon_id)]
    return [
        str(r["constraint_key"])
        for r in store.effective_constraints(taxon_id)
        if r.get("constraint_type") in {"trait", "phenotype"}
    ]


def descriptor_novelty(store: MMapTaxonomyStore, taxon_id: int, text: str) -> float:
    text = store.normalize_descriptor(text)
    existing = effective_descriptor_texts(store, taxon_id)
    if not existing:
        return 1.0
    highest = max(descriptor_similarity(text, item) for item in existing)
    return max(0.0, 1.0 - highest)


def queue_taxon(store: MMapTaxonomyStore, taxon_id: int, *, priority: int = 0) -> None:
    rank, _ = decode_taxon_id(taxon_id)
    next_rank = NEXT_RANK.get(rank)
    if next_rank is None:
        return
    existing = store.edge_count(taxon_id)
    store.catalog().execute(
        """INSERT INTO BUILD_QUEUE(
             taxon_id,next_rank,target_children,populated_children,status,priority
           ) VALUES(?,?,?,?,?,?)
           ON CONFLICT(taxon_id) DO UPDATE SET
             next_rank=excluded.next_rank,
             target_children=excluded.target_children,
             populated_children=MAX(BUILD_QUEUE.populated_children,excluded.populated_children),
             priority=MIN(BUILD_QUEUE.priority,excluded.priority),
             status=CASE WHEN BUILD_QUEUE.status='complete' THEN 'complete' ELSE 'pending' END,
             updated_at=CURRENT_TIMESTAMP""",
        (
            taxon_id, next_rank, CHILDREN_PER_PAGE, existing,
            "complete" if existing >= CHILDREN_PER_PAGE else "pending",
            priority,
        ),
    )


def next_pending(store: MMapTaxonomyStore) -> Optional[sqlite3.Row]:
    return store.catalog().execute(
        """SELECT q.*,t.rank,t.canonical_name,t.common_name,t.scientific_name,
                  t.source_ref,t.origin_kind,t.source_rank
           FROM BUILD_QUEUE q JOIN TAXON_INDEX t USING(taxon_id)
           WHERE q.status='pending'
           ORDER BY q.priority,t.taxon_id LIMIT 1"""
    ).fetchone()


def inherit_constraints(store: MMapTaxonomyStore, parent_id: int, child_id: int) -> None:
    store.inherit_parent_constraints(parent_id, child_id)


def enrich_taxon(
    store: MMapTaxonomyStore,
    miner: Optional[EncyclopediaMiner],
    taxon_id: int,
    *,
    descriptor_limit: int,
    min_novelty: float = 0.35,
) -> int:
    if miner is None or descriptor_limit <= 0:
        return 0
    taxon = store.get_taxon(taxon_id)
    aliases = [
        value for value in (taxon["common_name"], taxon["scientific_name"])
        if value and value != taxon["canonical_name"]
    ]
    candidates = miner.descriptors_for(
        taxon["canonical_name"], *aliases,
        limit=max(descriptor_limit * 3, descriptor_limit),
    )
    inserted = 0
    for item in candidates:
        if inserted >= descriptor_limit:
            break
        novelty = descriptor_novelty(store, taxon_id, item["descriptor"])
        if novelty < min_novelty:
            continue
        store.set_descriptor(
            taxon_id,
            item["descriptor"],
            kind=item["kind"],
            state=item["state"],
            inheritable=True,
            confidence=float(item["score"]),
            novelty_score=novelty,
            source="anemone-encyclopedia",
            source_ref=item.get("source_file"),
        )
        inserted += 1
    return inserted


def seed_kingdoms(
    store: MMapTaxonomyStore,
    source: NCBISource,
    miner: Optional[EncyclopediaMiner],
    *,
    kingdom_limit: Optional[int],
    descriptor_limit: int,
) -> int:
    count = 0
    for item in source.kingdoms(limit=kingdom_limit):
        name = item["scientific_name"]
        taxon_id = store.upsert_taxon(
            "kingdom", name,
            common_name=item.get("common_name"),
            scientific_name=name,
            source="NCBI Taxonomy",
            source_ref="ncbi:%s" % item["tax_id"],
            origin_kind="scientific",
            source_rank="kingdom",
        )
        enrich_taxon(store, miner, taxon_id, descriptor_limit=descriptor_limit)
        queue_taxon(store, taxon_id, priority=0)
        count += 1
    cat = store.catalog()
    for key, value in (
        ("kingdom_count", count),
        ("leaf_capacity_per_kingdom", LEAF_CAPACITY_PER_KINGDOM),
        ("node_capacity_below_kingdom", NODE_CAPACITY_BELOW_KINGDOM),
    ):
        cat.execute(
            "INSERT OR REPLACE INTO BUILD_STAT(stat_key,stat_value) VALUES(?,?)",
            (key, str(value)),
        )
    store.commit()
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
    store: MMapTaxonomyStore,
    parent_id: int,
    next_rank: str,
    item: dict,
) -> int:
    name = item["scientific_name"]
    source_tax_id = item.get("tax_id")
    if next_rank == "name":
        source_ref = "ncbi-name:%s:%s:%s" % (
            source_tax_id, item.get("name_class", "alias"), name,
        )
        origin_kind = "projected"
        source_rank = item.get("name_class", "name")
    else:
        source_ref = "ncbi:%s" % source_tax_id
        origin_kind = "scientific" if item.get("rank") == next_rank else "projected"
        source_rank = item.get("rank")

    child_id = store.add_child(
        parent_id, next_rank, name,
        common_name=item.get("common_name"),
        scientific_name=name if next_rank != "name" else None,
        source="NCBI Taxonomy",
        source_ref=source_ref,
        origin_kind=origin_kind,
        source_rank=source_rank,
    )
    inherit_constraints(store, parent_id, child_id)
    return child_id


def semantic_descriptor_pool(
    store: MMapTaxonomyStore,
    miner: Optional[EncyclopediaMiner],
    parent_id: int,
    *,
    limit: int = 240,
    min_novelty: float = 0.35,
) -> list[dict]:
    if miner is None:
        return []
    parent = store.get_taxon(parent_id)
    anchor = parent["scientific_name"] or parent["common_name"] or parent["canonical_name"]
    aliases = [
        value for value in (parent["common_name"], parent["scientific_name"])
        if value and value != anchor
    ]
    pool = miner.descriptors_for(anchor, *aliases, limit=limit)
    return [item for item in pool if descriptor_novelty(store, parent_id, item["descriptor"]) >= min_novelty]


def delete_child(store: MMapTaxonomyStore, parent_id: int, child_id: int) -> None:
    parent_rank, _ = decode_taxon_id(parent_id)
    child_rank, child_local = decode_taxon_id(child_id)
    edb = store.edge_db(parent_rank, child_rank)
    edb.execute("DELETE FROM CHILD_CONSTRAINT WHERE parent_id=? AND child_id=?", (parent_id, child_id))
    edb.execute("DELETE FROM EDGE WHERE parent_id=? AND child_id=?", (parent_id, child_id))
    store.rank_db(child_rank).execute("DELETE FROM LOCAL_DESCRIPTOR WHERE local_id=?", (child_local,))
    store.rank_db(child_rank).execute("DELETE FROM TAXON WHERE local_id=?", (child_local,))
    store.catalog().execute("DELETE FROM TAXON_INDEX WHERE taxon_id=?", (child_id,))
    store.catalog().execute("DELETE FROM BUILD_QUEUE WHERE taxon_id=?", (child_id,))


def add_semantic_children(
    store: MMapTaxonomyStore,
    miner: Optional[EncyclopediaMiner],
    parent_id: int,
    next_rank: str,
    *,
    needed: int,
    descriptors_per_child: int = 4,
    min_novelty: float = 0.35,
) -> tuple[int, int]:
    if needed <= 0 or miner is None:
        return 0, 0
    parent = store.get_taxon(parent_id)
    pool = semantic_descriptor_pool(
        store, miner, parent_id,
        limit=max(240, needed * max(8, descriptors_per_child * 4)),
        min_novelty=min_novelty,
    )
    if not pool:
        return 0, 0

    created = 0
    descriptor_assignments = 0
    used_primary: set[str] = set()
    for primary_index, primary in enumerate(pool):
        if created >= needed:
            break
        phrase = primary["descriptor"]
        if phrase in used_primary:
            continue
        used_primary.add(phrase)
        child_name = "%s / %s" % (parent["canonical_name"], phrase)
        try:
            child_id = store.add_child(
                parent_id, next_rank, child_name,
                common_name=parent["common_name"],
                scientific_name=parent["scientific_name"],
                source="Anemone semantic taxonomy",
                source_ref="semantic-parent:%s" % parent_id,
                origin_kind="semantic",
                source_rank="descriptor_cluster",
            )
            inherit_constraints(store, parent_id, child_id)
        except sqlite3.IntegrityError:
            continue

        attached = 0
        ordered = [primary] + [
            pool[(primary_index + offset) % len(pool)]
            for offset in range(1, min(len(pool), descriptors_per_child * 3))
        ]
        seen: set[str] = set()
        for item in ordered:
            text = item["descriptor"]
            if text in seen:
                continue
            seen.add(text)
            novelty = descriptor_novelty(store, child_id, text)
            if novelty < min_novelty:
                continue
            store.set_descriptor(
                child_id, text,
                kind=item["kind"], state=item["state"], inheritable=True,
                confidence=float(item["score"]), novelty_score=novelty,
                source="anemone-encyclopedia", source_ref=item.get("source_file"),
            )
            attached += 1
            descriptor_assignments += 1
            if attached >= descriptors_per_child:
                break
        if attached == 0:
            delete_child(store, parent_id, child_id)
            continue
        created += 1
        if next_rank != "name":
            queue_taxon(store, child_id, priority=RANKS.index(next_rank))
    return created, descriptor_assignments


def actual_store_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.glob("*.sqlite3") if p.is_file())


def budget_near_limit(root: Path, budget_gib: float, headroom: float = 0.985) -> bool:
    return actual_store_bytes(root) >= int(budget_gib * 1024 ** 3 * headroom)


def mark_queue(store: MMapTaxonomyStore, taxon_id: int, *, populated: int, status: str) -> None:
    store.catalog().execute(
        """UPDATE BUILD_QUEUE
           SET populated_children=?,status=?,updated_at=CURRENT_TIMESTAMP
           WHERE taxon_id=?""",
        (populated, status, taxon_id),
    )


def populate(
    store: MMapTaxonomyStore,
    source: NCBISource,
    miner: Optional[EncyclopediaMiner],
    *,
    budget_gib: float,
    descriptor_limit: int = 10,
    semantic_fill: bool = True,
    semantic_descriptors_per_child: int = 4,
    max_nodes: int = 0,
    commit_every: int = 1000,
) -> dict:
    created = 0
    expanded = 0
    descriptor_assignments = 0

    while True:
        if max_nodes and created >= max_nodes:
            break
        if budget_near_limit(store.root, budget_gib):
            store.catalog().execute(
                """UPDATE BUILD_QUEUE SET status='budget_stop',updated_at=CURRENT_TIMESTAMP
                   WHERE status IN ('pending','running')"""
            )
            store.commit()
            break

        row = next_pending(store)
        if row is None:
            break
        parent_id = int(row["taxon_id"])
        next_rank = str(row["next_rank"])
        parent_rank = str(row["rank"])
        store.catalog().execute(
            "UPDATE BUILD_QUEUE SET status='running',updated_at=CURRENT_TIMESTAMP WHERE taxon_id=?",
            (parent_id,),
        )

        existing = store.edge_count(parent_id)
        needed = max(0, CHILDREN_PER_PAGE - existing)
        candidates = source_children(source, row, next_rank, limit=needed)

        for item in candidates:
            if budget_near_limit(store.root, budget_gib):
                break
            try:
                child_id = add_source_child(store, parent_id, next_rank, item)
            except (sqlite3.IntegrityError, sqlite3.OperationalError):
                continue
            created += 1
            descriptor_assignments += enrich_taxon(
                store, miner, child_id, descriptor_limit=descriptor_limit,
            )
            if next_rank != "name":
                queue_taxon(store, child_id, priority=RANKS.index(next_rank))
            if commit_every and created % commit_every == 0:
                store.commit()

        populated = store.edge_count(parent_id)
        remaining = max(0, CHILDREN_PER_PAGE - populated)
        if semantic_fill and remaining > 0 and not budget_near_limit(store.root, budget_gib):
            made, descs = add_semantic_children(
                store, miner, parent_id, next_rank,
                needed=remaining,
                descriptors_per_child=semantic_descriptors_per_child,
            )
            created += made
            descriptor_assignments += descs
            populated = store.edge_count(parent_id)

        if budget_near_limit(store.root, budget_gib):
            mark_queue(store, parent_id, populated=populated, status="budget_stop")
        elif populated >= CHILDREN_PER_PAGE:
            mark_queue(store, parent_id, populated=populated, status="complete")
        else:
            mark_queue(store, parent_id, populated=populated, status="source_exhausted")
        expanded += 1
        if commit_every and expanded % max(1, commit_every // 10) == 0:
            store.commit()

    store.catalog().execute(
        "INSERT OR REPLACE INTO BUILD_STAT(stat_key,stat_value) VALUES('created_nodes',?)",
        (str(created),),
    )
    store.catalog().execute(
        "INSERT OR REPLACE INTO BUILD_STAT(stat_key,stat_value) VALUES('descriptor_assignments',?)",
        (str(descriptor_assignments),),
    )
    store.commit()
    return {
        "created": created,
        "expanded": expanded,
        "descriptor_assignments": descriptor_assignments,
        "store": store.status(),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store", type=Path, default=DEFAULT_STORE)
    p.add_argument("--budget-gib", type=float, default=DEFAULT_BUDGET_GIB)
    p.add_argument("--mmap-gib", type=float, default=DEFAULT_MMAP_GIB)
    p.add_argument("--source-db", type=Path, default=SOURCE_DB)
    p.add_argument("--encyclopedia-db", type=Path, default=INDEX_DB)
    p.add_argument("--kingdom-limit", type=int)
    p.add_argument("--descriptors-per-node", type=int, default=10)
    p.add_argument("--semantic-descriptors-per-child", type=int, default=4)
    p.add_argument("--max-nodes", type=int, default=0)
    p.add_argument("--commit-every", type=int, default=1000)
    p.add_argument("--skip-encyclopedia", action="store_true")
    p.add_argument("--no-semantic-fill", action="store_true")
    p.add_argument("--rebuild-source", action="store_true")
    args = p.parse_args()

    ensure_source(args.source_db, rebuild=args.rebuild_source)
    source = NCBISource(args.source_db)

    miner = None
    if not args.skip_encyclopedia:
        if not args.encyclopedia_db.exists():
            build_index(args.encyclopedia_db)
        miner = EncyclopediaMiner(args.encyclopedia_db)

    store = MMapTaxonomyStore.create(
        args.store,
        budget_gib=args.budget_gib,
        mmap_gib=args.mmap_gib,
    )
    try:
        kingdom_count = int(store.catalog().execute(
            "SELECT COUNT(*) FROM TAXON_INDEX WHERE rank='kingdom'"
        ).fetchone()[0])
        if kingdom_count == 0:
            seed_kingdoms(
                store, source, miner,
                kingdom_limit=args.kingdom_limit,
                descriptor_limit=args.descriptors_per_node,
            )
        result = populate(
            store, source, miner,
            budget_gib=args.budget_gib,
            descriptor_limit=args.descriptors_per_node,
            semantic_fill=not args.no_semantic_fill,
            semantic_descriptors_per_child=args.semantic_descriptors_per_child,
            max_nodes=args.max_nodes,
            commit_every=args.commit_every,
        )
        print(json.dumps(result, indent=2, default=str))
    finally:
        if miner is not None:
            miner.close()
        source.close()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
