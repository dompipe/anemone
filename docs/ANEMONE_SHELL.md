# Anemone Shell

The Anemone shell is the human-facing command layer for the `anemone-store` branch.
It does **not** replace the application runtime. PHP remains the application/API
boundary, and work that needs the runtime is dispatched through that boundary to JX.

## Start it

```bash
python anemone.py
```

That opens:

```text
Anemone shell
3-word background + taxonomy + PHP/JX dispatch boundary
anemone>
```

You can also use one-shot commands:

```bash
python anemone.py lookup gravity
python anemone.py taxonomy gravity
python anemone.py facts gravity
python anemone.py connector causes
python anemone.py bridge gravity velocity --depth 4
```

## Exact 3-word facts

Anemone's semantic unit remains:

```text
[A relation B]
```

A valid chain overlaps on the hinge:

```text
[gravity causes acceleration]
[acceleration changes velocity]
```

Validate an explicit chain:

```bash
python anemone.py chain \
  "gravity causes acceleration" \
  "acceleration changes velocity"
```

The shell rejects a chain when the prior fact's last semantic token is not the next
fact's first semantic token.

## Bridge search

`bridge` searches the existing fact graph for overlapping exact 3-word links.

```bash
python anemone.py bridge gravity velocity --depth 4
```

Example shape:

```text
bridge 1:
  [gravity causes acceleration]
  [acceleration changes velocity]
```

The search uses both ordinary `facts` and `taxonomy_facts`, so a bridge can move
through knowledge and taxonomy with the same hinge rule.

## Taxonomy

```bash
python anemone.py taxonomy gravity
```

The shell prints the current rank path:

```text
Kingdom -> Phylum -> Family -> Order -> Genus -> Species -> Type -> Name
```

and the normalized `belongs` facts that encode the same path.

## Connectors and thesaurus variants

```bash
python anemone.py connector causes
```

This reads `data/background3/connector_seeds.jsonl` and shows the stable semantic
relation together with its non-vanilla rhetorical variants. The semantic relation
stays canonical even when generated language uses a variant.

## Background maintenance

```bash
python anemone.py build
python anemone.py index
python anemone.py validate
```

- `build` runs the background builder against the repository.
- `index` rebuilds `data/background3/index.tsv` using byte offsets.
- `validate` rejects malformed facts and broken taxonomy hinges.

`tools/background3/build_index.py` accepts an optional background folder, so the
shell's `--background` flag remains usable for alternate corpora.

## PHP/JX dispatch boundary

The shell deliberately does not invent a second application runtime. To send work
into the application stack, configure the PHP API endpoint:

```bash
export ANEMONE_API_URL="https://example.com/api/anemone.php"
```

If the route uses bearer authentication:

```bash
export ANEMONE_API_TOKEN="..."
```

Then:

```bash
python anemone.py dispatch "evaluate this request"
```

The shell POSTs JSON shaped as:

```json
{
  "op": "anemone.shell",
  "prompt": "evaluate this request",
  "source": "anemone-shell"
}
```

The PHP route remains responsible for deciding how that work reaches the persistent
JX daemon. `dispatch` stays disabled when `ANEMONE_API_URL` is not configured rather
than silently bypassing PHP and creating a parallel path.

## Status

```bash
python anemone.py status
```

This reports:

- repository/background location
- byte-offset index readiness
- `rg` availability for lookup fallback
- configured PHP API endpoint
- JX executable/config visibility
- loaded background manifest

## Legacy conversation path

The previous `eng1neer` response path is still reachable:

```bash
python anemone.py ask "What is gravity?"
```

Inside the interactive shell, bare text is treated as `ask ...`, so the shell adds
structured commands without removing the existing conversational entry point.
