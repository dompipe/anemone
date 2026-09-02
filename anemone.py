#!/usr/bin/env python3
"""Primary Anemone entry point.

Running without arguments opens the Anemone shell. Subcommands are forwarded to
`anemone_shell.py`, while bare text inside the shell keeps the legacy eng1neer
conversation path available.
"""

from pathlib import Path

from word_freq_runtime import ensure_word_freq

ensure_word_freq(Path(__file__).resolve().parent)

from anemone_shell import main


if __name__ == "__main__":
    raise SystemExit(main())
