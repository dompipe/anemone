"""Compare and blend two subject entries using available subject files and thesaurus.

Usage: python compare_subjects.py subjectA subjectB

This is a root-level copy of the scripts/compare_subjects.py utilities so the
helpers are available from the repository top-level.
"""

import json
import os
import re
import sys
from pathlib import Path


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
    # very long tokens likely garbage
    if len(t) > 25:
        return True
    # numeric tokens are noise here
    if t.isdigit():
        return True
    return False


def looks_like_code_or_math(s: str) -> bool:
    s = s.lower()
    # crude checks: math operators, typical code keywords, or parenthesis/equals
    if any(ch in s for ch in '+-*/^=<>%'):
        return True
    code_keywords = ('def ', 'class ', 'import ', 'lambda', 'return', 'for ', 'while ', 'if ')
    if any(k in s for k in code_keywords):
        return True
    math_words = ('integral', 'derivative', 'sum', 'product', 'equation', 'solve')
    if any(w in s for w in math_words):
        return True
    return False


def load_thesaurus(path='thesaurus_assoc.json'):
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _clean_definition_text(s: str) -> str:
    """Remove URL/wiki noise, bracketed lists, and common noisy tokens from text."""
    if not s:
        return ''
    t = str(s)
    # remove explicit URLs
    t = re.sub(r'https?://\S+', ' ', t)
    t = re.sub(r'www\.\S+', ' ', t)
    # remove org/wiki style fragments
    t = re.sub(r'\borg/wiki/\S+', ' ', t, flags=re.IGNORECASE)
    # strip common host/token words
    t = re.sub(r'\b(wikipedia|wiki|org|com|net|edu|gov)\b', ' ', t, flags=re.IGNORECASE)
    # remove simple Python/JSON list artifacts like [ ... ]
    t = re.sub(r"\[.*?\]", ' ', t)
    # collapse whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _ensure_sentence_end(s: str) -> str:
    s = (s or '').strip()
    if not s:
        return ''
    if s[-1] not in '.!?':
        return s + '.'
    return s


def _ensure_periods_in_text(text: str) -> str:
    """Normalize text so sentences end with a period and are separated by a single space."""
    if not text:
        return ''
    # First split on newlines to respect deliberate breaks
    parts = [p.strip() for p in re.split(r'[\n]+', text) if p.strip()]
    sentences = []
    for p in parts:
        # further split on existing sentence boundaries
        subs = re.split(r'(?<=[.!?])\s+', p)
        for s in subs:
            ss = s.strip()
            if not ss:
                continue
            sentences.append(_capitalize_first_alpha(_ensure_sentence_end(ss)))
    return ' '.join(sentences)


def _capitalize_first_alpha(s: str) -> str:
    """Capitalize the first alphabetic character in the string, preserving leading punctuation."""
    if not s:
        return ''
    m = re.search(r'[A-Za-z]', s)
    if not m:
        return s
    i = m.start()
    return s[:i] + s[i].upper() + s[i+1:]


def _first_sentence_containing(text: str, term: str) -> str:
    if not text:
        return ''
    for s in re.split(r'[\n\.]', text):
        if term.lower() in s.lower():
            s = s.strip()
            return s if len(s) <= 240 else (s[:237] + '...')
    return ''


def is_noise_token(t: str) -> bool:
    return is_noise_token(t)


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
        'and or but however while although because since therefore thus hence whereas meanwhile furthermore moreover despite despite'
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
    """Try to find a single word that links both subjects using the thesaurus or shared terms."""
    # 1) prefer a shared term that maps in thesaurus to both subjects
    if isinstance(thesaurus, dict):
        for term in shared_terms:
            vals = thesaurus.get(term)
            if isinstance(vals, list) and name_a.lower() in [v.lower() for v in vals] and name_b.lower() in [v.lower() for v in vals]:
                return term
    # 2) prefer any short shared term (noun) that looks connective
    for term in shared_terms:
        if len(term) <= 12:
            return term
    # 3) try to find a thesaurus key that mentions both subjects
    if isinstance(thesaurus, dict):
        for k, v in thesaurus.items():
            if isinstance(v, list) and name_a.lower() in [x.lower() for x in v] and name_b.lower() in [x.lower() for x in v]:
                return k
    return None


def _strip_leading_term(text: str, name: str) -> str:
    """Remove a leading repeated subject name like 'Algebra Algebra' or a single leading 'Algebra'."""
    if not text or not name:
        return text or ''
    # If the name appears twice at the start (e.g. 'Algebra Algebra ...'), remove the first occurrence
    dup_pattern = re.compile(r'^\s*' + re.escape(name) + r'\s+' + re.escape(name) + r'\b', flags=re.IGNORECASE)
    if dup_pattern.search(text):
        # replace 'Name Name' with a single 'Name'
        return re.sub(dup_pattern, name, text, count=1).lstrip()
    # otherwise leave a single leading occurrence intact
    return text


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


