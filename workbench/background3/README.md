# Anemone Background 3-Word Workbench

This directory is the staging area for the replacement Anemone semantic background on the `anemone-store` branch.

## Canonical large-taxonomy format

The large taxonomy corpus now uses SQLite under:

```text
workbench/background3/sqlite_taxonomy/
```

The biological/scientific projection follows eight downward transitions beneath a kingdom:

```text
KINGDOM_PHYLUM
PHYLUM_CLASS
CLASS_ORDER
ORDER_FAMILY
FAMILY_GENUS
GENUS_SPECIES
SPECIES_TYPE
TYPE_NAME
```

That gives the requested geometric target of `25^8 = 152,587,890,625` possible leaf paths per kingdom. The complete geometric tree is much larger than the storage budget, so the builder expands breadth-first and stops near the 35 GiB SQLite ceiling.

Taxa themselves live in `TAXON`. Two- and three-word traits and phenotypes are normalized in `DESCRIPTOR` and attached to any rank through `TAXON_DESCRIPTOR`, with explicit `present`, `absent`, and `variable` states. Lower-rank statements override inherited higher-rank statements.

Descriptors are added only when semantically new relative to effective local and inherited descriptors. This avoids repeatedly storing facts that already became true at a higher rank.

Current scientific hierarchy is discovered from NCBI Taxonomy. When a real source parent has fewer than 25 suitable children, the builder can fill unused slots with explicitly marked Anemone semantic branches derived from new descriptors. Those rows are tagged `origin_kind=semantic` and are never represented as official scientific taxa.

### Build toward the 35 GiB ceiling

```bash
python workbench/background3/sqlite_taxonomy/populate_taxonomy.py --budget-gib 35
```

The population command is resumable. It caches the current NCBI taxonomy, indexes Anemone's existing encyclopedia data, discovers current kingdom records, fills the adjacent-rank tables, adds descriptor assignments, and checkpoints its build queue.

### Inspect discovered kingdoms

```bash
python workbench/background3/sqlite_taxonomy/ncbi_source.py build
python workbench/background3/sqlite_taxonomy/ncbi_source.py kingdoms
```

### Fast offline structural test

```bash
python workbench/background3/sqlite_taxonomy/smoke_test.py
```

### Inspect the generated database

```bash
python workbench/background3/sqlite_taxonomy/taxonomy_db.py status
```

See `sqlite_taxonomy/README.md` for the complete layout, source/semantic distinction, and loader API.

## Live JX browser AI

The live frontend is under:

```text
workbench/background3/browser_ai/
```

It is a JX Book with canonical `home`, `explore`, `ask`, and `compare` leaves compiled to PASM/browser. PHP exposes the SQLite taxonomy as a live streaming API; the browser renders answer chunks, lineage, inherited descriptor evidence, explicit absences/variation, search results, and child branches as they arrive.

Build browser-mode JX:

```bash
export JX_ROOT=/path/to/dompipe/jx
php workbench/background3/browser_ai/build.php
```

Run the frontend:

```bash
cd workbench/background3/browser_ai
php -S 127.0.0.1:8787
```

Then open `http://127.0.0.1:8787/`.

If the large SQLite taxonomy has not been generated yet, the frontend uses a small built-in Animalia/wolf lineage so the AI-style interaction can be exercised immediately. It switches to the real taxonomy automatically when the database is present.

See `browser_ai/README.md` for the browser/JX/API architecture and endpoint contract.

## Archive

The original bundle is stored losslessly in base64 parts under `archive/` because the connected GitHub file writer accepts UTF-8 text rather than arbitrary binary bytes.

Reconstruct the exact ZIP with:

```bash
python workbench/background3/rebuild_archive.py
```

Expected output:

```text
workbench/background3/anemone_background_3word.zip
```

Expected SHA-256:

```text
75757f40dcffbbe41ff6204c8895b64a322381d2d079db2086e5b6db5adf235b
```

The archive contains the initial three-word taxonomy/fact background, connector seed families, grep/byte-index lookup tooling, schema, validator, and dictionary/encyclopedia converter.

The workbench is developed on `anemone-store`; `main` remains untouched.
