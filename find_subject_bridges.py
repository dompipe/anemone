"""Find promising subject-pair bridges across the local subject definitions.

Produces a ranked list of subject pairs with a percent similarity score and a
candidate bridge word or shared term. Uses the same local heuristics as
`compare_subjects.py` (nouns/predicates/participles/conjunctives).
"""

import json
import os
import re
from itertools import combinations


def load_subject_definitions(data_dir='data'):
    defs = {}
    if not os.path.isdir(data_dir):
        return defs
    for fn in os.listdir(data_dir):
        if not fn.endswith('.json'):
            continue
        try:
            with open(os.path.join(data_dir, fn), 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    for k, v in data.items():
                        defs[k.lower()] = v
        except Exception:
            continue
    return defs


STOPWORDS = {
    'the', 'a', 'an', 'of', 'and', 'in', 'on', 'for', 'with', 'to', 'by', 'is', 'are',
    'that', 'this', 'as', 'from', 'be', 'or', 'it', 'its'
}

NOISE_TOKENS = {'http', 'https', 'www', 'wiki', 'wikipedia', 'org', 'com', 'net', 'edu', 'gov'}


def is_noise_token(t: str) -> bool:
    t = (t or '').lower()
    if not t:
        return True
    if any(x in t for x in ('http', 'www')):
        return True
    if t in NOISE_TOKENS:
        return True
    if len(t) > 25:
        return True
    if t.isdigit():
        return True
    return False


def extract_nouns_and_predicates(text: str):
    text = (text or '').lower()
    tokens = re.findall(r"[a-zA-Z_]+", text)
    tokens = [t for t in tokens if t not in STOPWORDS and len(t) > 2 and not is_noise_token(t)]
    nouns = set()
    predicates = set()
    for t in tokens:
        if t.endswith(('ion', 'ment', 'ing', 'ize', 'ise')) or t in {'compute', 'calculate', 'measure', 'solve'}:
            predicates.add(t)
        else:
            nouns.add(t)
    return nouns, predicates


def extract_participles_and_conjunctives(text: str):
    t = (text or '').lower()
    tokens = re.findall(r"[a-zA-Z_]+", t)
    tokens = [w for w in tokens if not is_noise_token(w)]
    participles = {w for w in tokens if w.endswith('ing') and len(w) > 4}
    conjunctives_list = (
        'and or but however while although because since therefore thus hence whereas meanwhile furthermore moreover despite'
        ' in addition consequently accordingly nevertheless henceforth'
    )
    conjunctives = {w for w in tokens if w in conjunctives_list.split()}
    return participles, conjunctives


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    inter = a & b
    union = a | b
    return len(inter) / len(union) if union else 0.0


def find_bridge_word(shared_terms, thesaurus, name_a, name_b):
    if isinstance(thesaurus, dict):
        for term in shared_terms:
            vals = thesaurus.get(term)
            if isinstance(vals, list) and name_a.lower() in [v.lower() for v in vals] and name_b.lower() in [v.lower() for v in vals]:
                return term
    for term in shared_terms:
        if len(term) <= 12:
            return term
    if isinstance(thesaurus, dict):
        for k, v in thesaurus.items():
            if isinstance(v, list) and name_a.lower() in [x.lower() for x in v] and name_b.lower() in [x.lower() for x in v]:
                return k
    return None


def percent_similarity(a_def, b_def, thesaurus):
    a_nouns, a_preds = extract_nouns_and_predicates(a_def)
    b_nouns, b_preds = extract_nouns_and_predicates(b_def)
    a_partics, a_conjs = extract_participles_and_conjunctives(a_def)
    b_partics, b_conjs = extract_participles_and_conjunctives(b_def)

    noun_sim = jaccard(a_nouns, b_nouns)
    pred_sim = jaccard(a_preds, b_preds)
    partic_sim = jaccard(a_partics, b_partics)
    conj_sim = jaccard(a_conjs, b_conjs)
    percent = (noun_sim * 0.50 + pred_sim * 0.30 + partic_sim * 0.15 + conj_sim * 0.05) * 100
    shared = sorted(list(a_nouns & b_nouns))
    bridge = find_bridge_word(shared, thesaurus, '', '')
    return percent, shared, bridge


def load_thesaurus(path='thesaurus_assoc.json'):
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def normalize_value(x):
    if isinstance(x, dict):
        if 'definition' in x and isinstance(x['definition'], str):
            return x['definition']
        return ' '.join(str(v) for v in x.values())
    if isinstance(x, list):
        return ' '.join(str(i) for i in x)
    return str(x or '')


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Find top subject bridges')
    parser.add_argument('-n', '--top', type=int, default=50, help='number of top results to show')
    parser.add_argument('-t', '--threshold', type=float, default=20.0, help='minimum percent similarity to report')
    parser.add_argument('--data-dir', default='data', help='data directory')
    args = parser.parse_args(argv)

    defs = load_subject_definitions(data_dir=args.data_dir)
    thes = load_thesaurus()
    keys = sorted(defs.keys())
    results = []
    for a, b in combinations(keys, 2):
        a_def = normalize_value(defs[a])
        b_def = normalize_value(defs[b])
        percent, shared, bridge = percent_similarity(a_def, b_def, thes)
        if percent >= args.threshold:  # candidate threshold
            results.append((percent, a, b, shared[:6], bridge))

    results.sort(reverse=True, key=lambda x: x[0])
    top = results[:args.top]
    if not top:
        print(f'No strong candidate bridges found (threshold {args.threshold}%).')
        return
    print('Top subject bridges (percent, subjectA, subjectB, shared_terms, bridge):')
    for pct, a, b, shared, bridge in top:
        print(f"{pct:.0f}%\t{a}\t{b}\tshared={shared}\tbridge={bridge}")


if __name__ == '__main__':
    import sys
    main(sys.argv[1:])
