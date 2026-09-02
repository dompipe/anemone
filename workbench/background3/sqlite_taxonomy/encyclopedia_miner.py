#!/usr/bin/env python3
"""Mine compact 2-3 word descriptors from Anemone's encyclopedia files.

This intentionally uses simple deterministic text heuristics instead of an LLM
so a 35-GiB build is reproducible and can run offline after source acquisition.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Iterator

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
CACHE_DIR = HERE / "cache"
INDEX_DB = CACHE_DIR / "encyclopedia_index.sqlite3"

DEFAULT_SOURCES = [
    REPO / "data" / "biology.json",
    REPO / "data" / "chemistry.json",
    REPO / "data" / "definitions.json",
    REPO / "data" / "wikipedia_defs_formulas_cleaned.json",
]

INDEX_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS ENTRY (
    entry_id    INTEGER PRIMARY KEY,
    term        TEXT NOT NULL COLLATE NOCASE,
    text        TEXT NOT NULL,
    source_file TEXT NOT NULL,
    UNIQUE(term, text, source_file)
);
CREATE INDEX IF NOT EXISTS idx_entry_term ON ENTRY(term COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS META (
    meta_key TEXT PRIMARY KEY,
    meta_value TEXT NOT NULL
);
"""

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
SENTENCE_RE = re.compile(r"(?<=[.!?;])\s+")
CUE_RE = re.compile(
    r"\b(characterized by|distinguished by|identified by|possess(?:es)?|"
    r"contain(?:s)?|include(?:s)?|have|has|with|bearing|covered (?:in|with)|"
    r"typically|usually|commonly|often|lack(?:s|ing)?|without)\b",
    re.I,
)

STOP = {
    "a","an","the","and","or","but","if","then","than","that","this","these",
    "those","of","to","in","on","for","from","by","with","without","as","at",
    "into","through","during","before","after","above","below","between","is",
    "are","was","were","be","been","being","it","its","their","they","them",
    "which","who","whose","can","may","might","will","would","could","should",
    "also","other","some","many","most","more","less","such","often","usually",
    "typically","generally","commonly","known","called","including","include",
}

BAD = {
    "species","genus","family","order","class","phylum","kingdom","organism",
    "organisms","group","groups","type","types","name","names","taxon","taxa",
    "found","used","known","called","include","includes","including",
}

PHENOTYPE_WORDS = {
    "body","bodies","wing","wings","leaf","leaves","root","roots","stem","stems",
    "bark","flower","flowers","seed","seeds","fruit","fruits","fur","hair","skin",
    "shell","shells","leg","legs","eye","eyes","beak","beaks","bill","bills",
    "fin","fins","tail","tails","horn","horns","scale","scales","feather",
    "feathers","color","colour","colored","coloured","pattern","shape","size",
    "length","height","teeth","tooth","claw","claws","hoof","hooves","spine",
    "spines","petal","petals","needle","needles","antenna","antennae","segment",
    "segments","membrane","wall","walls","coat","coating","pigment","pigmented",
}

NEGATIVE_CUES = {"lack", "lacks", "lacking", "without", "absent", "no"}
VARIABLE_CUES = {"variable", "vary", "varies", "sometimes", "may", "often"}


def normalize_term(term: str) -> str:
    return " ".join(term.strip().split()).lower()


def _iter_entries(obj, key_hint: str | None = None) -> Iterator[tuple[str, str]]:
    if isinstance(obj, dict):
        name = None
        for key in ("term", "name", "title", "word", "subject"):
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                name = value.strip()
                break
        for key in ("definition", "description", "summary", "text", "content"):
            value = obj.get(key)
            if name and isinstance(value, str) and len(value.strip()) >= 24:
                yield name, value.strip()
        for key, value in obj.items():
            if isinstance(value, str):
                if len(value.strip()) >= 24 and key.lower() not in {
                    "definition","description","summary","text","content"
                }:
                    yield str(key), value.strip()
            elif isinstance(value, (dict, list)):
                yield from _iter_entries(value, str(key))
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_entries(item, key_hint)
    elif isinstance(obj, str) and key_hint and len(obj.strip()) >= 24:
        yield key_hint, obj.strip()


def build_index(
    db_path: Path = INDEX_DB,
    sources: list[Path] | None = None,
    *,
    rebuild: bool = False,
) -> Path:
    sources = sources or DEFAULT_SOURCES
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if rebuild and db_path.exists():
        db_path.unlink()
    db = sqlite3.connect(str(db_path))
    db.executescript(INDEX_SCHEMA)

    for source in sources:
        if not source.exists():
            continue
        marker = f"loaded:{source.resolve()}"
        if db.execute("SELECT 1 FROM META WHERE meta_key=?", (marker,)).fetchone():
            continue
        try:
            with source.open("r", encoding="utf-8", errors="replace") as fh:
                obj = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        batch = []
        seen = set()
        for term, text in _iter_entries(obj):
            term_n = normalize_term(term)
            if not term_n or len(term_n) > 240:
                continue
            key = (term_n, text[:300])
            if key in seen:
                continue
            seen.add(key)
            batch.append((term_n, text, source.name))
            if len(batch) >= 5000:
                db.executemany(
                    "INSERT OR IGNORE INTO ENTRY(term,text,source_file) VALUES(?,?,?)",
                    batch,
                )
                batch.clear()
        if batch:
            db.executemany(
                "INSERT OR IGNORE INTO ENTRY(term,text,source_file) VALUES(?,?,?)",
                batch,
            )
        db.execute(
            "INSERT OR REPLACE INTO META(meta_key,meta_value) VALUES(?,?)",
            (marker, "1"),
        )
        db.commit()

    db.execute("PRAGMA optimize")
    db.close()
    return db_path


