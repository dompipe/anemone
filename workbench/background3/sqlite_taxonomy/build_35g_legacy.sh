#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
DB_PATH="${ANEMONE_TAXONOMY_DB:-workbench/background3/sqlite_taxonomy/anemone_taxonomy.sqlite3}"
BUDGET_GIB="${ANEMONE_TAXONOMY_GIB:-35}"
DESCRIPTORS_PER_NODE="${ANEMONE_DESCRIPTORS_PER_NODE:-10}"
SEMANTIC_DESCRIPTORS_PER_CHILD="${ANEMONE_SEMANTIC_DESCRIPTORS_PER_CHILD:-4}"

exec "$PYTHON_BIN" workbench/background3/sqlite_taxonomy/populate_taxonomy.py \
  --db "$DB_PATH" \
  --budget-gib "$BUDGET_GIB" \
  --descriptors-per-node "$DESCRIPTORS_PER_NODE" \
  --semantic-descriptors-per-child "$SEMANTIC_DESCRIPTORS_PER_CHILD" \
  "$@"
