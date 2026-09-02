#!/usr/bin/env python3
"""Fast Anemone background lookup: byte index first, ripgrep fallback second."""
from pathlib import Path
import csv, json, re, shutil, subprocess


def slug(s):
    return re.sub(r'[^a-z0-9]+', '_', str(s).lower()).strip('_')


class Background:
    def __init__(self, folder='data/background3'):
        self.folder = Path(folder)
        self.index = {}
        idx = self.folder / 'index.tsv'
        if idx.exists():
            with idx.open(encoding='utf-8') as f:
                for r in csv.DictReader(f, delimiter='\t'):
                    self.index.setdefault(r['name'], []).append(
                        (r['file'], int(r['offset']), int(r['length']))
                    )

    def _seek(self, loc):
        fn, off, size = loc
        with (self.folder / fn).open('rb') as f:
            f.seek(off)
            return json.loads(f.read(size))

    def get(self, name):
        key = slug(name)
        hits = [self._seek(x) for x in self.index.get(key, [])]
        if hits:
            return hits
        rg = shutil.which('rg')
        if not rg:
            return []
        proc = subprocess.run(
            [rg, '-n', '-F', f'\"name\":\"{key}\"', str(self.folder), '-g', '*.jsonl'],
            text=True, capture_output=True
        )
        out = []
        for line in proc.stdout.splitlines():
            try:
                _, _, payload = line.split(':', 2)
                out.append(json.loads(payload))
            except Exception:
                pass
        return out


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('name')
    ap.add_argument('--folder', default='data/background3')
    a = ap.parse_args()
    print(json.dumps(Background(a.folder).get(a.name), indent=2))
