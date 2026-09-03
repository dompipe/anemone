#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

import mmap_store
from mmap_ids import apply as apply_safe_ids

apply_safe_ids(mmap_store)
from mmap_ids import decode_taxon_id, MAX_SAFE_TAXON_ID
from mmap_store import MMapTaxonomyStore


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="anemone-mmap-") as td:
        root = Path(td) / "store"
        store = MMapTaxonomyStore.create(root, budget_gib=0.5, mmap_gib=0.05)
        try:
            animalia = store.upsert_taxon(
                "kingdom", "Animalia", common_name="animals",
                source="smoke", source_ref="root", origin_kind="scientific",
                source_rank="kingdom",
            )
            store.set_descriptor(
                animalia, "multicellular body", kind="trait", state="present",
                novelty_score=1.0, source="smoke",
            )

            chordata = store.add_child(
                animalia, "phylum", "Chordata", common_name="chordates",
                source="smoke", source_ref="chordata", origin_kind="scientific",
                source_rank="phylum",
            )
            store.inherit_parent_constraints(animalia, chordata)
            store.set_descriptor(
                chordata, "dorsal nerve", kind="phenotype", state="present",
                novelty_score=1.0, source="smoke",
            )

            mammalia = store.add_child(
                chordata, "class", "Mammalia", common_name="mammals",
                source="smoke", source_ref="mammalia", origin_kind="scientific",
                source_rank="class",
            )
            store.inherit_parent_constraints(chordata, mammalia)
            store.set_descriptor(
                mammalia, "hair covered", kind="phenotype", state="present",
                novelty_score=1.0, source="smoke",
            )

            # Explicit local override of an inherited key must win in the child shard.
            store.set_descriptor(
                mammalia, "dorsal nerve", kind="phenotype", state="variable",
                novelty_score=0.8, source="smoke-override",
            )
            store.commit()

            assert decode_taxon_id(animalia)[0] == "kingdom"
            assert decode_taxon_id(chordata)[0] == "phylum"
            assert decode_taxon_id(mammalia)[0] == "class"
            assert max(animalia, chordata, mammalia) <= MAX_SAFE_TAXON_ID < (1 << 53)

            lineage = [r["canonical_name"] for r in store.lineage(mammalia)]
            assert lineage == ["Animalia", "Chordata", "Mammalia"], lineage

            effective = {
                (r["constraint_type"], r["constraint_key"]): r
                for r in store.effective_constraints(mammalia)
                if r["constraint_type"] in {"trait", "phenotype"}
            }
            assert effective[("trait", "multicellular body")]["state"] == "present"
            assert effective[("phenotype", "dorsal nerve")]["state"] == "variable"
            assert effective[("phenotype", "hair covered")]["state"] == "present"

            hits = store.children(
                chordata,
                constraint_type="phenotype",
                constraint_key="hair covered",
                state="present",
            )
            assert hits == [mammalia], hits

            status = store.status()
            assert status["taxa"] == 3
            assert len(status["shards"]) == 18
            assert (root / "store.json").exists()
            print("mmap taxonomy smoke test: ok")
            return 0
        finally:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
