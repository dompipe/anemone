#!/usr/bin/env python3
"""Small stdin/stdout bridge from the browser PHP boundary to Anemone's answer engine."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"invalid request: {exc}"}))
        return 2

    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        print(json.dumps({"ok": False, "error": "prompt required"}))
        return 2

    captured_out = io.StringIO()
    captured_err = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured_out), contextlib.redirect_stderr(captured_err):
            # word_freq.txt is generated from the whole readable Anemone corpus,
            # plus a sibling/explicit CNGN checkout when available.
            from word_freq_runtime import ensure_word_freq
            word_freq_path = ensure_word_freq(ROOT)

            from eng1neer import respond_subject_specific
            reply = respond_subject_specific(
                prompt,
                assoc_path=str(ROOT / "thesaurus_assoc.json"),
                data_dir=str(ROOT / "data"),
            )
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "diagnostic": (captured_err.getvalue() or captured_out.getvalue())[-4000:],
        }, ensure_ascii=False))
        return 1

    print(json.dumps({
        "ok": True,
        "reply": str(reply),
        "engine": "eng1neer.respond_subject_specific",
        "word_freq": str(word_freq_path),
        "diagnostic": (captured_err.getvalue() or captured_out.getvalue())[-4000:],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
