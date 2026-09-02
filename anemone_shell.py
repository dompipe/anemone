#!/usr/bin/env python3
"""Anemone shell: human-facing CLI/REPL over background3 and the PHP/JX runtime boundary."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from typing import Dict, Iterator, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parent
BACKGROUND = ROOT / "data" / "background3"
TOOLS = ROOT / "tools" / "background3"
RANKS = ("kingdom", "phylum", "family", "order", "genus", "species", "type", "name")

try:
    from tools.background3.runtime_lookup import Background, slug
except ModuleNotFoundError:
    sys.path.insert(0, str(TOOLS))
    from runtime_lookup import Background, slug  # type: ignore


def _jsonl_files(folder: Path) -> Iterator[Path]:
    for path in sorted(folder.rglob("*.jsonl")):
        if path.name == "connector_seeds.jsonl":
            continue
        yield path


def _records(folder: Path) -> Iterator[dict]:
    for path in _jsonl_files(folder):
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict):
                        yield row
        except OSError:
            continue


def _fact_tuples(row: dict) -> Iterator[Tuple[str, str, str]]:
    for key in ("facts", "taxonomy_facts"):
        for fact in row.get(key) or ():
            if isinstance(fact, list) and len(fact) == 3:
                yield tuple(str(x) for x in fact)  # type: ignore[misc]


def _all_facts(folder: Path) -> Iterator[Tuple[str, str, str]]:
    seen = set()
    for row in _records(folder):
        for fact in _fact_tuples(row):
            if fact not in seen:
                seen.add(fact)
                yield fact


def _format_fact(fact: Sequence[str]) -> str:
    return f"[{fact[0]} {fact[1]} {fact[2]}]"


def _print_record(row: dict) -> None:
    print(row.get("name", "(unnamed)"))
    taxonomy = row.get("taxonomy") or {}
    if taxonomy:
        parts = [f"{rank}={taxonomy.get(rank)}" for rank in RANKS if taxonomy.get(rank)]
        print("  taxonomy: " + " -> ".join(parts))
    traits = row.get("traits") or {}
    if traits:
        print("  traits: " + ", ".join(f"{k}={v}" for k, v in sorted(traits.items())))
    for fact in row.get("facts") or ():
        if isinstance(fact, list) and len(fact) == 3:
            print("  fact: " + _format_fact(fact))
    for fact in row.get("taxonomy_facts") or ():
        if isinstance(fact, list) and len(fact) == 3:
            print("  tax:  " + _format_fact(fact))
    for formula in row.get("formulas") or ():
        print(f"  math: {formula}")


class AnemoneShell:
    def __init__(self, folder: Path = BACKGROUND):
        self.folder = folder
        self.background = Background(str(folder))

    def lookup(self, term: str) -> List[dict]:
        return self.background.get(term)

    def cmd_lookup(self, term: str, as_json: bool = False) -> int:
        rows = self.lookup(term)
        if as_json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            if not rows:
                print(f"no exact background record for: {slug(term)}")
                return 1
            for i, row in enumerate(rows):
                if i:
                    print()
                _print_record(row)
        return 0

    def cmd_facts(self, term: str, incoming: bool = False, limit: int = 50) -> int:
        key = slug(term)
        hits: List[Tuple[str, str, str]] = []
        for fact in _all_facts(self.folder):
            if fact[0] == key or (incoming and fact[2] == key):
                hits.append(fact)
                if len(hits) >= limit:
                    break
        if not hits:
            print(f"no facts found for: {key}")
            return 1
        for fact in hits:
            print(_format_fact(fact))
        return 0

    def cmd_taxonomy(self, term: str) -> int:
        rows = self.lookup(term)
        if not rows:
            print(f"no taxonomy record for: {slug(term)}")
            return 1
        shown = False
        for row in rows:
            taxonomy = row.get("taxonomy") or {}
            if taxonomy:
                shown = True
                print(row.get("name", slug(term)))
                for rank in RANKS:
                    value = taxonomy.get(rank)
                    if value:
                        print(f"  {rank:8} {value}")
            facts = row.get("taxonomy_facts") or ()
            if facts:
                print("  chain")
                for fact in facts:
                    if isinstance(fact, list) and len(fact) == 3:
                        print("    " + _format_fact(fact))
        return 0 if shown else 1

    def _connectors(self) -> List[dict]:
        path = self.folder / "connector_seeds.jsonl"
        out = []
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(row, dict):
                            out.append(row)
        except OSError:
            pass
        return out

    def cmd_connector(self, relation: str = "") -> int:
        key = slug(relation) if relation else ""
        rows = self._connectors()
        if key:
            rows = [
                row for row in rows
                if key in {
                    slug(row.get("relation", "")),
                    slug(row.get("seed", "")),
                    *(slug(v) for v in (row.get("variants") or ())),
                }
            ]
        if not rows:
            print(f"no connector found for: {relation}")
            return 1
        for row in rows:
            variants = ", ".join(str(v) for v in row.get("variants") or ())
            print(f"{row.get('relation')}: {variants}")
        return 0

    def cmd_bridge(self, start: str, target: str, max_depth: int = 4, max_results: int = 8) -> int:
        start_key, target_key = slug(start), slug(target)
        graph: Dict[str, List[Tuple[str, str, str]]] = {}
        for fact in _all_facts(self.folder):
            graph.setdefault(fact[0], []).append(fact)

        queue = deque([(start_key, [])])
        best_depth: Dict[str, int] = {start_key: 0}
        results: List[List[Tuple[str, str, str]]] = []

        while queue and len(results) < max_results:
            node, path = queue.popleft()
            if len(path) >= max_depth:
                continue
            for fact in graph.get(node, ()):
                nxt = fact[2]
                new_path = path + [fact]
                if nxt == target_key:
                    results.append(new_path)
                    if len(results) >= max_results:
                        break
                    continue
                depth = len(new_path)
                if depth < best_depth.get(nxt, max_depth + 1):
                    best_depth[nxt] = depth
                    queue.append((nxt, new_path))

        if not results:
            print(f"no overlapping 3-word bridge: {start_key} -> {target_key} (depth <= {max_depth})")
            return 1

        for n, path in enumerate(results, 1):
            print(f"bridge {n}:")
            for fact in path:
                print("  " + _format_fact(fact))
        return 0

    def cmd_chain(self, pieces: Sequence[str]) -> int:
        parsed: List[Tuple[str, str, str]] = []
        for piece in pieces:
            tokens = shlex.split(piece)
            if len(tokens) != 3:
                print(f"invalid fact (need exactly 3 semantic tokens): {piece}")
                return 2
            parsed.append(tuple(slug(t) for t in tokens))

        for i, fact in enumerate(parsed):
            print(_format_fact(fact))
            if i:
                prior = parsed[i - 1]
                if prior[2] != fact[0]:
                    print(f"hinge mismatch: {prior[2]} != {fact[0]}")
                    return 1
        print("chain: valid")
        return 0

    def cmd_status(self) -> int:
        manifest_path = self.folder / "manifest.json"
        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}

        api_url = os.getenv("ANEMONE_API_URL", "").strip()
        jx_cmd = os.getenv("ANEMONE_JX_CMD", "").strip()
        jx_bin = shutil.which("jx")

        print(f"repo:       {ROOT}")
        print(f"background: {self.folder} ({'ok' if self.folder.exists() else 'missing'})")
        print(f"index:      {'ready' if (self.folder / 'index.tsv').exists() else 'not built'}")
        print(f"rg:         {shutil.which('rg') or 'not found'}")
        print(f"php api:    {api_url or 'ANEMONE_API_URL not set'}")
        print(f"jx:         {jx_cmd or jx_bin or 'ANEMONE_JX_CMD not set / jx not on PATH'}")
        if manifest:
            version = manifest.get("version") or manifest.get("name") or "loaded"
            print(f"manifest:   {version}")
        return 0

    def cmd_tool(self, script: str, extra: Sequence[str] = ()) -> int:
        path = TOOLS / script
        if not path.exists():
            print(f"missing tool: {path}")
            return 2
        proc = subprocess.run([sys.executable, str(path), *extra], cwd=str(ROOT))
        return int(proc.returncode)

    def cmd_dispatch(self, prompt: str) -> int:
        """Dispatch through the configured PHP/API boundary; do not duplicate the app runtime here."""
        api_url = os.getenv("ANEMONE_API_URL", "").strip()
        if not api_url:
            print("ANEMONE_API_URL is not set; dispatch stays disabled rather than bypassing PHP routing.")
            return 2

        payload = json.dumps({"op": "anemone.shell", "prompt": prompt, "source": "anemone-shell"}).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        token = os.getenv("ANEMONE_API_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        req = urllib.request.Request(api_url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            print(f"dispatch HTTP {exc.code}: {body}")
            return 1
        except urllib.error.URLError as exc:
            print(f"dispatch failed: {exc.reason}")
            return 1

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            print(body)
        else:
            print(json.dumps(parsed, indent=2, ensure_ascii=False))
        return 0

    def cmd_ask(self, prompt: str) -> int:
        try:
            from eng1neer import respond_subject_specific
        except Exception as exc:
            print(f"eng1neer unavailable: {type(exc).__name__}: {exc}")
            return 2
        try:
            reply = respond_subject_specific(prompt)
        except Exception as exc:
            print(f"eng1neer error: {type(exc).__name__}: {exc}")
            return 1
        print(reply)
        return 0

    def execute(self, argv: Sequence[str]) -> int:
        if not argv:
            return 0
        cmd, *args = argv
        cmd = cmd.lower()

        if cmd in {"quit", "exit", "q"}:
            raise EOFError
        if cmd in {"help", "?"}:
            print(REPL_HELP)
            return 0
        if cmd in {"lookup", "show"}:
            if not args:
                print("usage: lookup TERM")
                return 2
            return self.cmd_lookup(" ".join(args))
        if cmd == "facts":
            if not args:
                print("usage: facts TERM")
                return 2
            return self.cmd_facts(" ".join(args))
        if cmd in {"tax", "taxonomy"}:
            if not args:
                print("usage: taxonomy TERM")
                return 2
            return self.cmd_taxonomy(" ".join(args))
        if cmd in {"connector", "connectors"}:
            return self.cmd_connector(" ".join(args))
        if cmd == "bridge":
            if len(args) < 2:
                print("usage: bridge START TARGET [DEPTH]")
                return 2
            depth = 4
            if len(args) >= 3 and args[-1].isdigit():
                depth = int(args.pop())
            return self.cmd_bridge(args[0], args[1], depth)
        if cmd == "chain":
            if len(args) < 2:
                print('usage: chain "a relation b" "b relation c"')
                return 2
            return self.cmd_chain(args)
        if cmd == "status":
            return self.cmd_status()
        if cmd == "validate":
            return self.cmd_tool("validate_background.py", [str(self.folder)])
        if cmd == "build":
            return self.cmd_tool("build_background.py", ["--repo", str(ROOT)])
        if cmd == "index":
            return self.cmd_tool("build_index.py", [str(self.folder)])
        if cmd == "dispatch":
            if not args:
                print("usage: dispatch PROMPT")
                return 2
            return self.cmd_dispatch(" ".join(args))
        if cmd == "ask":
            if not args:
                print("usage: ask PROMPT")
                return 2
            return self.cmd_ask(" ".join(args))

        return self.cmd_ask(" ".join(argv))

    def repl(self) -> int:
        print("Anemone shell")
        print("3-word background + taxonomy + PHP/JX dispatch boundary")
        print("type 'help' for commands; Ctrl-C/Ctrl-D or 'exit' to leave")
        while True:
            try:
                line = input("anemone> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not line:
                continue
            try:
                argv = shlex.split(line)
            except ValueError as exc:
                print(f"parse error: {exc}")
                continue
            try:
                self.execute(argv)
            except EOFError:
                return 0


REPL_HELP = """\
Commands
  lookup TERM                show exact background record
  facts TERM                 show outgoing 3-word facts
  taxonomy TERM              show taxonomy ranks and belongs-chain
  connector [RELATION]       show connector/thesaurus variants
  bridge START TARGET [N]    find overlapping 3-word paths (default depth 4)
  chain "A rel B" "B rel C"  validate exact 3-token hinge continuity
  status                     show background/index/API/JX readiness
  build                      build large background from source data
  index                      build byte-offset index.tsv
  validate                   validate 3-word facts and taxonomy hinges
  dispatch PROMPT            POST work through ANEMONE_API_URL (PHP/JX boundary)
  ask PROMPT                 use the existing eng1neer response path
  help                       show this help
  exit                       leave the shell

