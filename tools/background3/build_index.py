#!/usr/bin/env python3
"""Build byte-offset index.tsv for every JSONL record under an Anemone background folder."""
from pathlib import Path
import argparse, csv, json, re


def slug(s):
    return re.sub(r'[^a-z0-9]+', '_', str(s).lower()).strip('_')


def build_index(folder='data/background3'):
    root = Path(folder)
    rows = []
    for fp in sorted(root.rglob('*.jsonl')):
        rel = fp.relative_to(root).as_posix()
        with fp.open('rb') as f:
            while True:
                off = f.tell()
                line = f.readline()
                if not line:
                    break
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                names = []
                if rec.get('kind') == 'connector':
                    names.append(rec.get('relation'))
                    names.append(rec.get('seed'))
                    names.extend(rec.get('variants') or [])
                else:
                    names.append(rec.get('name'))
                    names.extend(rec.get('aliases') or [])
                for name in names:
                    if name:
                        rows.append((slug(name), rel, off, len(line)))
    with (root/'index.tsv').open('w', encoding='utf-8', newline='') as out:
        w = csv.writer(out, delimiter='\t')
        w.writerow(['name','file','offset','length'])
        w.writerows(rows)
    print(f'indexed {len(rows):,} names')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('folder', nargs='?', default='data/background3')
    args = ap.parse_args()
    build_index(args.folder)


if __name__ == '__main__':
    main()
