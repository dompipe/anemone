# Anemone Taxonomy AI — JX browser frontend

This is the live browser surface for the Background3 SQLite taxonomy.

## What is JX here

The interface is a JX Book with four canonical leaves:

```text
home
explore
ask
compare
```

Each leaf is source `.jx`. `build.php` compiles those leaves with the current `dompipe/jx` compiler to PASM/browser and copies the JX browser VM into `build/runtime/`.

The visible browser is the host surface. PHP remains the application/API boundary and SQLite remains the durable taxonomy boundary.

```text
canonical .jx leaves
        |
      JX compiler
        |
  PASM/browser pages
        |
   browser JX VM
        |
   live host surface
        |
      api.php
        |
Anemone taxonomy SQLite
```

## Build JX browser mode

Set `JX_ROOT` to a checkout of `dompipe/jx`, or place `jx` beside `anemone`:

```bash
export JX_ROOT=/path/to/jx
php workbench/background3/browser_ai/build.php
```

This creates:

```text
build/browser/home.pasm
build/browser/explore.pasm
build/browser/ask.pasm
build/browser/compare.pasm
build/runtime/pasl-vm.js
build/manifest.json
```

The `build/` directory is generated output and is intentionally not the source of truth.

## Run it

From the browser frontend folder:

```bash
cd workbench/background3/browser_ai
php -S 127.0.0.1:8787
```

Open:

```text
http://127.0.0.1:8787/
```

To point at a different taxonomy file:

```bash
ANEMONE_TAXONOMY_DB=/absolute/path/anemone_taxonomy.sqlite3 \
php -S 127.0.0.1:8787
```

If the generated taxonomy database is not present, the API intentionally boots a small demo lineage (`Animalia → Chordata → Mammalia → Carnivora → Canidae → Canis → Canis lupus`) so the live UI can be tested immediately. As soon as the real database path exists, `bootstrap` reports `mode=live` and the interface switches to it without frontend changes.

## Live AI-style stream

`POST api.php?op=ask` returns `application/x-ndjson`. Events arrive as work is resolved:

```json
{"type":"status","label":"Searching taxonomy"}
{"type":"context","taxon":{},"lineage":[],"children":[]}
{"type":"status","label":"Resolving inherited traits"}
{"type":"chunk","text":"Canis lupus is indexed as species. "}
{"type":"evidence","descriptors":[]}
{"type":"done","taxon_id":123}
```

The browser does not wait for one large JSON response. It renders chunks as they arrive and updates lineage/descriptor evidence independently from prose.

## API operations

```text
GET  api.php?op=bootstrap
GET  api.php?op=search&q=wolf
GET  api.php?op=taxon&taxon_id=...
GET  api.php?op=children&taxon_id=...
POST api.php?op=compare
POST api.php?op=ask
```

`compare` takes:

```json
{
  "taxon_id": 123,
  "descriptors": ["hair covered", "retractile claws", "pack hunting"]
}
```

and returns explicit `present`, `absent`, `variable`, and `unknown` groups.

## Screen layout

### Left rail

- new conversation
- Ask / Explore / Compare JX leaves
- live taxon search
- kingdom list
- live corpus statistics

### Center

- AI-style conversation
- streamed answer chunks
- thinking/status line
- clickable child-taxon chips
- persistent prompt composer

### Right context

- active taxon and rank
- scientific/semantic origin badge
- complete loaded lineage
- inherited descriptor resolution
- present / absent / variable tabs
- up to 25 child nodes
- 35 GiB corpus meter
- active JX browser leaf/result/step count

## Important boundary

This frontend does not make JavaScript the Anemone reasoning runtime.

JavaScript is the browser host glue: DOM events, streaming fetch, and rendering. Canonical mode/state leaves are JX/PASM-browser. Taxonomy truth comes from SQLite through PHP. A persistent JX reasoning service can later sit behind `api.php?op=ask` while preserving the exact same NDJSON event contract and browser UI.