def _phrase_state(sentence: str, phrase_start: int) -> str:
    before = sentence[:phrase_start].lower()
    recent = WORD_RE.findall(before)[-5:]
    if any(word in NEGATIVE_CUES for word in recent):
        return "absent"
    if any(word in VARIABLE_CUES for word in recent):
        return "variable"
    return "present"


def _valid_phrase(words: list[str], taxon_tokens: set[str]) -> bool:
    if not 2 <= len(words) <= 3:
        return False
    lower = [w.lower() for w in words]
    if lower[0] in STOP or lower[-1] in STOP:
        return False
    if all(w in STOP or w in BAD for w in lower):
        return False
    if sum(1 for w in lower if w in STOP) > 1:
        return False
    if set(lower).issubset(taxon_tokens):
        return False
    if any(len(w) < 2 for w in lower):
        return False
    return True


def extract_descriptors(
    text: str,
    *,
    taxon_name: str = "",
    limit: int = 12,
) -> list[dict]:
    taxon_tokens = {w.lower() for w in WORD_RE.findall(taxon_name)}
    candidates: dict[str, dict] = {}
    counts = Counter()

    for sentence in SENTENCE_RE.split(text):
        sentence = " ".join(sentence.split())
        if len(sentence) < 20:
            continue
        words = WORD_RE.findall(sentence)
        if len(words) < 3:
            continue

        cue_positions = [m.end() for m in CUE_RE.finditer(sentence)]

        for size in (2, 3):
            for i in range(0, len(words) - size + 1):
                phrase_words = words[i:i + size]
                if not _valid_phrase(phrase_words, taxon_tokens):
                    continue
                phrase = " ".join(w.lower() for w in phrase_words)
                if any(w in BAD for w in phrase.split()) and size == 2:
                    continue

                char_pos = sentence.lower().find(phrase_words[0].lower())
                cue_bonus = 0.0
                if cue_positions:
                    distance = min(abs(char_pos - p) for p in cue_positions)
                    if distance <= 80:
                        cue_bonus = 0.35
                    elif distance <= 160:
                        cue_bonus = 0.15

                phenotype = any(w in PHENOTYPE_WORDS for w in phrase.split())
                score = 0.35 + cue_bonus + (0.15 if phenotype else 0.0)
                if size == 3:
                    score += 0.05
                state = _phrase_state(sentence, max(char_pos, 0))
                counts[phrase] += 1

                old = candidates.get(phrase)
                if old is None or score > old["score"]:
                    candidates[phrase] = {
                        "descriptor": phrase,
                        "kind": "phenotype" if phenotype else "trait",
                        "state": state,
                        "score": min(score, 0.95),
                        "sentence": sentence[:500],
                    }

    ranked = []
    for phrase, item in candidates.items():
        frequency_bonus = min(0.15, 0.03 * (counts[phrase] - 1))
        item = dict(item)
        item["score"] = min(0.99, item["score"] + frequency_bonus)
        ranked.append(item)
    ranked.sort(key=lambda x: (-x["score"], x["descriptor"]))
    return ranked[:limit]


class EncyclopediaMiner:
    def __init__(self, db_path: Path = INDEX_DB):
        self.db_path = Path(db_path)
        self.db = sqlite3.connect(str(db_path))
        self.db.row_factory = sqlite3.Row

    def close(self) -> None:
        self.db.close()

    def texts_for(self, *terms: str, limit: int = 8) -> list[dict]:
        out = []
        seen = set()
        for term in terms:
            if not term:
                continue
            rows = self.db.execute(
                """SELECT term,text,source_file FROM ENTRY
                   WHERE term=? COLLATE NOCASE
                   ORDER BY length(text) DESC LIMIT ?""",
                (normalize_term(term), limit),
            ).fetchall()
            for row in rows:
                key = (row["source_file"], row["text"][:300])
                if key in seen:
                    continue
                seen.add(key)
                out.append(dict(row))
        return out[:limit]

    def descriptors_for(
        self,
        taxon_name: str,
        *aliases: str,
        limit: int = 12,
    ) -> list[dict]:
        texts = self.texts_for(taxon_name, *aliases, limit=8)
        merged: dict[str, dict] = {}
        for entry in texts:
            for item in extract_descriptors(
                entry["text"], taxon_name=taxon_name, limit=limit * 2
            ):
                item = dict(item)
                item["source_file"] = entry["source_file"]
                old = merged.get(item["descriptor"])
                if old is None or item["score"] > old["score"]:
                    merged[item["descriptor"]] = item
        ranked = sorted(
            merged.values(),
            key=lambda x: (-x["score"], x["descriptor"]),
        )
        return ranked[:limit]


def cli() -> int:
    parser = argparse.ArgumentParser(description="Build/query Anemone encyclopedia descriptor index")
    parser.add_argument("--db", type=Path, default=INDEX_DB)
    sub = parser.add_subparsers(dest="command", required=True)
    p_build = sub.add_parser("build")
    p_build.add_argument("--rebuild", action="store_true")
    p_extract = sub.add_parser("extract")
    p_extract.add_argument("term")
    p_extract.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()

    if args.command == "build":
        build_index(args.db, rebuild=args.rebuild)
        print(args.db)
        return 0

    if not args.db.exists():
        build_index(args.db)
    miner = EncyclopediaMiner(args.db)
    try:
        for item in miner.descriptors_for(args.term, limit=args.limit):
            print(
                f"{item['kind']}\t{item['state']}\t"
                f"{item['score']:.2f}\t{item['descriptor']}"
            )
    finally:
        miner.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
