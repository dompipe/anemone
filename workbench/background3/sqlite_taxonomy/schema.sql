PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA temp_store = MEMORY;

-- Anemone taxonomy database.
-- Relationship tables are deliberately named by adjacent ranks.
-- Each parent/page is limited to 25 direct children.

CREATE TABLE IF NOT EXISTS TAXON (
    taxon_id        INTEGER PRIMARY KEY,
    rank            TEXT NOT NULL CHECK (rank IN (
                        'kingdom','phylum','family','order',
                        'genus','species','type','name'
                    )),
    canonical_name  TEXT NOT NULL,
    common_name     TEXT,
    scientific_name TEXT,
    source          TEXT,
    source_ref      TEXT,
    UNIQUE(rank, canonical_name)
);

CREATE INDEX IF NOT EXISTS idx_taxon_rank_name
ON TAXON(rank, canonical_name);

CREATE TABLE IF NOT EXISTS KINGDOM_PHYLUM (
    kingdom_id INTEGER NOT NULL REFERENCES TAXON(taxon_id),
    phylum_id  INTEGER NOT NULL REFERENCES TAXON(taxon_id),
    page_no    INTEGER NOT NULL DEFAULT 0 CHECK(page_no >= 0),
    slot_no    INTEGER NOT NULL CHECK(slot_no BETWEEN 1 AND 25),
    PRIMARY KEY (kingdom_id, phylum_id),
    UNIQUE (kingdom_id, page_no, slot_no)
);

CREATE TABLE IF NOT EXISTS PHYLUM_FAMILY (
    phylum_id INTEGER NOT NULL REFERENCES TAXON(taxon_id),
    family_id INTEGER NOT NULL REFERENCES TAXON(taxon_id),
    page_no   INTEGER NOT NULL DEFAULT 0 CHECK(page_no >= 0),
    slot_no   INTEGER NOT NULL CHECK(slot_no BETWEEN 1 AND 25),
    PRIMARY KEY (phylum_id, family_id),
    UNIQUE (phylum_id, page_no, slot_no)
);

CREATE TABLE IF NOT EXISTS FAMILY_ORDER (
    family_id INTEGER NOT NULL REFERENCES TAXON(taxon_id),
    order_id  INTEGER NOT NULL REFERENCES TAXON(taxon_id),
    page_no   INTEGER NOT NULL DEFAULT 0 CHECK(page_no >= 0),
    slot_no   INTEGER NOT NULL CHECK(slot_no BETWEEN 1 AND 25),
    PRIMARY KEY (family_id, order_id),
    UNIQUE (family_id, page_no, slot_no)
);

CREATE TABLE IF NOT EXISTS ORDER_GENUS (
    order_id INTEGER NOT NULL REFERENCES TAXON(taxon_id),
    genus_id INTEGER NOT NULL REFERENCES TAXON(taxon_id),
    page_no  INTEGER NOT NULL DEFAULT 0 CHECK(page_no >= 0),
    slot_no  INTEGER NOT NULL CHECK(slot_no BETWEEN 1 AND 25),
    PRIMARY KEY (order_id, genus_id),
    UNIQUE (order_id, page_no, slot_no)
);

CREATE TABLE IF NOT EXISTS GENUS_SPECIES (
    genus_id   INTEGER NOT NULL REFERENCES TAXON(taxon_id),
    species_id INTEGER NOT NULL REFERENCES TAXON(taxon_id),
    page_no    INTEGER NOT NULL DEFAULT 0 CHECK(page_no >= 0),
    slot_no    INTEGER NOT NULL CHECK(slot_no BETWEEN 1 AND 25),
    PRIMARY KEY (genus_id, species_id),
    UNIQUE (genus_id, page_no, slot_no)
);

CREATE TABLE IF NOT EXISTS SPECIES_TYPE (
    species_id INTEGER NOT NULL REFERENCES TAXON(taxon_id),
    type_id    INTEGER NOT NULL REFERENCES TAXON(taxon_id),
    page_no    INTEGER NOT NULL DEFAULT 0 CHECK(page_no >= 0),
    slot_no    INTEGER NOT NULL CHECK(slot_no BETWEEN 1 AND 25),
    PRIMARY KEY (species_id, type_id),
    UNIQUE (species_id, page_no, slot_no)
);

CREATE TABLE IF NOT EXISTS TYPE_NAME (
    type_id INTEGER NOT NULL REFERENCES TAXON(taxon_id),
    name_id INTEGER NOT NULL REFERENCES TAXON(taxon_id),
    page_no INTEGER NOT NULL DEFAULT 0 CHECK(page_no >= 0),
    slot_no INTEGER NOT NULL CHECK(slot_no BETWEEN 1 AND 25),
    PRIMARY KEY (type_id, name_id),
    UNIQUE (type_id, page_no, slot_no)
);

-- Descriptors and phenotypes are normalized instead of copied into every
-- relationship row. descriptor_text is intentionally limited by the loader
-- to 2-3 semantic words.
CREATE TABLE IF NOT EXISTS DESCRIPTOR (
    descriptor_id   INTEGER PRIMARY KEY,
    descriptor_text TEXT NOT NULL UNIQUE,
    word_count      INTEGER NOT NULL CHECK(word_count BETWEEN 2 AND 3)
);

