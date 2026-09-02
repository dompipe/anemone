# Anemone SQLite Taxonomy Builder

This workbench builds the large descriptor-rich taxonomy used by `background3`.
The generated SQLite database is intentionally not committed to Git.

## Geometry

Each kingdom expands through eight downward transitions:

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

The target fan-out is 25 children per parent. That gives a geometric leaf
capacity of:

```text
25^8 = 152,587,890,625
```

paths beneath each kingdom. The complete geometric tree is not expected to fit
physically: SQLite enforces a 35 GiB hard main-database ceiling and the
population queue stops before that ceiling.

## Scientific versus semantic nodes

Current scientific hierarchy is imported from NCBI Taxonomy. NCBI source IDs,
source ranks, common names, and scientific names are retained.

When a source parent contains fewer than 25 suitable children, the remaining
slots can be filled with descriptor-defined semantic branches. These rows are
always stored with:

```text
origin_kind = semantic
source_rank = descriptor_cluster
source = Anemone semantic taxonomy
```

They are reasoning/classification nodes and must never be presented as official
scientific taxa.

Disable semantic filling with `--no-semantic-fill` when a strictly scientific
projection is wanted.

## Descriptors at every level

Traits and phenotypes are normalized once in `DESCRIPTOR` and attached through
`TAXON_DESCRIPTOR`.

Each descriptor is exactly 2 or 3 words, for example:

```text
warm blooded
hair covered
milk producing
compound eyes
dorsal nerve cord
needle leaves
fibrous roots
```

Each assignment records:

```text
kind: trait | phenotype
state: present | absent | variable
inheritable: 0 | 1
confidence: 0.0 .. 1.0
novelty_score: 0.0 .. 1.0
```

A phrase is attached only when it contributes new semantics relative to the
node's effective local and inherited descriptors. Lower levels inherit higher
level descriptors automatically, so repeated facts do not consume space.

The nearest explicit state wins. A lower taxon can therefore override an
inherited descriptor as absent or variable.

## Logical conditionals

`TAXON_CONDITION`, `CONDITION_TERM`, and `CONDITION_EFFECT` store conditional
knowledge.

Terms can require:

```text
all
any
none
```

Effects can:

```text
add_present
add_absent
add_variable
remove
```

This supports A+B+C queries where a candidate can explicitly report:

```text
A: present
B: absent
C: present
```

rather than merely failing because B did not match.

## Sources

`ncbi_source.py` downloads the current NCBI `new_taxdump` and builds a disposable
local source index in `cache/`. The kingdom list is discovered from that source
at build time instead of being permanently hard-coded.

`encyclopedia_miner.py` builds another disposable local index from Anemone's
existing encyclopedia files, including biology, chemistry, definitions, and
the cleaned Wikipedia definition corpus. It mines deterministic 2-3 word
traits and phenotypes without requiring an online language model during the
large population pass.

Grammar cue phrases such as `characterized by`, `have`, and `contains` guide
extraction but are prohibited from becoming descriptors themselves.

## 35 GiB ceiling

`taxonomy_db.py` initializes the database with SQLite `max_page_count`
corresponding to a 35 GiB main database by default. With the default 4096-byte
page size this is 9,175,040 pages.

The population loop also leaves a small amount of headroom before the hard
limit so transactions and checkpointing can finish cleanly.

## Build

From the repository root:

```bash
python workbench/background3/sqlite_taxonomy/populate_taxonomy.py --budget-gib 35
```

The first run will:

1. download/cache the current NCBI taxonomy dump;
2. build the local source taxonomy index;
3. index Anemone's encyclopedia data;
4. discover current kingdom records;
5. seed the kingdom rows;
6. expand breadth-first toward 25 children per parent;
7. use source taxonomy first;
8. fill sparse branches with explicitly semantic descriptor clusters;
9. add semantically new descriptors at every level;
10. checkpoint the build queue continuously;
11. stop near the 35 GiB hard ceiling.

The build is resumable. Re-running the same command continues pending work.

For a small test build:

```bash
python workbench/background3/sqlite_taxonomy/populate_taxonomy.py \
  --budget-gib 0.25 \
  --max-nodes 10000
```

For scientific rows only:

```bash
python workbench/background3/sqlite_taxonomy/populate_taxonomy.py \
  --budget-gib 35 \
  --no-semantic-fill
```

To list the current source kingdoms without building the main corpus:

```bash
python workbench/background3/sqlite_taxonomy/ncbi_source.py kingdoms
```

To inspect database size and counts:

```bash
python workbench/background3/sqlite_taxonomy/taxonomy_db.py status
```

## Smoke test

The smoke test is offline. It supplies only two fake scientific children per
source node and verifies that semantic filling reaches 25 slots, continues
downward, and preserves the 2-3 word descriptor constraint.

```bash
python workbench/background3/sqlite_taxonomy/smoke_test.py
```

## Generated files

The following are local build products and should not be committed:

```text
anemone_taxonomy.sqlite3
anemone_taxonomy.sqlite3-wal
anemone_taxonomy.sqlite3-shm
cache/new_taxdump.tar.gz
cache/ncbi_taxonomy_source.sqlite3*
cache/encyclopedia_index.sqlite3*
```
