# Anemone SQLite Taxonomy

This is the staging format for the large Background3 taxonomy corpus.

## Rank tables

The hierarchy is stored as adjacent-rank tables:

```text
KINGDOM_PHYLUM
PHYLUM_FAMILY
FAMILY_ORDER
ORDER_GENUS
GENUS_SPECIES
SPECIES_TYPE
TYPE_NAME
```

Every relationship row links two normalized `TAXON` rows. Each parent is stored in pages of 25 children using `page_no` and `slot_no`, so a real taxon with more than 25 known children can continue on the next page without changing the table design.

## Descriptors at every level

Traits and phenotypes do not live inside the relationship tables. They are normalized once in `DESCRIPTOR` and attached to any rank through `TAXON_DESCRIPTOR`.

Each descriptor is exactly 2 or 3 words and has:

- `kind`: `trait` or `phenotype`
- `state`: `present`, `absent`, or `variable`
- `inheritable`: whether descendants inherit it
- `confidence`
- optional source metadata

A descriptor attached to a kingdom, phylum, family, order, genus, species, type, or name can therefore become part of a descendant's effective description without being copied into every descendant row.

The nearest explicit descriptor wins. For example, if Mammalia says `hair covered = present` and a lower taxon explicitly marks `hair covered = absent`, the lower statement overrides the inherited one.

## Logical conditionals

`TAXON_CONDITION`, `CONDITION_TERM`, and `CONDITION_EFFECT` store conditional knowledge.

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

This is intended for queries such as A + B + C. A candidate can report:

```text
A: present
B: absent
C: present
```

instead of merely failing the query because B is missing.

## 35 GiB ceiling

`taxonomy_db.py` initializes the database with a SQLite `max_page_count` corresponding to a 35 GiB main database by default. With the default 4096-byte page size this is 9,175,040 pages.

Initialize:

```bash
python workbench/background3/sqlite_taxonomy/taxonomy_db.py init
```

Inspect size and page budget:

```bash
python workbench/background3/sqlite_taxonomy/taxonomy_db.py status
```

Use another ceiling when testing:

```bash
python workbench/background3/sqlite_taxonomy/taxonomy_db.py \
  --db /tmp/anemone-test.sqlite3 \
  --budget-gib 0.1 \
  init
```

The generated `.sqlite3`, `-wal`, and `-shm` files are runtime artifacts and should not be committed to Git.

## Python API

`taxonomy_db.py` exposes helpers for loaders and future encyclopedia builders:

```python
from taxonomy_db import (
    init_db,
    upsert_taxon,
    add_child,
    link_taxa,
    set_descriptor,
    effective_descriptors,
    compare_requested,
)
```

A loader should add the actual taxonomic relationship first, then attach descriptors at the highest rank where each fact becomes true. That minimizes duplication and makes inheritance useful.