CREATE TABLE IF NOT EXISTS TAXON_DESCRIPTOR (
    taxon_id      INTEGER NOT NULL REFERENCES TAXON(taxon_id) ON DELETE CASCADE,
    descriptor_id INTEGER NOT NULL REFERENCES DESCRIPTOR(descriptor_id),
    kind          TEXT NOT NULL CHECK(kind IN ('trait','phenotype')),
    state         TEXT NOT NULL CHECK(state IN ('present','absent','variable')),
    inheritable   INTEGER NOT NULL DEFAULT 1 CHECK(inheritable IN (0,1)),
    confidence    REAL NOT NULL DEFAULT 1.0 CHECK(confidence >= 0.0 AND confidence <= 1.0),
    source        TEXT,
    source_ref    TEXT,
    PRIMARY KEY (taxon_id, descriptor_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_taxon_descriptor_taxon_state
ON TAXON_DESCRIPTOR(taxon_id, state, kind);

CREATE INDEX IF NOT EXISTS idx_taxon_descriptor_descriptor
ON TAXON_DESCRIPTOR(descriptor_id, state);

-- Conditional knowledge supports questions such as A+B+C where a candidate
-- has A and C but explicitly lacks B.
CREATE TABLE IF NOT EXISTS TAXON_CONDITION (
    condition_id INTEGER PRIMARY KEY,
    taxon_id     INTEGER NOT NULL REFERENCES TAXON(taxon_id) ON DELETE CASCADE,
    note         TEXT,
    source       TEXT,
    source_ref   TEXT
);

CREATE TABLE IF NOT EXISTS CONDITION_TERM (
    condition_id  INTEGER NOT NULL REFERENCES TAXON_CONDITION(condition_id) ON DELETE CASCADE,
    descriptor_id INTEGER NOT NULL REFERENCES DESCRIPTOR(descriptor_id),
    test          TEXT NOT NULL CHECK(test IN ('all','any','none')),
    PRIMARY KEY (condition_id, descriptor_id, test)
);

CREATE TABLE IF NOT EXISTS CONDITION_EFFECT (
    condition_id  INTEGER NOT NULL REFERENCES TAXON_CONDITION(condition_id) ON DELETE CASCADE,
    descriptor_id INTEGER NOT NULL REFERENCES DESCRIPTOR(descriptor_id),
    action        TEXT NOT NULL CHECK(action IN ('add_present','add_absent','add_variable','remove')),
    kind          TEXT NOT NULL DEFAULT 'trait' CHECK(kind IN ('trait','phenotype')),
    PRIMARY KEY (condition_id, descriptor_id, action, kind)
);

-- Optional aliases let the shell match ordinary language against canonical
-- taxonomy names without modifying the scientific hierarchy.
CREATE TABLE IF NOT EXISTS TAXON_ALIAS (
    alias          TEXT NOT NULL,
    taxon_id       INTEGER NOT NULL REFERENCES TAXON(taxon_id) ON DELETE CASCADE,
    alias_kind     TEXT NOT NULL DEFAULT 'common',
    PRIMARY KEY(alias, taxon_id)
);

CREATE INDEX IF NOT EXISTS idx_taxon_alias_alias ON TAXON_ALIAS(alias);

-- Views make traversal convenient while preserving separate rank tables.
CREATE VIEW IF NOT EXISTS TAXON_EDGE AS
SELECT kingdom_id AS parent_id, phylum_id AS child_id, 'KINGDOM_PHYLUM' AS edge_table, page_no, slot_no FROM KINGDOM_PHYLUM
UNION ALL
SELECT phylum_id, family_id, 'PHYLUM_FAMILY', page_no, slot_no FROM PHYLUM_FAMILY
UNION ALL
SELECT family_id, order_id, 'FAMILY_ORDER', page_no, slot_no FROM FAMILY_ORDER
UNION ALL
SELECT order_id, genus_id, 'ORDER_GENUS', page_no, slot_no FROM ORDER_GENUS
UNION ALL
SELECT genus_id, species_id, 'GENUS_SPECIES', page_no, slot_no FROM GENUS_SPECIES
UNION ALL
SELECT species_id, type_id, 'SPECIES_TYPE', page_no, slot_no FROM SPECIES_TYPE
UNION ALL
SELECT type_id, name_id, 'TYPE_NAME', page_no, slot_no FROM TYPE_NAME;

CREATE VIEW IF NOT EXISTS TAXON_DESCRIPTOR_TEXT AS
SELECT
    td.taxon_id,
    t.rank,
    t.canonical_name,
    d.descriptor_text,
    td.kind,
    td.state,
    td.inheritable,
    td.confidence,
    td.source,
    td.source_ref
FROM TAXON_DESCRIPTOR td
JOIN TAXON t ON t.taxon_id = td.taxon_id
JOIN DESCRIPTOR d ON d.descriptor_id = td.descriptor_id;
