# Anemone background3

This is the working semantic background for the `anemone-store` branch.

## Core rule

Every normalized assertion is exactly three semantic tokens:

`[A relation B]`

Chains overlap on the hinge:

`[A relation B] -> [B relation C]`

Multiword concepts use underscores so they remain one semantic token.

## Taxonomy

`Kingdom -> Phylum -> Family -> Order -> Genus -> Species -> Type -> Name`

Taxonomy paths are also represented as three-token facts, for example:

`gravity belongs force_model`
`force_model belongs newtonian_gravity`
`newtonian_gravity belongs gravitation`
`gravitation belongs fundamental_interaction`
`fundamental_interaction belongs interaction`
`interaction belongs physics`
`physics belongs science`

Traits belong to the second-order layer of the taxonomy level where they first become valid and are inherited downward unless specialized.

## Files

- `science_facts.jsonl` - starter three-word fact corpus across physics, chemistry, biology, astronomy, earth science, mathematics, Locke/epistemology and rhetoric.
- `connector_seeds.jsonl` - stable semantic connectors plus non-vanilla rhetorical thesaurus variants.
- `taxonomy/` - curated concept paths and formulas.
- `taxonomy_rules.json` - conservative rules used when classifying dictionary/encyclopedia material.
- `schema.json` - normalized record structure.
- `manifest.json` - corpus metadata.

## Anemone shell

The branch now exposes the background through the main Anemone entry point:

```bash
python anemone.py
```

Useful one-shot commands:

```bash
python anemone.py lookup gravity
python anemone.py taxonomy gravity
python anemone.py facts gravity
python anemone.py connector causes
python anemone.py bridge gravity velocity --depth 4
python anemone.py chain "gravity causes acceleration" "acceleration changes velocity"
python anemone.py status
```

See `docs/ANEMONE_SHELL.md` for the complete command surface and the PHP/JX dispatch boundary.

## Build the large background

The repository already contains `data/definitions.json` and `data/wikipedia_defs.json`. Convert those into grep-friendly JSONL without changing the original files:

```bash
python tools/background3/build_background.py --repo .
```

or through the shell:

```bash
python anemone.py build
```

Install `ijson` for streaming conversion of the large JSON files:

```bash
python -m pip install ijson
```

## Lookup

The low-level lookup remains available:

```bash
python tools/background3/runtime_lookup.py gravity
```

The runtime uses `index.tsv` when available and falls back to `rg -n` over JSONL, parsing only matching records.

Build the byte-offset index directly or through the shell:

```bash
python tools/background3/build_index.py data/background3
python anemone.py index
```

## Validate

```bash
python tools/background3/validate_background.py data/background3
python anemone.py validate
```

The validator rejects facts that are not exact three-token units and checks taxonomy hinge continuity.