def _find_sentences_with_terms(text, terms, max_n=5):
    if not text or not terms:
        return []
    out = []
    for s in re.split(r'[\n\.]', text):
        ss = s.strip()
        if not ss:
            continue
        low = ss.lower()
        for t in terms:
            if t and t.lower() in low and ss not in out:
                out.append(ss if len(ss) <= 400 else ss[:397] + '...')
                break
        if len(out) >= max_n:
            break
    return out


def generate_paragraph(name_a, name_b, defs, thesaurus):
    """Generate three short paragraphs: similarities, differences, conclusion."""
    a_raw = defs.get(name_a.lower(), '')
    b_raw = defs.get(name_b.lower(), '')

    def _normalize(x):
        if isinstance(x, dict):
            if 'definition' in x and isinstance(x['definition'], str):
                return x['definition']
            return _clean_definition_text(' '.join(str(v) for v in x.values()))
        if isinstance(x, list):
            return _clean_definition_text(' '.join(str(i) for i in x))
        return _clean_definition_text(str(x or ''))

    a_def = _normalize(a_raw)
    b_def = _normalize(b_raw)

    a_def = _strip_leading_term(a_def, name_a)
    b_def = _strip_leading_term(b_def, name_b)
    a_def = _ensure_periods_in_text(a_def)
    b_def = _ensure_periods_in_text(b_def)

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
    a_only = sorted(list(a_nouns - b_nouns))
    b_only = sorted(list(b_nouns - a_nouns))

    # Similarities paragraph
    sim_sentences = []
    if shared:
        sim_sentences += _find_sentences_with_terms(a_def, shared, max_n=3)
        sim_sentences += _find_sentences_with_terms(b_def, shared, max_n=3)
    if a_preds & b_preds:
        sim_sentences += _find_sentences_with_terms(a_def, list(a_preds & b_preds), max_n=2)
        sim_sentences += _find_sentences_with_terms(b_def, list(a_preds & b_preds), max_n=2)
    sim_sentences = list(dict.fromkeys(sim_sentences))[:5]
    if sim_sentences:
        sim_para = ' '.join(sim_sentences)
    else:
        sim_examples = ', '.join(shared[:4]) if shared else 'a few broad concepts'
        sim_para = (
            f"Similarities — Both {name_a} and {name_b} share anchors such as {sim_examples}. "
            f"They employ overlapping operational vocabulary (e.g. {', '.join(list(a_preds & b_preds)[:3]) or 'symbolic manipulation, operations'}), "
            "so practitioners use similar procedural skills across contexts."
        )

    a_high = ', '.join(a_only[:8]) or 'distinct focus'
    b_high = ', '.join(b_only[:8]) or 'distinct focus'
    diff_sentences = []
    if a_only:
        diff_sentences += _find_sentences_with_terms(a_def, a_only, max_n=3)
    if b_only:
        diff_sentences += _find_sentences_with_terms(b_def, b_only, max_n=3)
    bridge = find_bridge_word(shared, thesaurus, name_a, name_b) or (shared[0] if shared else None)
    if bridge:
        diff_sentences += _find_sentences_with_terms(a_def, [bridge], max_n=1)
        diff_sentences += _find_sentences_with_terms(b_def, [bridge], max_n=1)
    diff_sentences = list(dict.fromkeys(diff_sentences))[:5]
    if diff_sentences:
        diff_para = ' '.join(diff_sentences)
    else:
        diff_para = (
            f"Differences — {name_a} emphasizes {a_high}; {name_b} emphasizes {b_high}. "
            f"For example, {name_a}: " + (_first_sentence_containing(a_def, a_only[0]) or a_high) + " — whereas " + f"{name_b}: " + (_first_sentence_containing(b_def, b_only[0]) or b_high) + "."
        )

    if sim_para.strip() == diff_para.strip():
        diff_para = (
            "Differences — The source definitions overlap heavily; specific contrasts are limited in the available texts."
        )

    if percent >= 60:
        concl = (f"Conclusion — These fields are strongly related ({percent:.0f}%). Emphasize shared techniques and examples to leverage transfer.")
    elif percent >= 30:
        concl = (f"Conclusion — Moderate relation ({percent:.0f}%). Highlight bridging concepts (e.g. {bridge or 'functions, expressions'}) to help learners transfer skills.")
    else:
        concl = (f"Conclusion — Limited overlap ({percent:.0f}%). Treat them as distinct domains while teaching targeted bridges for transfer.")

    return '\n\n'.join([sim_para, diff_para, concl])


if __name__ == '__main__':
    raise SystemExit(load_subject_definitions())
