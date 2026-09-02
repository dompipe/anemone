# Anemone Background 3-Word Workbench

This directory is the staging area for the replacement Anemone semantic background on the `anemone-store` branch.

## Canonical large-taxonomy format

The large taxonomy corpus now uses SQLite under:

```text
workbench/background3/sqlite_taxonomy/
```

The hierarchy is split into adjacent-rank tables:

```text
KINGDOM_PHYLUM
PHYLUM_FAMILY
FAMILY_ORDER
ORDER_GENUS
GENUS_SPECIES
SPECIES_TYPE
TYPE_NAME
```

Taxa themselves live in `TAXON`. Two- and three-word traits and phenotypes are normalized in `DESCRIPTOR` and attached to any rank through `TAXON_DESCRIPTOR`, with explicit `present`, `absent`, and `variable` states. Lower-rank statements override inherited higher-rank statements.

Children are arranged in 25-slot pages. The default main-database ceiling is 35 GiB and is enforced using SQLite's page-count limit.

Initialize the taxonomy store with:

```bash
python workbench/background3/sqlite_taxonomy/taxonomy_db.py init
```

Inspect its storage budget with:

```bash
python workbench/background3/sqlite_taxonomy/taxonomy_db.py status
```

See `sqlite_taxonomy/README.md` for the complete layout and loader API.

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
