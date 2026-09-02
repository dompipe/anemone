#!/usr/bin/env python3
from pathlib import Path
import argparse, json, sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('folder', nargs='?', default='data/background3')
    a = ap.parse_args()
    errors = []
    records = 0
    facts = 0
    for fp in Path(a.folder).rglob('*.jsonl'):
        for ln, line in enumerate(fp.open(encoding='utf-8'), 1):
            records += 1
            try:
                r = json.loads(line)
            except Exception as e:
                errors.append(f'{fp}:{ln}: invalid JSON: {e}')
                continue
            for field in ('facts', 'taxonomy_facts'):
                for fact in r.get(field, []) or []:
                    facts += 1
                    if not isinstance(fact, list) or len(fact) != 3 or any(' ' in str(x).strip() for x in fact):
                        errors.append(f'{fp}:{ln}: {field} is not exact 3-token fact: {fact!r}')
            tf = r.get('taxonomy_facts') or []
            for x, y in zip(tf, tf[1:]):
                if x[2] != y[0]:
                    errors.append(f'{fp}:{ln}: broken taxonomy hinge: {x} -> {y}')
    print(f'{records} records; {facts} three-token facts; {len(errors)} errors')
    if errors:
        print('\n'.join(errors[:100]))
        sys.exit(1)


if __name__ == '__main__':
    main()
