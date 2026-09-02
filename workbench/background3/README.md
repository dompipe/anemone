# Anemone Background 3-Word Workbench

This directory is the staging area for the replacement Anemone semantic background on the `anemone-store` branch.

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

We will use this directory as the integration workbench and leave `main` untouched while developing on `anemone-store`.
