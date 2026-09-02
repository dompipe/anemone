#!/usr/bin/env python3
"""Fast offline smoke test for the 25-way taxonomy builder."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from populate_taxonomy import populate, seed_kingdoms
from taxonomy_db import init_db


class FakeMiner:
    DESCRIPTORS = [
        "warm blooded", "hair covered", "milk producing", "four chambered heart",
        "internal skeleton", "bilateral symmetry", "active metabolism", "lung breathing",
        "parental care", "sensory whiskers", "mobile body", "sexual reproduction",
        "complex nervous system", "paired limbs", "endothermic regulation", "vertebral column",
        "closed circulation", "muscular movement", "central brain", "distinct head",
        "jaw structure", "tooth differentiation", "body insulation", "social behavior",
        "territorial signaling", "seasonal breeding", "live birth", "placental nourishment",
        "auditory sensitivity", "olfactory sensing", "visual tracking", "food specialization",
        "habitat selection", "water balance", "temperature control", "energy storage",
        "immune defense", "wound healing", "growth regulation", "hormonal signaling",
        "sleep cycling", "circadian rhythm", "learning behavior", "memory formation",
        "vocal communication", "chemical signaling", "mate selection", "offspring protection",
        "locomotor pattern", "feeding strategy", "digestive specialization", "renal filtration",
        "skeletal support", "joint mobility", "muscle fibers", "skin glands",
        "hair follicles", "ear structures", "eye structures", "nasal passages",
        "oral cavity", "limb posture", "body proportions", "surface texture",
        "color pattern", "growth pattern", "resource use", "range preference",
    ]

    def descriptors_for(self, taxon_name: str, *aliases: str, limit: int = 12):
        return [
            {
                "descriptor": phrase,
                "kind": "phenotype" if any(
                    token in phrase
                    for token in ("hair", "eye", "ear", "skin", "limb", "body", "jaw", "tooth")
                ) else "trait",
                "state": "present",
                "score": 0.8,
                "source_file": "smoke",
            }
            for phrase in self.DESCRIPTORS[:limit]
        ]


class FakeSource:
    def kingdoms(self, limit=None):
        rows = [{"tax_id": 1, "scientific_name": "Animalia", "common_name": "animals"}]
        return rows[:limit] if limit else rows

    def nearest_descendants(self, parent_tax_id, target_ranks, limit=25):
        rank = target_ranks[0]
        return [
            {
                "tax_id": parent_tax_id * 10 + i,
                "rank": rank,
                "scientific_name": f"{rank.title()}{parent_tax_id}_{i}",
                "common_name": None,
                "depth": 1,
            }
            for i in range(1, 3)
        ][:limit]

    def names(self, tax_id, limit=25):
        return [
            {"name": f"alias{tax_id}_{i}", "name_class": "synonym"}
            for i in range(2)
        ][:limit]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "taxonomy.sqlite3"
        db = init_db(db_path, 0.02)
        try:
            source = FakeSource()
            miner = FakeMiner()
            assert seed_kingdoms(
                db,
                source,
                miner,
                kingdom_limit=None,
                descriptor_limit=5,
            ) == 1

            result = populate(
                db,
                db_path,
                source,
                miner,
                descriptor_limit=5,
                semantic_fill=True,
                semantic_descriptors_per_child=2,
                max_nodes=100,
                commit_every=10,
            )

            assert result["created"] == 100
            assert db.execute("SELECT COUNT(*) FROM KINGDOM_PHYLUM").fetchone()[0] == 25
            assert db.execute("SELECT COUNT(*) FROM PHYLUM_CLASS").fetchone()[0] >= 50
            assert db.execute(
                "SELECT COUNT(*) FROM TAXON WHERE origin_kind='semantic'"
            ).fetchone()[0] > 0
            assert db.execute(
                "SELECT COUNT(*) FROM DESCRIPTOR WHERE word_count NOT BETWEEN 2 AND 3"
            ).fetchone()[0] == 0
            print("taxonomy smoke test: ok")
        finally:
            db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
