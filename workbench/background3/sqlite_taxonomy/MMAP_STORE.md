# Anemone taxonomy v3: sharded mmap store

The v3 store replaces the single growing `anemone_taxonomy.sqlite3` file as the
default 35-GiB build target.

## Physical rule

Logical taxonomy remains:

```text
kingdom -> phylum -> class -> order -> family -> genus -> species -> type -> name
```

Physical storage is split by rank and transition:

```text
anemone_taxonomy.mmap/
  store.json
  catalog.sqlite3

  rank_00_kingdom.sqlite3
  rank_01_phylum.sqlite3
  rank_02_class.sqlite3
  rank_03_order.sqlite3
  rank_04_family.sqlite3
  rank_05_genus.sqlite3
  rank_06_species.sqlite3
  rank_07_type.sqlite3
  rank_08_name.sqlite3

  edge_00_kingdom_phylum.sqlite3
  edge_01_phylum_class.sqlite3
  edge_02_class_order.sqlite3
  edge_03_order_family.sqlite3
  edge_04_family_genus.sqlite3
  edge_05_genus_species.sqlite3
  edge_06_species_type.sqlite3
  edge_07_type_name.sqlite3
```

That is 18 SQLite databases: one catalog, nine rank shards, and eight transition
shards.

## Constraint index one level below the tables

Every transition shard has two primary structures:

```text
EDGE
  parent_id
  child_id
  page_no
  slot_no

CHILD_CONSTRAINT
  parent_id
  child_id
  constraint_type
  constraint_key
  state
  text_value
  num_value
  inheritable
  confidence
  novelty_score
  origin_taxon_id
  source
  source_ref
```

`CHILD_CONSTRAINT` is the indexed layer immediately below the child rank table.
It contains effective constraints for that child at that transition.

The important change is that inheritance is materialized **when the child is
written**. A descendant query does not recursively walk ancestors to learn that
a trait is inherited. The inherited constraint already exists beside the edge.
A lower-rank explicit descriptor replaces the projected constraint with the same
constraint key, preserving the lower-level override.

Useful indexes include:

```text
(parent_id, page_no, slot_no, child_id)
(parent_id, constraint_type, constraint_key, state, child_id)
(constraint_type, constraint_key, state, text_value, child_id)
(child_id, constraint_type, constraint_key)
```

So a request like "children of X with hair covered present" filters in the edge
shard before fetching full child records.

## Address-space IDs

A taxon id is a 64-bit address:

```text
high 8 bits   = rank code
low 56 bits   = local row id inside that rank shard
```

Examples of ownership are therefore known without a lookup:

```text
rank code 1 -> kingdom shard
rank code 2 -> phylum shard
...
rank code 9 -> name shard
```

The browser and Python runtime decode the id and open only the necessary shard.

## mmap behavior

Each database uses:

```text
page_size     32768
mmap_size     configurable, default 4 GiB maximum mapping per hot shard
temp_store    MEMORY
cache_size    ~128 MiB per hot connection
```

During bulk construction:

```text
journal_mode  OFF
synchronous   OFF
locking_mode  EXCLUSIVE
```

The store manifest assigns every shard a `max_page_count` ceiling. These are
virtual growth ceilings; the files are not eagerly filled with zeros. The
aggregate population loop also stops near the configured total byte budget.

For browser/read mode, shards reopen with WAL + NORMAL synchronization and mmap.

## Create the databases only

This creates the store geometry, schemas, indexes, ids, and shard ceilings. It
does **not** populate NCBI knowledge:

```bash
python3 workbench/background3/sqlite_taxonomy/mmap_store.py create \
  --store workbench/background3/sqlite_taxonomy/anemone_taxonomy.mmap \
  --budget-gib 35 \
  --mmap-gib 4
```

The result is immediately inspectable:

```bash
python3 workbench/background3/sqlite_taxonomy/mmap_store.py status \
  --store workbench/background3/sqlite_taxonomy/anemone_taxonomy.mmap
```

## Populate/resume

The normal build command now targets v3:

```bash
bash workbench/background3/sqlite_taxonomy/build_35g.sh
```

Environment overrides:

```text
ANEMONE_TAXONOMY_STORE
ANEMONE_TAXONOMY_GIB                 default 35
ANEMONE_TAXONOMY_MMAP_GIB            default 4
ANEMONE_DESCRIPTORS_PER_NODE          default 10
ANEMONE_SEMANTIC_DESCRIPTORS_PER_CHILD default 4
ANEMONE_COMMIT_EVERY                  default 1000
PYTHON_BIN                            default python3
```

The build queue remains resumable in `catalog.sqlite3`.

The old single-file builder remains available as:

```bash
bash workbench/background3/sqlite_taxonomy/build_35g_legacy.sh
```

## Browser

`browser_ai/api.php` automatically selects the v3 store when these exist:

```text
anemone_taxonomy.mmap/store.json
anemone_taxonomy.mmap/catalog.sqlite3
```

Otherwise it falls back to the old single-file API/demo behavior.

Ask-mode still uses the full Anemone answer engine; the mmap store serves
structured taxonomy Explore/Compare/context operations.

## Smoke test

```bash
cd workbench/background3/sqlite_taxonomy
python3 smoke_test_mmap.py
```

The smoke test verifies:

- 64-bit rank-address ids,
- three-rank lineage,
- write-time descriptor inheritance,
- lower-rank state override,
- constraint-filtered child lookup,
- all 18 physical shard definitions.
