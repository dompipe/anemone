#!/usr/bin/env python3
"""Scan subject pairs and report pairs where definitions contain example sentences
mentioning shared anchor nouns (i.e., not purely template output).

Usage: python find_pairs_with_examples.py --top 20
"""
import argparse
import importlib.util
import itertools
import json
import re
from pathlib import Path

# Load compare_subjects.py as a module without running its CLI main block
spec = importlib.util.spec_from_file_location('compare_subjects_mod', str(Path(__file__).parent / 'compare_subjects.py'))
compare_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare_mod)

load_subject_definitions = compare_mod.load_subject_definitions
extract_nouns_and_predicates = compare_mod.extract_nouns_and_predicates
_clean_definition_text = compare_mod._clean_definition_text
_ensure_periods_in_text = compare_mod._ensure_periods_in_text
_strip_leading_term = compare_mod._strip_leading_term
_capitalize_first_alpha = compare_mod._capitalize_first_alpha


def sentences_with_term(text, term, max_n=2):
    if not text or not term:
        return []
    out = []
    for s in re.split(r'[\n\.]+', text):
        ss = s.strip()
        if not ss:
            continue
        if term.lower() in ss.lower():
            out.append(_capitalize_first_alpha(ss if len(ss) <= 400 else ss[:397] + '...'))
            if len(out) >= max_n:
                break
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--top', '-n', type=int, default=20)
    args = p.parse_args()

    defs = load_subject_definitions()
    keys = sorted(defs.keys())

    results = []
    for a, b in itertools.combinations(keys, 2):
        a_raw = defs.get(a, '')
        b_raw = defs.get(b, '')
        # normalize similar to compare_subjects
        def norm(x, name):
            if isinstance(x, dict):
                if 'definition' in x and isinstance(x['definition'], str):
                    t = x['definition']
                else:
                    t = ' '.join(str(v) for v in x.values())
            elif isinstance(x, list):
                t = ' '.join(str(i) for i in x)
            else:
                t = str(x or '')
            t = _clean_definition_text(t)
            t = _strip_leading_term(t, name)
            t = _ensure_periods_in_text(t)
            return t

        a_def = norm(a_raw, a)
        b_def = norm(b_raw, b)

        a_nouns, _ = extract_nouns_and_predicates(a_def)
        b_nouns, _ = extract_nouns_and_predicates(b_def)
        shared = sorted(list(a_nouns & b_nouns))
        if not shared:
            continue

        # Check for actual sentences in either def that mention shared nouns
        sample_sentences = []
        for term in shared[:6]:
            sa = sentences_with_term(a_def, term, max_n=1)
            sb = sentences_with_term(b_def, term, max_n=1)
            if sa or sb:
                sample_sentences.append((term, sa[:1], sb[:1]))
        if not sample_sentences:
            continue

        results.append((len(sample_sentences), len(shared), a, b, sample_sentences))

    # sort by number of sample sentences then shared nouns (desc)
    results.sort(key=lambda x: (x[0], x[1]), reverse=True)

    top = results[: args.top]
    for count_examples, shared_count, a, b, samples in top:
        print(f"{a} <-> {b}  | examples:{count_examples} shared:{shared_count}")
        for term, sa, sb in samples:
            print(f" - {term} -> {a}: {sa[0] if sa else ''}")
            print(f"           {b}: {sb[0] if sb else ''}")
        print()


if __name__ == '__main__':
    main()