Bare text is treated as `ask ...`.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anemone",
        description="Anemone shell over the exact 3-word background and PHP/JX runtime boundary.",
    )
    parser.add_argument("--background", default=str(BACKGROUND), help="background3 directory")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("lookup", aliases=["show"], help="show exact background record")
    p.add_argument("term")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("facts", help="show 3-word facts involving a term")
    p.add_argument("term")
    p.add_argument("--incoming", action="store_true")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("taxonomy", aliases=["tax"], help="show taxonomy and belongs-chain")
    p.add_argument("term")

    p = sub.add_parser("connector", aliases=["connectors"], help="show connector/thesaurus variants")
    p.add_argument("relation", nargs="?", default="")

    p = sub.add_parser("bridge", help="find overlapping 3-word paths")
    p.add_argument("start")
    p.add_argument("target")
    p.add_argument("--depth", type=int, default=4)
    p.add_argument("--max-results", type=int, default=8)

    p = sub.add_parser("chain", help="validate overlapping exact 3-word facts")
    p.add_argument("facts", nargs="+")

    sub.add_parser("status", help="show shell/background/API/JX readiness")
    sub.add_parser("build", help="build the large background")
    sub.add_parser("index", help="build index.tsv")
    sub.add_parser("validate", help="validate background")

    p = sub.add_parser("dispatch", help="send work through the configured PHP API")
    p.add_argument("prompt")

    p = sub.add_parser("ask", help="use the existing eng1neer response path")
    p.add_argument("prompt")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    shell = AnemoneShell(Path(args.background))

    if not args.command:
        return shell.repl()

    cmd = args.command
    if cmd in {"lookup", "show"}:
        return shell.cmd_lookup(args.term, args.json)
    if cmd == "facts":
        return shell.cmd_facts(args.term, args.incoming, args.limit)
    if cmd in {"taxonomy", "tax"}:
        return shell.cmd_taxonomy(args.term)
    if cmd in {"connector", "connectors"}:
        return shell.cmd_connector(args.relation)
    if cmd == "bridge":
        return shell.cmd_bridge(args.start, args.target, args.depth, args.max_results)
    if cmd == "chain":
        return shell.cmd_chain(args.facts)
    if cmd == "status":
        return shell.cmd_status()
    if cmd == "build":
        return shell.cmd_tool("build_background.py", ["--repo", str(ROOT)])
    if cmd == "index":
        return shell.cmd_tool("build_index.py", [str(shell.folder)])
    if cmd == "validate":
        return shell.cmd_tool("validate_background.py", [str(shell.folder)])
    if cmd == "dispatch":
        return shell.cmd_dispatch(args.prompt)
    if cmd == "ask":
        return shell.cmd_ask(args.prompt)
    parser.error(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
