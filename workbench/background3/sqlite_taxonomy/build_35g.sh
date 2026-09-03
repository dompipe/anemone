#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
STORE_PATH="${ANEMONE_TAXONOMY_STORE:-workbench/background3/sqlite_taxonomy/anemone_taxonomy.mmap}"
BUDGET_GIB="${ANEMONE_TAXONOMY_GIB:-35}"
MMAP_GIB="${ANEMONE_TAXONOMY_MMAP_GIB:-4}"
DESCRIPTORS_PER_NODE="${ANEMONE_DESCRIPTORS_PER_NODE:-10}"
SEMANTIC_DESCRIPTORS_PER_CHILD="${ANEMONE_SEMANTIC_DESCRIPTORS_PER_CHILD:-4}"
COMMIT_EVERY="${ANEMONE_COMMIT_EVERY:-1000}"

exec "$PYTHON_BIN" workbench/background3/sqlite_taxonomy/populate_mmap_store.py \
  --store "$STORE_PATH" \
  --budget-gib "$BUDGET_GIB" \
  --mmap-gib "$MMAP_GIB" \
  --descriptors-per-node "$DESCRIPTORS_PER_NODE" \
  --semantic-descriptors-per-child "$SEMANTIC_DESCRIPTORS_PER_CHILD" \
  --commit-every "$COMMIT_EVERY" \
  "$@"
