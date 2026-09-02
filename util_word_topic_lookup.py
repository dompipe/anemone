import os
import json
import difflib


def load_word_freq(word_freq_path):
    if not os.path.exists(word_freq_path):
        try:
            from pathlib import Path
            from word_freq_runtime import ensure_word_freq
            generated = ensure_word_freq(Path(__file__).resolve().parent)
            if os.path.basename(word_freq_path) == 'word_freq.txt':
                word_freq_path = str(generated)
        except Exception:
            pass
    with open(word_freq_path, 'r', encoding='utf-8') as f:
        return set(line.strip().lower() for line in f if line.strip())


def load_json(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def similarity(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def lookup_word_topics(word, word_freq_path='word_freq.txt',
                      assoc_path='thesaurus_assoc.json',
                      code_dict_path='data/code_dictionary.json',
                      definitions_path='data/wikipedia_defs.json',
                      min_similarity=0.8):
    word = word.lower().strip()
    word_freq = load_word_freq(word_freq_path)
    # Find closest match in the global Anemone vocabulary.
    best_match = None
    best_score = 0.0
    for wf in word_freq:
        score = similarity(word, wf)
        if score > best_score:
            best_score = score
            best_match = wf
    if best_score < min_similarity:
        return None  # No good match, leave alone
    # Check for topics in thesaurus_assoc.json
    assoc = load_json(assoc_path)
    topics = assoc.get(best_match, [])
    if topics:
        return {'word': best_match, 'topics': topics, 'source': 'thesaurus_assoc'}
    # Check for instantiation in code_dictionary.json
    if os.path.exists(code_dict_path):
        code_dict = load_json(code_dict_path)
        if best_match in code_dict:
            return {'word': best_match, 'topics': ['code'], 'source': 'code_dictionary'}
    # Check for definition in the derived Wikipedia definitions
    if os.path.exists(definitions_path):
        definitions = load_json(definitions_path)
        if best_match in definitions:
            return {'word': best_match, 'topics': ['definition'], 'source': 'wikipedia_defs'}
    # If word is in the vocabulary but not in these direct topic files, leave it alone.
    return None


# Example usage:
if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('Usage: python util_word_topic_lookup.py <word>')
    else:
        result = lookup_word_topics(sys.argv[1])
        print(result if result else 'No relevant topics found.')
