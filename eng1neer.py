def is_participle(word):
    # Heuristic: participles often end with these suffixes
    return word.lower().endswith((
        'ing', 'ed', 'en', 'nt', 'd', 't', 'n', 'ne', 'wn', 'pt', 'st', 'ft', 'ld', 'lt', 'rt', 'rd', 'rn', 'rk', 'rm', 'mp', 'nd', 'nt', 'sk', 'sp', 'st', 'th', 'wn', 'zz', 'ss', 'sh', 'ch', 'ph', 'gh', 'wh', 'ng', 'nk', 'ct', 'ft', 'pt', 'xt', 'zz', 'ed', 'en'
    ))

def strip_participles_from_end(text):
    # Remove trailing participles from the end of a sentence
    words = text.rstrip().split()
    while words and is_participle(words[-1].strip('.,;:')):
        words.pop()
    return ' '.join(words)

def respond_subject_specific(prompt: str, assoc_path='thesaurus_assoc.json', data_dir='data') -> str:
    # --- Context-aware answer splicing ---
    # If previous answer exists, use it as context for the next answer
    if not hasattr(respond_subject_specific, '_last_answer'):
        respond_subject_specific._last_answer = ''
    previous_answer = respond_subject_specific._last_answer

    # Intercept code-notes commands before any other handling.
    try:
        from eng1neer_notes import handle_notes_command
        _notes_response = handle_notes_command(prompt)
        if _notes_response is not None:
            return _notes_response
    except Exception:
        pass

    # Intercept patcher-related natural-language requests and handle them here.
    # If a pending patch exists, interpret the user's reply as confirm/cancel/apply.
    try:
        from eng1neer_patch import (
            detect_patch_intent,
            patch_kingdom_json_chat,
            prepare_patch_preview,
            apply_selected_changes,
            get_git_blame_for_lines,
            find_line_numbers,
            get_diff_for_change,
            load_pending_patches,
            get_pending_patch,
            add_pending_patch,
            remove_pending_patch,
            apply_pending_patch,
        )
        # If there's a pending patch awaiting confirmation, check user response
        pending = getattr(respond_subject_specific, '_pending_patch', None)
        user_cmd = prompt.strip().lower()
        import re

        # Global pending commands: apply <id>, preview pending <id>, list pending, remove pending <id>
        m_apply_id = re.search(r"\bapply(?:\s+pending)?\s+([0-9a-fA-F-]{6,})\b", user_cmd)
        if m_apply_id:
            pid = m_apply_id.group(1)
            # default to inplace unless user said out=<path>
            inplace_flag = 'inplace' in user_cmd or 'write' in user_cmd
            out_m = re.search(r"out[:=]\s*([\w\-./\\]+\.json)", user_cmd)
            out_path = out_m.group(1) if out_m else None
            res = apply_pending_patch(pid, inplace=inplace_flag, out=out_path, dry_run=False)
            if res.get('error'):
                return f"Failed to apply pending {pid}: {res['error']}"
            return f"Applied {res.get('applied',0)} changes. Wrote to: {res.get('written_to') or 'none'}"

        m_preview_id = re.search(r"\bpreview(?:\s+pending)?\s+([0-9a-fA-F-]{6,})\b", user_cmd)
        if m_preview_id:
            pid = m_preview_id.group(1)
            ent = get_pending_patch(pid)
            if not ent:
                return f'No pending patch with id {pid}'
            parsed = ent.get('parsed', {})
            return patch_kingdom_json_chat(parsed.get('path'), parsed.get('old'), parsed.get('new'), regex=parsed.get('regex_flag', False), layer=parsed.get('layer'), apply=False)

        if re.search(r"\blist\s+pending\b|\bpending\s+list\b|\bshow\s+pending\b", user_cmd):
            ents = load_pending_patches()
            if not ents:
                return 'No pending patches.'
            lines = [f"Pending patches ({len(ents)}):"]
            for e in ents:
                pid = e.get('id')
                p = e.get('parsed', {})
                lines.append(f"- {pid}: {p.get('old')} -> {p.get('new')} (path: {p.get('path')})")
            return '\n'.join(lines)

        m_remove = re.search(r"\bremove\s+pending\s+([0-9a-fA-F-]{6,})\b", user_cmd)
        if m_remove:
            pid = m_remove.group(1)
            ok = remove_pending_patch(pid)
            return f'Removed pending {pid}.' if ok else f'No pending patch {pid} found.'
        if pending:
            # parse commands: apply, apply N, apply 1-3, apply all, cancel, preview, blame N, diff N
            import re
            if re.search(r"\b(cancel|no|abort)\b", user_cmd):
                respond_subject_specific._pending_patch = None
                return 'Patch cancelled.'

            m_all = re.search(r"\bapply(?:\s+all)?(?:\s+inplace)?\b", user_cmd)
            m_sel = re.search(r"\bapply\s+([0-9,\-\s]+)(?:\s+inplace)?\b", user_cmd)
            if m_all and not m_sel:
                # apply all
                inplace_flag = 'inplace' in user_cmd or pending.get('apply_flag', False)
                res = apply_selected_changes(pending['path'], pending['old'], pending['new'], regex=pending['regex_flag'], layer=pending['layer'], selected_indices=None, inplace=inplace_flag, dry_run=pending['dry_run'])
                respond_subject_specific._pending_patch = None
                return f"Applied {res['applied']} changes. Wrote to: {res['written_to']}" if res['written_to'] else f"Applied {res['applied']} changes. No file written."

            if m_sel:
                rng = m_sel.group(1)
                # parse numbers and ranges
                idxs = []
                for part in re.split(r"[\s,]+", rng.strip()):
                    if '-' in part:
                        a, b = part.split('-', 1)
                        try:
                            a_i = int(a) - 1
                            b_i = int(b) - 1
                            idxs.extend(list(range(a_i, b_i + 1)))
                        except Exception:
                            continue
                    else:
                        try:
                            idxs.append(int(part) - 1)
                        except Exception:
                            continue
                inplace_flag = 'inplace' in user_cmd or pending.get('apply_flag', False)
                res = apply_selected_changes(pending['path'], pending['old'], pending['new'], regex=pending['regex_flag'], layer=pending['layer'], selected_indices=idxs, inplace=inplace_flag, dry_run=pending['dry_run'])
                respond_subject_specific._pending_patch = None
                return f"Applied {res['applied']} changes. Wrote to: {res['written_to']}" if res['written_to'] else f"Applied {res['applied']} changes. No file written."

            if re.search(r"\bpreview\b|\bshow\b|\bwhat\b", user_cmd):
                return patch_kingdom_json_chat(pending['path'], pending['old'], pending['new'], regex=pending['regex_flag'], layer=pending['layer'], apply=False)

            m_blame = re.search(r"\bblame\s+(\d+)\b", user_cmd)
            if m_blame:
                idx = int(m_blame.group(1)) - 1
                details = prepare_patch_preview(pending['path'], pending['old'], pending['new'], pending['regex_flag'], pending['layer'])
                if 0 <= idx < len(details):
                    nums = find_line_numbers(pending['path'], details[idx][3])
                    if nums:
                        b = get_git_blame_for_lines(pending['path'], nums[0], nums[0])
                        return b or 'No blame info available.'
                return 'No matching change for blame.'

            m_diff = re.search(r"\bdiff\s+(\d+)\b", user_cmd)
            if m_diff:
                idx = int(m_diff.group(1)) - 1
                details = prepare_patch_preview(pending['path'], pending['old'], pending['new'], pending['regex_flag'], pending['layer'])
                if 0 <= idx < len(details):
                    d = get_diff_for_change(pending['path'], details[idx])
                    return d
                return 'No matching change for diff.'

        # No pending patch: detect intent
        intent = detect_patch_intent(prompt)
        if intent:
            # store pending intent and return preview with explicit confirmation instructions
            respond_subject_specific._pending_patch = intent
            preview = patch_kingdom_json_chat(intent['path'], intent['old'], intent['new'], regex=intent['regex_flag'], layer=intent['layer'], apply=False)
            return preview + "\n\nIf you want to apply these changes, reply 'apply'. To cancel, reply 'cancel'. To apply and write the file, reply 'apply inplace'."
    except Exception:
        pass

    # Quick detection: natural-language equality/inclusion questions
    try:
        # common patterns: "is X the same as Y", "are X and Y the same", "does X include Y", "is X a type of Y"
        _q = prompt.strip()
        _ql = _q.lower()
        # Quick date/range queries: if user asks about a year or range, use history lookup
        try:
            from history_lookup import find_entries_covering_year, query_period_coverage, find_entries_within_range
            m = re.search(r'between\s+(-?\d{1,4})\s+(?:and|to)\s+(-?\d{1,4})', _ql)
            if m:
                s = int(m.group(1))
                e = int(m.group(2))
                return query_period_coverage(s, e)
            m2 = re.search(r'\bin\s+(-?\d{1,4})\b', _ql)
            if m2 and not re.search(r'\bcompare\b|\bequal\b|\bsame\b', _ql):
                year = int(m2.group(1))
                entries = find_entries_covering_year(year)
                if not entries:
                    return f'No historical entries recorded for {year}.'
                lines = [f'Historical entries covering {year}:']
                for key, rec in entries[:10]:
                    sy = rec.get('start_year') or rec.get('year') or 'N/A'
                    ey = rec.get('end_year') or rec.get('year') or 'N/A'
                    lines.append(f"- {key}: {sy}–{ey} — {rec.get('gloss','')}")
                return '\n'.join(lines)
        except Exception:
            pass
        eq_patterns = [
            r"^is\s+(.+?)\s+(?:the same as|equal to|equal|equivalent to)\s+(.+?)\??$",
            r"^are\s+(.+?)\s+and\s+(.+?)\s+(?:the same|equivalent)\??$",
            r"^does\s+(.+?)\s+(?:include|contain|cover|mean|imply|subsume)\s+(.+?)\??$",
            r"^is\s+(.+?)\s+a\s+(?:type|kind|form)\s+of\s+(.+?)\??$",
            r"^what(?:'s| is) the difference between\s+(.+?)\s+and\s+(.+?)\??$",
            r"^how does\s+(.+?)\s+differ from\s+(.+?)\??$",
            r"^are\s+(.+?)\s+and\s+(.+?)\s+equivalent\??$",
            r"^is\s+(.+?)\s+part of\s+(.+?)\??$",
            r"^is\s+(.+?)\s+included in\s+(.+?)\??$",
            r"^is\s+(.+?)\s+a\s+subset\s+of\s+(.+?)\??$",
            r"^do(es)?\s+(.+?)\s+imply\s+(.+?)\??$",
            r"^is\s+(.+?)\s+(?:greater than|larger than|more than)\s+(.+?)\??$",
            r"^is\s+(.+?)\s+(?:less than|smaller than)\s+(.+?)\??$",
            r"^which\s+is\s+(?:bigger|larger):\s*(.+?)\s+or\s+(.+?)\??$",
            r"^which\s+is\s+(?:smaller|less):\s*(.+?)\s+or\s+(.+?)\??$",
            r"^compare\s+(.+?)\s+and\s+(.+?)\??$",
            r"^compare\s+(.+?)\s+to\s+(.+?)\??$",
            r"^are\s+(.+?)\s+synonyms\??$",
            r"^is\s+(.+?)\s+analogous\s+to\s+(.+?)\??$",
            r"^are\s+(.+?)\s+related\s+to\s+(.+?)\??$",
        ]
        for pat in eq_patterns:
            m = re.search(pat, _ql)
            if not m:
                continue
            # Different patterns capture groups differently; take last two groups as terms
            groups = [g for g in m.groups() if g]
            if len(groups) >= 2:
                a = groups[-2].strip(' ?.,')
                b = groups[-1].strip(' ?.,')
            else:
                continue
            # Detect predicate-style queries like "do A and B VERB ...?"
            pred_m = re.search(r"^do\s+(.+?)\s+and\s+(.+?)\s+(.+?)\??$", _ql)
            if pred_m:
                pa = pred_m.group(1).strip()
                pb = pred_m.group(2).strip()
                predicate = pred_m.group(3).strip(' ?.,')
                # ensure terms match extracted a/b
                # fall back to earlier parsed a/b otherwise
                a_term = pa or a
                b_term = pb or b
                try:
                    from equality_verifier import find_entries, tokenize, entry_keywords, relation_between_terms
                    data_map = load_all_data('data')
                except Exception:
                    data_map = None

                def _predicate_overlap(term, predicate_text):
                    # return max token overlap between predicate tokens and any entry keywords for term
                    try:
                        preds = []
                        if data_map is None:
                            return 0.0
                        found = find_entries(term, data_map)
                        pred_toks = set(tokenize(predicate_text))
                        best = 0.0
                        for _, _, ent in found:
                            kws = set(entry_keywords(ent))
                            if not kws or not pred_toks:
                                continue
                            inter = len(kws & pred_toks)
                            frac = inter / max(1, len(pred_toks))
                            best = max(best, frac)
                        return best
                    except Exception:
                        return 0.0

                a_pred = _predicate_overlap(a_term, predicate)
                b_pred = _predicate_overlap(b_term, predicate)
                # similarity between a and b
                try:
                    relv = relation_between_terms(a_term, b_term)
                except Exception:
                    relv = {}
                reltype = relv.get('relation')
                # decide phrasing
                thresh = 0.35
                if a_pred < thresh and b_pred < thresh and reltype in ('overlap', 'equal'):
                    out = f"Neither {a_term} nor {b_term} {predicate} (no indication either does)."
                    respond_subject_specific._last_answer = out
                    return out
                if a_pred >= thresh and b_pred < thresh:
                    out = f"{a_term.capitalize()} {predicate}, whereas {b_term} does not appear to {predicate}."
                    respond_subject_specific._last_answer = out
                    return out
                if b_pred >= thresh and a_pred < thresh:
                    out = f"{b_term.capitalize()} {predicate}, whereas {a_term} does not appear to {predicate}."
                    respond_subject_specific._last_answer = out
                    return out
                # fall through to normal equal/inclusion logic if ambiguous
            try:
                from equality_verifier import relation_between_terms
                verdict = relation_between_terms(a, b)
                rel = verdict.get('relation')
                if rel == 'equal':
                    out = f"Yes — '{a}' and '{b}' are equivalent. ({verdict.get('reason')})"
                elif rel == 'a_includes_b':
                    out = f"'{a}' broadly includes '{b}' (score {verdict.get('score'):.2f})."
                elif rel == 'b_includes_a':
                    out = f"'{b}' broadly includes '{a}' (score {verdict.get('score'):.2f})."
                elif rel == 'overlap':
                    out = f"'{a}' and '{b}' overlap (score {verdict.get('score'):.2f})."
                else:
                    out = f"'{a}' and '{b}' appear distinct. ({verdict.get('reason')})"
                respond_subject_specific._last_answer = out
                return out
            except Exception:
                # fall back to normal processing if verifier fails
                break
    except Exception:
        pass

    """
    For each extracted term in the prompt, find all subject files (classifications) it appears in using thesaurus_assoc.json.
    Load only those files, gather definitions for the term, and build a subject-specific response.
    """
    import json, os, re
    # --- Normalization helper ---
    # Ensures consistent, lowercase, alphanumeric term matching
    def normalize(term):
        """Normalize a term to lowercase alphanumeric for consistent matching."""
        return re.sub(r'[^a-z0-9]', '', term.lower())

    # --- Association loading ---
    # Loads the main subject association file for fast lookup
    with open(assoc_path, 'r', encoding='utf-8') as f:
        assoc = json.load(f)

    # --- Term extraction and similarity import ---
    # Extracts candidate terms from the prompt and prepares Levenshtein similarity
    import sys
    sys.path.append(os.path.dirname(__file__))
    try:
        from util_word_topic_lookup import similarity
    except ImportError:
        similarity = None
    # --- Persistent subject memory ---
    if not hasattr(respond_subject_specific, "_last_subject"):
        respond_subject_specific._last_subject = None
    terms = extract_terms(prompt)
    # Find the first noun (regular/proper) in the prompt
    import string
    prompt_tokens = re.findall(r"\b\w+\b", prompt)
    def is_noun_candidate(word):
        return word and word[0].isalpha() and word.lower() not in {"i","me","my","mine","myself","you","your","yours","yourself","yourselves","he","him","his","himself","she","her","hers","herself","it","its","itself","we","us","our","ours","ourselves","they","them","their","theirs","themselves","this","that","these","those","who","whom","whose","which","what","where","when","why","how"}
    noun_in_prompt = next((w for w in prompt_tokens if is_noun_candidate(w)), None)
    if noun_in_prompt:
        respond_subject_specific._last_subject = noun_in_prompt
    current_subject = respond_subject_specific._last_subject

    # --- Domain lineage and sibling/subspecies logic ---
    # For each filtered term, find its subject (file), type (term), synonyms (subspecies), and siblings (other terms in file)
    domain_info = {}
    for fname in os.listdir(data_dir):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(data_dir, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as fjson:
                data = json.load(fjson)
        except Exception:
            continue
        for term in terms:
            if term in data:
                entry = data[term]
                # Synonyms (subspecies)
                subspecies = set()
                if isinstance(entry, list):
                    for e in entry:
                        if isinstance(e, dict) and 'synonyms' in e:
                            subspecies.update(e['synonyms'])
                elif isinstance(entry, dict) and 'synonyms' in entry:
                    subspecies.update(entry['synonyms'])
                # Siblings (other types in the same file)
                siblings = [k for k in data.keys() if k != term]
                domain_info[term] = {
                    'kingdom': fname.replace('.json',''),
                    'type': term,
                    'subspecies': sorted(list(subspecies)),
                    'siblings': siblings[:10]  # limit to 10 for brevity
                }


    # --- Prioritized lookup order for subject association ---
    # 1. Direct match in thesaurus_assoc.json
    # 2. Fuzzy match in word_freq.txt (Levenshtein)
    # 3. Direct match in any data/*.json file
    # 4. Direct match in code_dictionary.json
    # 5. Direct match in definitions.json
    # This order ensures the most relevant, subject-specific, and expressive definitions are used first.
    with open(assoc_path, 'r', encoding='utf-8') as f:
        assoc = json.load(f)
    filtered_terms = []
    for term in terms:
        term_l = term.lower().strip()
        # Handle special multi-word aliases (map to canonical keys)
        SPECIAL_EQUIV = {
            'american football': 'football'
        }
        mapped = SPECIAL_EQUIV.get(term_l)
        if mapped:
            # if mapped term has an association, prefer that
            if mapped in assoc:
                filtered_terms.append(mapped)
                continue
        # --- 1. Direct subject association ---
        if term_l in assoc:
            filtered_terms.append(term_l)
            continue
        # --- 2. Fuzzy word match (Levenshtein) ---
        word_freq_path = os.path.join(os.path.dirname(__file__), 'word_freq.txt')
        with open(word_freq_path, 'r', encoding='utf-8') as wf:
            word_freq = [line.strip().lower() for line in wf if line.strip()]
        best_match = None
        best_score = 0.0
        if similarity:
            for wf_word in word_freq:
                score = similarity(term_l, wf_word)
                if score > best_score:
                    best_score = score
                    best_match = wf_word
        if best_score >= 0.8:
            # If Levenshtein match, re-check thesaurus_assoc for the matched word
            if best_match in assoc:
                filtered_terms.append(best_match)
                continue
        # --- 3. Direct match in any data/*.json file ---
        found_in_data = False
        # If term has a special mapping, prefer checking the mapped key in data files
        if mapped:
            for fname in os.listdir(data_dir):
                if fname.endswith('.json'):
                    fpath = os.path.join(data_dir, fname)
                    try:
                        with open(fpath, 'r', encoding='utf-8') as fjson:
                            data = json.load(fjson)
                        if mapped in data:
                            filtered_terms.append(mapped)
                            found_in_data = True
                            break
                    except Exception:
                        continue
        if found_in_data:
            continue
        for fname in os.listdir(data_dir):
            if fname.endswith('.json'):
                fpath = os.path.join(data_dir, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8') as fjson:
                        data = json.load(fjson)
                    if term_l in data:
                        filtered_terms.append(term_l)
                        found_in_data = True
                        break
                except Exception:
                    continue
        if found_in_data:
            continue
        # --- 4. code_dictionary.json ---
        code_dict_path = os.path.join(data_dir, 'code_dictionary.json')
        if os.path.exists(code_dict_path):
            with open(code_dict_path, 'r', encoding='utf-8') as fcd:
                code_dict = json.load(fcd)
            if term_l in code_dict:
                filtered_terms.append(term_l)
                continue
        # --- 5. wikipedia_defs.json (preferred over legacy definitions.json) ---
        wiki_defs_path = os.path.join(data_dir, 'wikipedia_defs.json')
        if os.path.exists(wiki_defs_path):
            try:
                with open(wiki_defs_path, 'r', encoding='utf-8') as fd:
                    wiki_defs = json.load(fd)
                if term_l in wiki_defs:
                    filtered_terms.append(term_l)
                    continue
            except Exception:
                pass
        # legacy fallback: definitions.json (kept only for compatibility)
        definitions_path = os.path.join(data_dir, 'definitions.json')
        if os.path.exists(definitions_path):
            try:
                with open(definitions_path, 'r', encoding='utf-8') as fd:
                    definitions = json.load(fd)
                if term_l in definitions:
                    filtered_terms.append(term_l)
                    continue
            except Exception:
                pass
        # --- If not found anywhere, skip this term ---
    if not filtered_terms:
        # Attempt a robust fallback: use wikipedia_defs.json lead-summary if available
        try:
            wiki_defs_path = os.path.join(data_dir, 'wikipedia_defs.json')
            if os.path.exists(wiki_defs_path):
                with open(wiki_defs_path, 'r', encoding='utf-8') as fw:
                    wiki_defs = json.load(fw)
                # Prefer the noun_in_prompt if we detected one earlier
                candidates = []
                if noun_in_prompt:
                    candidates.append(noun_in_prompt.lower())
                # also try original extracted terms as a fallback
                candidates.extend([t.lower() for t in terms])
                for cand in candidates:
                    if not cand:
                        continue
                    if cand in wiki_defs:
                        ent = wiki_defs[cand]
                        # Try 'summary' or 'definition' or 'gloss' fields
                        summary = None
                        if isinstance(ent, dict):
                            summary = ent.get('summary') or ent.get('definition') or ent.get('gloss')
                        elif isinstance(ent, str):
                            summary = ent
                        if summary:
                            # Return the first sentence for clarity
                            s = re.split(r'(?<=[.!?])\s+', summary.strip())
                            lead = s[0] if s else summary.strip()
                            return f"{cand.capitalize()}: {lead}"
        except Exception:
            pass
        return "No subject-specific definitions found for your query."
    terms = filtered_terms
    alt_terms = set(terms)
    responses = []
    import collections
    # Use module-level blending implementation for portability and testing
    blend_definitions = None  # assigned to module-level `blend_fragments` at import time

    # Define file priority order (customize as needed)
    file_priority = [
        # Math group
        'algebra.json', 'linear_algebra.json', 'calculus.json',
        # Science group
        'biology.json', 'chemistry.json', 'physics.json', 'math.json', 'geometry.json', 'complex_numbers.json',
        'probability.json', 'statistics.json', 'thermodynamics.json', 'trigonometry.json', 'vectors.json',
        # Other
        'economics.json', 'finance.json', 'user_drift.json',
        # Code just before definitions
        'code_dictionary.json',
        # Prefer the derived Wikipedia definitions file as the canonical last-resort source
        'wikipedia_defs.json'
    ]
    # Build list of files present, preferring file_priority and wikipedia_defs.json
    files_in_dir = set(f for f in os.listdir(data_dir) if f.endswith('.json'))
    # Exclude legacy `definitions.json` entirely — use wikipedia-derived sources only
    if 'definitions.json' in files_in_dir:
        files_in_dir.remove('definitions.json')
    ordered_files = [f for f in file_priority if f in files_in_dir]
    # Ensure wikipedia_defs.json is present as canonical fallback
    if 'wikipedia_defs.json' in files_in_dir and 'wikipedia_defs.json' not in ordered_files:
        ordered_files.append('wikipedia_defs.json')


    

    # Build a mapping: term -> [files that define it]
    term_to_files = {term: [] for term in terms}
    file_to_terms = {fname: set() for fname in ordered_files}
    file_term_defs = {fname: {} for fname in ordered_files}
    for fname in ordered_files:
        fpath = os.path.join(data_dir, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as fjson:
                data = json.load(fjson)
            for term in terms:
                entry = data.get(term)
                if not entry:
                    continue

                def _clean_text_examples(text: str) -> str:
                    if not text or not isinstance(text, str):
                        return text
                    low = text
                    # Remove common example clauses that start with these markers
                    markers = [" e.g.", " e.g ", " for example", " such as", " including:", " including ", " (e.g.", " (for example"]
                    idx = None
                    for m in markers:
                        i = low.find(m)
                        if i != -1:
                            if idx is None or i < idx:
                                idx = i
                    if idx is not None:
                        return text[:idx].strip(' ,;:()')
                    return text

                # Clean up definitions/gloss strings to remove embedded example lists
                cleaned_entry = entry
                try:
                    if isinstance(entry, str):
                        cleaned_entry = _clean_text_examples(entry)
                    elif isinstance(entry, dict):
                        ce = dict(entry)
                        if 'definition' in ce and isinstance(ce['definition'], str):
                            ce['definition'] = _clean_text_examples(ce['definition'])
                        if 'gloss' in ce and isinstance(ce['gloss'], str):
                            ce['gloss'] = _clean_text_examples(ce['gloss'])
                        cleaned_entry = ce
                    elif isinstance(entry, list):
                        new_list = []
                        for it in entry:
                            if isinstance(it, str):
                                new_list.append(_clean_text_examples(it))
                            elif isinstance(it, dict):
                                it2 = dict(it)
                                if 'definition' in it2 and isinstance(it2['definition'], str):
                                    it2['definition'] = _clean_text_examples(it2['definition'])
                                if 'gloss' in it2 and isinstance(it2['gloss'], str):
                                    it2['gloss'] = _clean_text_examples(it2['gloss'])
                                new_list.append(it2)
                        cleaned_entry = new_list
                except Exception:
                    cleaned_entry = entry

                term_to_files[term].append(fname)
                file_to_terms[fname].add(term)
                file_term_defs[fname][term] = cleaned_entry
        except Exception:
            continue

    # Prefer to use the file that covers the most terms in the prompt
    # If a term is only found in one file, use that file for that term
    # Otherwise, try to use the file that covers the most terms for as many as possible
    # If tie, use file_priority order
    responses = []
    # Find the file that covers the most terms
    file_term_count = {fname: len(terms_set) for fname, terms_set in file_to_terms.items()}
    # For each term, decide which file to use
    chosen_files = {}
    # First, assign unique files for terms only found in one file
    for term, files in term_to_files.items():
        if len(files) == 1:
            chosen_files[term] = files[0]
    # For remaining terms, try to assign the file that covers the most terms
    remaining_terms = [term for term in terms if term not in chosen_files]
    if remaining_terms:
        # Find the file(s) with max coverage
        max_count = 0
        best_files = []
        for fname in ordered_files:
            count = len(file_to_terms[fname].intersection(remaining_terms))
            if count > max_count:
                max_count = count
                best_files = [fname]
            elif count == max_count and count > 0:
                best_files.append(fname)
        # Use the first best file in priority order
        if best_files:
            best_file = best_files[0]
            for term in remaining_terms:
                if term in file_to_terms[best_file]:
                    chosen_files[term] = best_file
    # For any still unassigned, use the first file in priority order that defines it
    for term in terms:
        if term not in chosen_files:
            files = term_to_files[term]
            if files:
                chosen_files[term] = files[0]
    import difflib
    def is_good_definition(defn, term=None):
        # At least 4 characters, not just a substring or abbreviation of the term, not empty, not just a prefix
        if not defn or len(defn.strip()) < 4:
            return False
        defn_l = defn.strip().lower()
        if term:
            t_l = term.lower()
            # Exclude if definition is a substring, prefix, or abbreviation of the term
            if defn_l == t_l or defn_l in t_l or t_l in defn_l or defn_l.startswith(t_l) or t_l.startswith(defn_l):
                return False
        return True

    # --- Group definitions for Levenshtein fallback ---
    group_map = {
        'math': {'algebra.json', 'linear_algebra.json', 'calculus.json', 'math.json', 'geometry.json', 'complex_numbers.json', 'probability.json', 'statistics.json', 'trigonometry.json', 'vectors.json'},
        'science': {'biology.json', 'chemistry.json', 'physics.json', 'thermodynamics.json'},
        'code': {'code_dictionary.json'},
        'definitions': {'wikipedia_defs.json'},
        'other': {'economics.json', 'finance.json', 'user_drift.json'}
    }
    def get_group(fname):
        for group, files in group_map.items():
            if fname in files:
                return group
        return 'other'

    # Replace each word in the prompt with its subject-specific definition tidbit
    prompt_tokens = re.findall(r"\b\w+\b", prompt)
    token_defs = {}
    # --- Taxonomy-aware source selection ---
    prompt_lower = prompt.lower()
    prompt_domains = set()
    # Heuristic: if a domain/subject file name is mentioned in the prompt, prefer it
    for fname in ordered_files:
        domain = fname.replace('.json','').lower()
        if domain in prompt_lower:
            prompt_domains.add(domain)

    for term in terms:
        best_tidbit = None
        best_score = -1
        best_file = None
        for fname in ordered_files:
            entry = file_term_defs.get(fname, {}).get(term)
            if entry:
                candidates = []
                if isinstance(entry, dict):
                    if 'definition' in entry and entry['definition']:
                        candidates.append(entry['definition'])
                    if 'gloss' in entry and entry['gloss']:
                        candidates.append(entry['gloss'])
                elif isinstance(entry, str):
                    candidates.append(entry)
                elif isinstance(entry, list):
                    for e in entry:
                        if isinstance(e, dict):
                            if 'definition' in e and e['definition']:
                                candidates.append(e['definition'])
                            if 'gloss' in e and e['gloss']:
                                candidates.append(e['gloss'])
                        elif isinstance(e, str):
                            candidates.append(e)
                # Blend candidates into a single tidbit (ensures consistent blending even for definitions.json)
                blended = None
                try:
                    blended = blend_definitions(candidates, subject=term) if candidates else None
                except Exception:
                    blended = None
                # If blending produced something, score that single combined tidbit; otherwise fall back to best single candidate
                if blended:
                    cand = blended
                    cand_l = cand.lower()
                    score = 0
                    domain = fname.replace('.json','').lower()
                    if domain in prompt_domains:
                        score += 10
                    score += min(len(cand_l) // 50, 2)
                    if any(w in cand_l for w in prompt_lower.split()):
                        score += 2
                    score += (len(ordered_files) - ordered_files.index(fname))
                    if score > best_score:
                        best_score = score
                        best_tidbit = cand
                        best_file = fname
                else:
                    for cand in candidates:
                        cand_l = cand.lower()
                        score = 0
                        domain = fname.replace('.json','').lower()
                        if domain in prompt_domains:
                            score += 10
                        score += min(len(cand_l) // 50, 2)
                        if any(w in cand_l for w in prompt_lower.split()):
                            score += 2
                        score += (len(ordered_files) - ordered_files.index(fname))
                        if score > best_score:
                            best_score = score
                            best_tidbit = cand
                            best_file = fname
        if best_tidbit and best_score >= 0:
            token_defs[term] = best_tidbit

    # If no token-level definitions were found, fall back to wikipedia lead summaries
    if not token_defs:
        try:
            wiki_defs_path = os.path.join(data_dir, 'wikipedia_defs.json')
            if os.path.exists(wiki_defs_path):
                with open(wiki_defs_path, 'r', encoding='utf-8') as fw:
                    wiki_defs = json.load(fw)
                # prefer noun_in_prompt, then extracted terms
                candidates = []
                if noun_in_prompt:
                    candidates.append(noun_in_prompt.lower())
                candidates.extend([t.lower() for t in terms])
                for cand in candidates:
                    if not cand:
                        continue
                    if cand in wiki_defs:
                        ent = wiki_defs[cand]
                        summary = None
                        if isinstance(ent, dict):
                            summary = ent.get('summary') or ent.get('definition') or ent.get('gloss')
                        elif isinstance(ent, str):
                            summary = ent
                        if summary:
                            s = re.split(r'(?<=[.!?])\s+', summary.strip())
                            lead = s[0] if s else summary.strip()
                            return f"{cand.capitalize()}: {lead}"
        except Exception:
            pass

    # Cross-file blending: if multiple files provide candidate definitions, blend their fragments
    associations_map = {}
    for term in list(token_defs.keys()):
        # gather candidates from all files that define this term
        candidates_all = []
        for fname in ordered_files:
            entry = file_term_defs.get(fname, {}).get(term)
            if not entry:
                continue
            if isinstance(entry, dict):
                if entry.get('definition'):
                    candidates_all.append(entry.get('definition'))
                if entry.get('gloss'):
                    candidates_all.append(entry.get('gloss'))
            elif isinstance(entry, list):
                for e in entry:
                    if isinstance(e, dict):
                        if e.get('definition'):
                            candidates_all.append(e.get('definition'))
                        if e.get('gloss'):
                            candidates_all.append(e.get('gloss'))
                    elif isinstance(e, str):
                        candidates_all.append(e)
        # collect synonyms across entries to help association extraction
        synonyms_all = []
        for fname in ordered_files:
            entry = file_term_defs.get(fname, {}).get(term)
            if not entry:
                continue
            # gather synonyms if present
            if isinstance(entry, dict):
                synonyms_all.extend(entry.get('synonyms', []))
            elif isinstance(entry, list):
                for e in entry:
                    if isinstance(e, dict):
                        synonyms_all.extend(e.get('synonyms', []))

        # if we have multiple candidates, use blend_definitions to merge fragments
        if len(candidates_all) > 1:
            try:
                blended = blend_definitions(candidates_all, subject=term)
            except Exception:
                blended = None
            if blended:
                token_defs[term] = blended
                # extract associations from last fragments (if available)
                frags = getattr(blend_definitions, '_last_fragments', [])
                assoc_counter = {}
                stop_local = set(["the","and","of","in","on","for","to","a","an","is","are","was","were","this","that"])
                for frag in frags:
                    frag_tokens = [w for w in re.findall(r"\b\w+\b", frag.lower())]
                    for w in frag_tokens:
                        if len(w) <= 3 or w in stop_local or w == term.lower():
                            continue
                        assoc_counter[w] = assoc_counter.get(w, 0) + 1
                    # consider synonyms: count a synonym if it closely matches any fragment token
                    if synonyms_all:
                        from difflib import SequenceMatcher
                        for syn in synonyms_all:
                            if not isinstance(syn, str):
                                continue
                            syn_norm = re.sub(r'[^a-z0-9]', '', syn.lower())
                            if len(syn_norm) <= 3 or syn_norm in stop_local or syn_norm == term.lower():
                                continue
                            # compute similarity to fragment tokens
                            best = 0.0
                            for tok in frag_tokens:
                                r = SequenceMatcher(None, syn_norm, tok.lower()).ratio()
                                if r > best:
                                    best = r
                            # require reasonably high similarity to count (avoid homophones/near-matches)
                            if best >= 0.80:
                                assoc_counter[syn_norm] = assoc_counter.get(syn_norm, 0) + 1
                # pick top 5 associated words
                assoc_sorted = sorted(assoc_counter.items(), key=lambda x: -x[1])[:5]
                associations_map[term] = [w for w, _ in assoc_sorted]

    # Handle personal pronoun logic: skip initial pronoun unless subject is referenced later
    personal_pronouns = {
        'i', 'me', 'my', 'mine', 'myself',
        'you', 'your', 'yours', 'yourself', 'yourselves',
        'he', 'him', 'his', 'himself',
        'she', 'her', 'hers', 'herself',
        'it', 'its', 'itself',
        'we', 'us', 'our', 'ours', 'ourselves',
        'they', 'them', 'their', 'theirs', 'themselves',
        'this', 'that', 'these', 'those',
        'who', 'whom', 'whose', 'which', 'what', 'where', 'when', 'why', 'how'
    }
    # If the first token is a personal pronoun, skip it unless it is referenced later in the prompt
    skip_first = False
    if prompt_tokens and prompt_tokens[0].lower() in personal_pronouns:
        skip_first = True
    subject_terms = set(terms)
    referenced_later = any(t.lower() in subject_terms for t in prompt_tokens[1:])

    # --- Compose response with domain lineage and siblings ---
    import random
    affirmatives = [
        "Certainly.", "Of course.", "Here's what I found:", "Affirmative.", "Let me explain:", "Absolutely.", "Here's the information:", "Sure.", "Indeed.", "As requested:", "Here's a summary:", "Let me clarify:", "Here's what the data shows:", "According to the data:", "Based on available information:", "Here's what I know:"
    ]
    response_lines = []
    if skip_first and not referenced_later:
        pass
    else:
        response_lines.append(random.choice(affirmatives))

    affirmations = [
        "Absolutely!", "You got it!", "Here's something cool:", "Let's explore:", "For sure!", "Glad you asked!", "Here's a fun fact:", "Indeed!", "With pleasure!", "Let's dive in!"
    ]
    new_fragments = []
    for t in terms:
        info = domain_info.get(t)
        definition = token_defs.get(t)
        assoc_words = associations_map.get(t, []) if 'associations_map' in locals() else []
        if info:
            sentence = random.choice(affirmations) + " "
            if info['subspecies']:
                noun_taxonomy = f"In the world of {info['kingdom']}, '{info['type']}' (sometimes called {', '.join(info['subspecies'])})"
            else:
                noun_taxonomy = f"In the world of {info['kingdom']}, '{info['type']}'"
            if definition:
                sentence += f"{noun_taxonomy} means {definition.strip('. ')}."
            else:
                sentence += f"{noun_taxonomy} is a fascinating concept!"
            new_fragments.append(sentence)
        elif definition:
            sentence = random.choice(affirmations) + f" {t.capitalize()} means {definition.strip('. ')}."
            if assoc_words:
                sentence += " Associated concepts: " + ', '.join(assoc_words) + '.'
            new_fragments.append(sentence)

    # Remove from previous_answer any fragments not related to the new prompt's terms
    import re
    def fragment_related_to_terms(fragment, terms):
        for t in terms:
            if re.search(rf"\b{re.escape(t)}\b", fragment, re.IGNORECASE):
                return True
        return False
    prev_fragments = re.split(r'(?<=[.!?])\s+', previous_answer.strip()) if previous_answer else []
    kept_prev = [frag for frag in prev_fragments if fragment_related_to_terms(frag, terms)]
    # Splice in new masterkey'd fragments
    response_lines = kept_prev + new_fragments
    response = ' '.join(response_lines)
    # Store this answer for next turn
    respond_subject_specific._last_answer = response
    return response if response.strip() else "No subject-specific definitions found for your query."
def extract_subject_modifier_pairs(text: str, defs: dict) -> list:
    """
    Extract (subject, modifier) pairs in linear order from the text.
    Subject: noun or noun phrase present in defs.
    Modifier: any sequence of adjectives/descriptive words directly before the subject.
    Returns: list of (full_phrase, subject, modifiers) in order of appearance.
    """
    import re
    tokens = re.findall(r"\b\w+\b", text)
    pairs = []
    used = set()
    n = len(tokens)
    # Try to match the longest possible phrases in defs (up to 4 words)
    i = 0
    while i < n:
        found = False
        for span in (4, 3, 2, 1):
            if i + span > n:
                continue
            phrase_tokens = tokens[i:i+span]
            phrase = ' '.join(phrase_tokens).lower()
            if phrase in defs and phrase not in RELATIONAL_EXCLUSIONS and phrase not in used:
                # Modifiers: all words before the last word in the phrase (including participles/determiners)
                modifiers = phrase_tokens[:-1]
                subject = phrase_tokens[-1]
                full_phrase = ' '.join(phrase_tokens)
                pairs.append((full_phrase, subject, modifiers))
                used.add(phrase)
                found = True
                i += span - 1
                break
        i += 1
    # Always include the main subject (first noun-like phrase in tokens that is in defs), even if preceded by modifiers/participles
    found_main = False
    for span in (4, 3, 2, 1):
        for i in range(n - span + 1):
            phrase_tokens = tokens[i:i+span]
            phrase = ' '.join(phrase_tokens).lower()
            if phrase in defs and phrase not in RELATIONAL_EXCLUSIONS and phrase not in used:
                pairs.insert(0, (' '.join(phrase_tokens), phrase_tokens[-1], phrase_tokens[:-1]))
                found_main = True
                break
        if found_main:
            break
    return pairs


# ===============================
# Natural Language Knowledge Engine
# ===============================
# Modular, maintainable, and robust code/definition engine with context, scoring, and extensibility.

# --- Imports and Global Constants ---

import os
import re
import json
import math
from typing import Any, Dict, List, Optional, Tuple
from new_natural_code_engine import NaturalCodeEngine

# Exclude generic relational words from term extraction and synonym expansion
RELATIONAL_EXCLUSIONS = {
    "part", "type", "kind", "form", "aspect", "element", "component", "piece", "portion", "section", "segment", "member", "item", "thing", "division", "fragment", "bit", "share", "slice", "sample", "example", "instance", "case", "category", "class", "group", "variety", "sort", "genre", "species", "order", "family", "set", "subset", "subgroup", "variation", "modification", "version", "model", "pattern", "style", "manner", "mode", "means", "method", "way", "approach", "system", "structure", "framework", "arrangement", "composition", "configuration", "constitution", "makeup", "fabric", "texture", "substance", "material", "matter", "object", "entity", "unit"
}

SAFE_GLOBALS = {"math": math, "__builtins__": {}}


def score_sentence_against_knowledge(sentence: str, knowledge: dict) -> float:
    """
    Score a sentence for overlap with known knowledge/definitions.
    Inverted scoring: 1 - (unknown words / total words).
    """
    words = [w.strip('.,!?;:').lower() for w in sentence.split() if w.strip('.,!?;:')]
    if not words:
        return 1.0
    known_words = set(
        w
        for info in knowledge.values()
        for definition in info.get('definitions', [])
        for w in definition.lower().split()
    ) | set(
        w
        for info in knowledge.values()
        for _, rel_val in info.get('relations', [])
        for w in str(rel_val).lower().split()
    )
    unknown_count = sum(1 for w in words if w not in known_words)
    score = 1.0 - (unknown_count / len(words))
    return max(0.0, min(1.0, score))

def resolve_pronouns(sentence: str, context: List[str]) -> str:
    """
    Replace third-person pronouns in a sentence with the main subject from recent context.
    """
    pronouns = {"he", "she", "it", "they", "them", "his", "her", "their", "its"}
    tokens = sentence.split()
    referent = None
    if context:
        last = context[-1]
        stopwords = {"the", "a", "an", "of", "to", "in", "for", "on", "with", "at", "by", "from", "up", "about", "into", "over", "after", "under", "again", "further", "then", "once", "here", "there", "when", "where", "why", "how", "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very", "s", "t", "can", "will", "just", "don", "should", "now"}
        last_tokens = [w for w in last.split() if w.lower() not in stopwords and w.lower() not in pronouns]
        if last_tokens:
            referent = last_tokens[0]
    resolved = [referent if t.lower() in pronouns and referent else t for t in tokens]
    return ' '.join(resolved)
# Convenience function to load the full unified knowledge index
def get_full_knowledge() -> dict:
    """Load and return the full unified knowledge index from all data/*.json files."""
    return load_all_knowledge("data")
def normalize_key(key: str) -> str:
    """Normalize a key for matching: remove interrogatives, underscores, hyphens, and extra spaces."""
    interrogatives = ['what', 'which', 'who', 'whom', 'whose', 'when', 'where', 'why', 'how']
    key = key.replace('_', ' ').replace('-', ' ').lower()
    key = key.replace(' of ', ' ')
    key = ' '.join(key.split())
    words = [w for w in key.split() if w not in interrogatives]
    return ' '.join(words)

def singularize(word: str) -> str:
    """Convert simple English plurals to singular."""
    if word.endswith('ies'):
        return word[:-3] + 'y'
    if word.endswith('es'):
        return word[:-2]
    if word.endswith('s') and not word.endswith('ss'):
        return word[:-1]
    return word

def key_to_word_set(key: str) -> set:
    """Return set of words in key, including singularized forms."""
    words = normalize_key(key).split()
    return set(words + [singularize(w) for w in words])
# eng9.py


import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

# Import NaturalCodeEngine
from new_natural_code_engine import NaturalCodeEngine

# ---------------------------------------------------------------------
# Safe evaluation context for math expressions and exec lambdas
# ---------------------------------------------------------------------

SAFE_GLOBALS = {
    "math": math,
    "__builtins__": {}
}


# ---------------------------------------------------------------------
# Loading and normalization
# ---------------------------------------------------------------------

import json
import os



def load_all_knowledge(directory: str = "data") -> dict:
    """
    Recursively load all JSON files in the directory and subdirectories.
    Build a unified knowledge index capturing definitions, relationships, formulas, exec, and cross-references.
    Returns: dict of term -> { 'definitions': [...], 'relations': [...], 'formulas': [...], 'exec': [...], 'sources': [...] }
    """
    knowledge = {}
    for root, _, files in os.walk(directory):
        for filename in files:
            if filename.endswith(".json"):
                path = os.path.join(root, filename)
                with open(path, "r", encoding="utf-8") as f:
                    try:
                        data = json.load(f)
                    except Exception as e:
                        print(f"Error loading {path}: {e}")
                        continue
                    if isinstance(data, dict):
                        for k, v in data.items():
                            entry = knowledge.setdefault(k, {'definitions': [], 'relations': [], 'formulas': [], 'exec': [], 'sources': set()})
                            # Definitions
                            if isinstance(v, str):
                                entry['definitions'].append(v)
                            elif isinstance(v, dict):
                                if 'definition' in v:
                                    entry['definitions'].append(v['definition'])
                                if 'gloss' in v:
                                    entry['definitions'].append(v['gloss'])
                                # Relations
                                for rel_key in ['is a', 'type of', 'class of', 'category of', 'related to', 'see also', 'synonyms']:
                                    if rel_key in v:
                                        rels = v[rel_key]
                                        if isinstance(rels, str):
                                            entry['relations'].append((rel_key, rels))
                                        elif isinstance(rels, list):
                                            for rel in rels:
                                                entry['relations'].append((rel_key, rel))
                                # Formulas
                                if 'formula' in v:
                                    entry['formulas'].append(v['formula'])
                                # Executable code
                                if 'exec' in v:
                                    entry['exec'].append(v['exec'])
                            elif isinstance(v, list):
                                for item in v:
                                    if isinstance(item, dict):
                                        if 'definition' in item:
                                            entry['definitions'].append(item['definition'])
                                        if 'gloss' in item:
                                            entry['definitions'].append(item['gloss'])
                                        for rel_key in ['is a', 'type of', 'class of', 'category of', 'related to', 'see also', 'synonyms']:
                                            if rel_key in item:
                                                rels = item[rel_key]
                                                if isinstance(rels, str):
                                                    entry['relations'].append((rel_key, rels))
                                                elif isinstance(rels, list):
                                                    for rel in rels:
                                                        entry['relations'].append((rel_key, rel))
                                        if 'formula' in item:
                                            entry['formulas'].append(item['formula'])
                                        if 'exec' in item:
                                            entry['exec'].append(item['exec'])
                            entry['sources'].add(filename)
                    elif isinstance(data, list):
                        base_name = os.path.splitext(os.path.basename(path))[0]
                        entry = knowledge.setdefault(base_name, {'definitions': [], 'relations': [], 'formulas': [], 'exec': [], 'sources': set()})
                        for item in data:
                            if isinstance(item, dict):
                                if 'definition' in item:
                                    entry['definitions'].append(item['definition'])
                                if 'gloss' in item:
                                    entry['definitions'].append(item['gloss'])
                                for rel_key in ['is a', 'type of', 'class of', 'category of', 'related to', 'see also', 'synonyms']:
                                    if rel_key in item:
                                        rels = item[rel_key]
                                        if isinstance(rels, str):
                                            entry['relations'].append((rel_key, rels))
                                        elif isinstance(rels, list):
                                            for rel in rels:
                                                entry['relations'].append((rel_key, rel))
                                if 'formula' in item:
                                    entry['formulas'].append(item['formula'])
                                if 'exec' in item:
                                    entry['exec'].append(item['exec'])
                        entry['sources'].add(filename)
                    else:
                        print(f"Warning: {path} is not a dict or list. Skipping.")
    # Convert sources to list for serialization
    for v in knowledge.values():
        v['sources'] = list(v['sources'])
    return knowledge

def normalize_defs(defs: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Normalize all entries so they become:
    term: [ { gloss: "...", formula: ..., exec: ... } ]
    """
    normalized = {}

    for term, entry in defs.items():

        # Case 1: entry is a string → treat as gloss
        if isinstance(entry, str):
            normalized[term] = [
                {
                    "gloss": entry
                }
            ]
            continue

        # Case 2: entry is a dict → wrap in list
        if isinstance(entry, dict):
            normalized[term] = [entry]
            continue

        # Case 3: entry is a list → ensure each element is a dict
        if isinstance(entry, list):
            fixed_list = []
            for item in entry:
                if isinstance(item, str):
                    fixed_list.append({"gloss": item})
                elif isinstance(item, dict):
                    fixed_list.append(item)
            normalized[term] = fixed_list
            continue

        # Fallback: ignore weird types
        normalized[term] = []

    return normalized

def load_all_definitions() -> Dict[str, List[Dict[str, Any]]]:
    """
    Load core definitions and math definitions,
    merge them into a single normalized dictionary.
    """
    # Use the new unified loader, but extract only definitions for legacy compatibility
    knowledge = load_all_knowledge("data")
    defs = {}
    for term, info in knowledge.items():
        # Prefer structured definitions
        if info['definitions']:
            defs[term] = [{"gloss": d} for d in info['definitions']]
    return normalize_defs(defs)


# ---------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------


import ast
import operator as op

def try_eval_expression(text: str, variables: dict = None) -> Optional[float]:
    """
    Evaluate a math expression with variables and correct order of operations.
    Supports: +, -, *, /, **, %, parentheses, and variables.
    Example: '2*x + 3*y', variables={'x': 4, 'y': 5}
    """
    if not text or not isinstance(text, str):
        return None
    expr = text.strip().replace('^', '**')
    variables = variables or {}
    # Supported operators
    allowed_operators = {
        ast.Add: op.add,
        ast.Sub: op.sub,
        ast.Mult: op.mul,
        ast.Div: op.truediv,
        ast.Pow: op.pow,
        ast.Mod: op.mod,
        ast.USub: op.neg,
        ast.UAdd: op.pos
    }
    def eval_node(node):
        if isinstance(node, ast.Num):
            return node.n
        elif isinstance(node, ast.BinOp):
            left = eval_node(node.left)
            right = eval_node(node.right)
            return allowed_operators[type(node.op)](left, right)
        elif isinstance(node, ast.UnaryOp):
            operand = eval_node(node.operand)
            return allowed_operators[type(node.op)](operand)
        elif isinstance(node, ast.Name):
            if node.id in variables:
                return variables[node.id]
            else:
                raise ValueError(f"Unknown variable: {node.id}")
        else:
            raise TypeError(f"Unsupported expression: {ast.dump(node)}")
    try:
        parsed = ast.parse(expr, mode='eval')
        return eval_node(parsed.body)
    except Exception:
        return None


def parse_math_exec(defs: Dict[str, List[Dict[str, Any]]], term: str, *args: float) -> Optional[Any]:
    """
    Execute the math function stored in the 'exec' field of a definition.
    Returns the result on success, or None on error or if not executable.
    """
    entry = defs.get(term)
    if not entry:
        return None

    sense = entry[0]
    if isinstance(sense, dict):
        code = sense.get("exec")
    else:
        code = None
    if not code:
        return None

    try:
        fn = eval(code, SAFE_GLOBALS, {})
    except Exception:
        return None

    try:
        return fn(*args)
    except Exception:
        return None


# ---------------------------------------------------------------------
# Operator precedence helpers
# ---------------------------------------------------------------------
def get_operator_precedence(op: str) -> int:
    """
    Return precedence level for a given operator string.
    Higher number = higher precedence.
    """
    precedence = {
        '**': 4,
        '^': 4,
        '*': 3,
        '/': 3,
        '//': 3,
        '%': 3,
        '+': 2,
        '-': 2,
    }
    return precedence.get(op, 0)


# ---------------------------------------------------------------------
# Sense selection and definition building
# ---------------------------------------------------------------------

def choose_sense(senses: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Choose a single sense from a list.
    For now, select the first sense.
    """
    if not senses or not isinstance(senses, list) or len(senses) == 0:
        return {}
    return senses[0]


def build_definition_style(term: str, core_phrase: str, detail_phrases: List[str], formula: Optional[str] = None) -> str:
    """
    Build a clean academic definition sentence, optionally including a formula.
    Example:
    "addition is the process of combining quantities to produce a total.
     The formula is a + b."
    """
    core_phrase = core_phrase.strip()
    if not core_phrase:
        # print("[DEBUG] Fallback: core_phrase is empty, using 'a mathematical concept'.")
        core_phrase = "a mathematical concept"

    # Simple article handling: a / an / the
    if not re.match(r"\b(a|an|the)\b ", core_phrase):
        if core_phrase[0].lower() in "aeiou":
            core_phrase = "an " + core_phrase
        else:
            core_phrase = "a " + core_phrase

    detail_phrases = [d.strip() for d in detail_phrases if d.strip()]

    if detail_phrases:
        if len(detail_phrases) == 1:
            tail = detail_phrases[0]
        else:
            tail = ", ".join(detail_phrases[:-1]) + ", and " + detail_phrases[-1]
        base = f"{term} is {core_phrase} that {tail}."
    else:
        base = f"{term} is {core_phrase}."

    if formula:
        base += f" The formula is {formula}."

    return base


def split_gloss(gloss: str) -> Tuple[str, List[str]]:
    """
    Split a gloss into a core phrase and detail phrases.
    The first clause becomes the core; the rest become details.
    """
    text = gloss.strip()
    if not text:
        return "a mathematical concept", []

    # Split on basic separators: semicolons or periods
    parts = re.split(r"[;\.]", text)
    parts = [p.strip() for p in parts if p.strip()]

    if not parts:
        return text, []

    # Brute-force: combine parts until a full sentence or closed quote is detected
    core = parts[0]
    quote_chars = ['"', "'", "“", "”"]
    def count_quotes(s, q):
        return s.count(q)
    def is_quote_open(s):
        for q in quote_chars:
            if count_quotes(s, q) % 2 == 1:
                return q
        return None

    i = 1
    while i < len(parts):
        open_q = is_quote_open(core)
        # If in a quote, keep adding until quote is closed
        if open_q:
            core += '. ' + parts[i]
            i += 1
            continue
        # If not in a quote, check for sentence-ending punctuation
        if core and core[-1] in '.!?':
            break
        # If next part starts with a lowercase letter, likely a continuation
        if parts[i] and parts[i][0].islower():
            core += '. ' + parts[i]
            i += 1
            continue
        # Otherwise, treat as end of core
        break
    details = parts[i:]
    return core, details


# ---------------------------------------------------------------------
# Main respond function
# ---------------------------------------------------------------------



# --- Relational exclusions (generic words and synonyms) ---
relational_exclusions = {"part", "type", "kind", "form", "aspect", "element", "component", "piece", "portion", "section", "segment", "member", "item", "thing", "division", "fragment", "bit", "share", "slice", "sample", "example", "instance", "case", "category", "class", "group", "variety", "sort", "genre", "species", "order", "family", "set", "subset", "subgroup", "variation", "modification", "version", "model", "pattern", "style", "manner", "mode", "means", "method", "way", "approach", "system", "structure", "framework", "arrangement", "composition", "configuration", "constitution", "makeup", "fabric", "texture", "substance", "material", "matter", "object", "entity", "unit"}

import string
import re

def extract_master_key(raw: str) -> Optional[str]:
    """Extract explicit master key from prompt (e.g. 'what is X', 'what does X mean')."""
    m = re.match(r"what is ([\w\-\_ ]+)[\?\.]?", raw.lower())
    if m:
        val = m.group(1).strip()
        # strip leading determiners
        val = re.sub(r'^(?:a|an|the)\s+', '', val, flags=re.IGNORECASE)
        return val
    m = re.match(r"what does ([\w\-\_ ]+) mean[\?\.]?", raw.lower())
    if m:
        val = m.group(1).strip()
        val = re.sub(r'^(?:a|an|the)\s+', '', val, flags=re.IGNORECASE)
        return val
    return None

def strip_punct(word: str) -> str:
    return word.rstrip(string.punctuation)

def extract_terms(text: str) -> List[str]:
    """Extract relevant terms from prompt.
    Prioritize explicit question patterns ("what is X", "define X", "difference between X and Y", "how does X differ from Y").
    Fall back to multi-word phrase matching (up to 4 words) and capitalized/non-stopword heuristics.
    """
    import re
    text = text.strip()
    # Quick pattern matches for common question forms
    patterns = [
        r"what(?:'s| is) the difference between\s+(.+?)\s+and\s+(.+?)\??$",
        r"how does\s+(.+?)\s+differ from\s+(.+?)\??$",
        r"are\s+(.+?)\s+and\s+(.+?)\s+(?:the same|equivalent|equal)\??$",
        r"give\s+(?:me\s+)?(?:a|the)?\s*(?:brief\s+|short\s+)?definition of\s+(.+?)\??$",
        r"what(?:'s| is)\s+(.+?)\??$",
        r"define\s+(.+?)\??$",
        r"describe\s+(.+?)\??$",
        r"give\s+(?:me\s+)?(?:a|the)?\s*(?:brief\s+|short\s+)?description of\s+(.+?)\??$",
        r"what are\s+(.+?)\??$",
        r"what\s+is\s+a\s+(.+?)\??$",
        r"what\s+is\s+an\s+(.+?)\??$",
        r"difference between\s+(.+?)\s+and\s+(.+?)\??$",
        r"compare\s+(.+?)\s+and\s+(.+?)\??$",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            groups = [g for g in m.groups() if g]
            # return each captured group as a term (normalize and singularize)
            out = []
            for g in groups:
                phrase = re.sub(r"[^A-Za-z0-9\s'-]", "", g).strip()
                # strip leading determiners like 'a', 'an', 'the'
                phrase = re.sub(r'^(?:a|an|the)\s+', '', phrase, flags=re.IGNORECASE)
                # remove trailing request-modifiers like 'in one sentence', 'in 10 words', 'briefly'
                phrase = re.sub(r"\s+in\s+\d+\s+words$", "", phrase, flags=re.IGNORECASE)
                phrase = re.sub(r"\s+in\s+one\s+sentence\.?$", "", phrase, flags=re.IGNORECASE)
                phrase = re.sub(r"\s+in\s+one\s+paragraph\.?$", "", phrase, flags=re.IGNORECASE)
                phrase = re.sub(r"\s+briefly\.?$", "", phrase, flags=re.IGNORECASE)
                phrase = re.sub(r"\s+in\s+short\.?$", "", phrase, flags=re.IGNORECASE)
                if not phrase:
                    continue
                # keep multi-word phrases up to 4 words
                words = phrase.split()
                if len(words) > 4:
                    words = words[:4]
                cand = ' '.join(words)
                cand = cand.lower()
                cand = ' '.join(singularize(w) for w in cand.split())
                out.append(cand)
            if out:
                return out

    # Otherwise, fall back to token heuristics (prefer multi-word phrases up to 4 words)
    tokens = re.findall(r"\b\w+\b", text)
    lower_tokens = [t.lower() for t in tokens]
    interrogatives = {'what','which','who','whom','whose','when','where','why','how'}
    personal_pronouns = {
        'i', 'me', 'my', 'mine', 'myself',
        'you', 'your', 'yours', 'yourself', 'yourselves',
        'he', 'him', 'his', 'himself',
        'she', 'her', 'hers', 'herself',
        'it', 'its', 'itself',
        'we', 'us', 'our', 'ours', 'ourselves',
        'they', 'them', 'their', 'theirs', 'themselves',
        'this', 'that', 'these', 'those',
        'who', 'whom', 'whose', 'which', 'what', 'where', 'when', 'why', 'how'
    }
    seen = set()
    n = len(tokens)
    candidates = []
    # Try longest spans first (4,3,2,1)
    for span in (4, 3, 2, 1):
        for i in range(0, n - span + 1):
            span_tokens = tokens[i:i+span]
            low_span = [t.lower() for t in span_tokens]
            # skip spans that are all stop/pronoun words
            if all(w in personal_pronouns or not w.isalpha() for w in low_span):
                continue
            phrase = ' '.join(span_tokens).strip()
            norm = ' '.join(singularize(w.lower()) for w in phrase.split())
            norm = strip_punct(norm)
            if norm and norm not in seen and not any(r in norm for r in RELATIONAL_EXCLUSIONS) and not any(w in interrogatives for w in low_span):
                seen.add(norm)
                candidates.append(norm)
    # If we found nothing, as a last resort, return the longest alphanumeric substring
    if not candidates:
        phrase = re.sub(r"[^A-Za-z0-9\s]", "", text).strip()
        if phrase:
            words = phrase.split()
            if len(words) > 4:
                words = words[:4]
            cand = ' '.join(singularize(w.lower()) for w in words)
            return [cand]
    return candidates

def lookup_definition(defs: Dict[str, Any], term: str) -> Optional[Any]:
    """Find the best-matching definition entry for a term (normalized)."""
    norm_term = normalize_key(term)
    for k in defs:
        norm_k = normalize_key(k)
        if norm_k == norm_term:
            return defs[k]
    return None


def respond(defs: Dict[str, List[Dict[str, Any]]], text: str) -> str:
    global _last_evidence

    raw = text.strip()
    if not raw:
        return "I need something to define."

    # Context and pronoun resolution (preserve previous behavior)
    if not hasattr(respond, "_context"):
        respond._context = []
    context = respond._context
    resolved_raw = resolve_pronouns(raw, context)
    context.append(raw)
    if len(context) > 10:
        context.pop(0)

    # Initialize spaCy (cached on the function to avoid repeated loads)
    if not hasattr(respond, "_nlp"):
        try:
            import spacy
            respond._nlp = spacy.load('en_core_web_sm')
        except Exception:
            respond._nlp = None
    nlp = respond._nlp

    # Extract topics using spaCy noun chunks and nouns/proper nouns
    topics = []
    if nlp:
        doc = nlp(resolved_raw)
        seen = set()
        for nc in doc.noun_chunks:
            lem = nc.lemma_.lower().strip()
            if lem and lem not in seen:
                seen.add(lem)
                topics.append(lem)
        for tok in doc:
            if tok.pos_ in ("NOUN", "PROPN"):
                lem = tok.lemma_.lower().strip()
                if lem and lem not in seen:
                    seen.add(lem)
                    topics.append(lem)
    # Fallback to older extractor when spaCy not available or no topics found
    if not topics:
        master_key = extract_master_key(resolved_raw)
        if master_key:
            topics = [strip_punct(master_key)]
        else:
            topics = extract_terms(resolved_raw)

    # Normalize topics: strip determiners, interrogatives, and relational exclusions
    norm_topics = []
    interrogatives_set = {'what','which','who','whom','whose','when','where','why','how'}
    for t in topics:
        if not t:
            continue
        tl = t.lower().strip()
        tl = re.sub(r'^(?:a|an|the)\s+', '', tl)
        tl = tl.strip()
        if not tl:
            continue
        if tl in interrogatives_set:
            continue
        if any(r in tl for r in RELATIONAL_EXCLUSIONS):
            # avoid generic relational words
            continue
        # singularize final token words
        tl = ' '.join(singularize(w) for w in tl.split())
        tl = strip_punct(tl)
        if tl and tl not in norm_topics:
            norm_topics.append(tl)
    topics = norm_topics

    # Helper: detect whether the user's prompt is explicitly a comparison
    def is_comparison_query(q: str) -> bool:
        ql = q.lower()
        # explicit comparison keywords/phrases that clearly indicate a comparison intent
        explicit = [r"\bdifference between\b", r"\bdiffer from\b", r"\bcompare\b", r"\bversus\b", r"\b vs \b", r"\bvs\.\b"]
        for p in explicit:
            if re.search(p, ql):
                return True

        # handle 'are X and Y' / 'do X and Y' only when we can detect two noun-like topics
        # use the already-extracted `topics` list (if available) or fall back to simple token scan
        topic_count = 0
        try:
            topic_count = len([t for t in topics if t and isinstance(t, str)])
        except Exception:
            # fallback: count simple noun tokens separated by 'and' or ','
            m = re.findall(r"\b(\w+)\b", ql)
            topic_count = len(m)

        if topic_count >= 2 and (re.search(r"\bare\s+", ql) or re.search(r"\bdo\s+", ql) or re.search(r"\bcompare\b", ql)):
            # ensure there is an 'and' or ',' or 'vs' connecting two topics
            if re.search(r"\band\b", ql) or re.search(r",", ql) or re.search(r"\bvs\b|\bversus\b", ql):
                return True

        # questions like 'which is bigger: X or Y' should be treated as comparison
        if re.search(r"\bor\b", ql) and re.search(r"which\b", ql):
            return True

        return False

    # Helper: get fragments from a definition entry
    def fragments_from_entry(entry):
        frags = []
        if isinstance(entry, list):
            for e in entry:
                if isinstance(e, dict):
                    for k in ("definition", "text", "gloss", "desc"):
                        if k in e and isinstance(e[k], str):
                            frags.append(e[k])
                            break
                elif isinstance(e, str):
                    frags.append(e)
        elif isinstance(entry, dict):
            for k in ("definition", "text", "gloss", "desc"):
                if k in entry and isinstance(entry[k], str):
                    frags.append(entry[k])
                    break
        elif isinstance(entry, str):
            frags.append(entry)
        return [f for f in frags if f and f.strip()]

    # If the user explicitly asked for a definition ("define X", "give definition of X", "what is the definition of X"),
    # return direct definition(s) rather than attempting a comparative narrative.
    def parse_definition_request(q: str) -> list:
        ql = q.strip()
        patterns = [
            r"^define\s+(.+?)\s*\??$",
            r"^give(?: me| a| an| the)?(?: brief| short| one-sentence| concise)?\s+definition(?:s)?(?: of)?\s+(.+?)\s*\.?$",
            r"what(?:'s| is) the definition of\s+(.+?)\s*\??$",
            r"what(?:'s| is) definition of\s+(.+?)\s*\??$",
            r"^definitions? of\s+(.+?)\s*\.?$",
        ]
        for p in patterns:
            m = re.search(p, ql, flags=re.IGNORECASE)
            if m:
                part = m.group(1)
                # strip trailing request modifiers like 'in one sentence', 'in 10 words', 'briefly'
                part = re.sub(r"\s+in\s+\d+\s+words\.?$", "", part, flags=re.IGNORECASE)
                part = re.sub(r"\s+in\s+one\s+sentence\.?$", "", part, flags=re.IGNORECASE)
                part = re.sub(r"\s+in\s+one\s+paragraph\.?$", "", part, flags=re.IGNORECASE)
                part = re.sub(r"\s+briefly\.?$", "", part, flags=re.IGNORECASE)
                part = re.sub(r"\s+in\s+short\.?$", "", part, flags=re.IGNORECASE)
                # split on ' and ' or commas to support multiple subjects
                parts = re.split(r"\s*,\s*|\s+and\s+|\s+or\s+", part)
                cleaned = []
                for s in parts:
                    s2 = re.sub(r"[^A-Za-z0-9\s'-]", '', s).strip()
                    s2 = re.sub(r'^(?:a|an|the)\s+', '', s2, flags=re.IGNORECASE).strip()
                    if not s2:
                        continue
                    # keep up to 4 words for multi-word subjects
                    words = s2.split()[:4]
                    words = [singularize(w.lower()) for w in words]
                    cleaned.append(' '.join(words))
                if cleaned:
                    return cleaned
        return []

    # Check for explicit definition requests and short-circuit to direct definitions
    try:
        def_reqs = parse_definition_request(resolved_raw)
        if def_reqs:
            lines = []
            for subj in def_reqs:
                # lookup in provided defs first
                ent = lookup_definition(defs, subj)
                frags = fragments_from_entry(ent) if ent else []
                blended = None
                try:
                    if frags:
                        blended = blend_definitions(frags, subject=subj)
                except Exception:
                    blended = None
                if not blended:
                    # try wikipedia fallback
                    try:
                        wiki_path = os.path.join(os.path.dirname(__file__), 'data', 'wikipedia_defs.json')
                        if os.path.exists(wiki_path):
                            with open(wiki_path, 'r', encoding='utf-8') as wf:
                                wdefs = json.load(wf)
                            ent2 = wdefs.get(subj) or wdefs.get(subj.lower())
                            if ent2:
                                blended = ent2.get('summary') if isinstance(ent2, dict) else (ent2 if isinstance(ent2, str) else None)
                                if blended:
                                    # take lead sentence
                                    blended = re.split(r'(?<=[.!?])\s+', blended.strip())[0]
                    except Exception:
                        blended = blended
                if blended:
                    lines.append(f"{subj.capitalize()}: {blended}")
                else:
                    lines.append(f"{subj.capitalize()}: (no definition found)")
            # expose minimal evidence for these direct-definition responses
            try:
                _last_evidence = {'direct_definition_request': True, 'subjects': def_reqs}
            except Exception:
                pass
            return '\n'.join(lines)
    except Exception:
        pass

    stop_small = set(["the","and","of","in","on","for","to","with","a","an","is","are","was","were","this","that"])

    term_blends = {}
    term_token_sets = {}
    term_raw_fragments = {}
    found_terms = []
    for t in topics:
        entry = lookup_definition(defs, t)
        if not entry:
            # try singular/plural variants
            alt = singularize(t)
            entry = lookup_definition(defs, alt) if alt != t else None
        if not entry:
            continue
        frags = fragments_from_entry(entry)
        if not frags:
            continue
        # Blend fragments for this term
        blended = blend_definitions(frags, subject=t)
        term_blends[t] = blended
        found_terms.append(t)
        # Use the last_fragments recorded by blend_definitions for token sets
        raw_frags = []
        try:
            raw_frags = blend_definitions._last_fragments or []
        except Exception:
            raw_frags = frags
        toks = set()
        for s in raw_frags:
            for w in re.findall(r"\b[a-zA-Z]+\b", s.lower()):
                if w in stop_small:
                    continue
                toks.add(w)
        term_token_sets[t] = toks
        term_raw_fragments[t] = raw_frags

    if not term_blends:
        return "I couldn't find matching definitions for the topics in your prompt."

    # If this is NOT a comparison query, prefer returning a concise single-term
    # summary instead of attempting cross-term comparison even when multiple
    # related entries are present.
    try:
        if not is_comparison_query(resolved_raw):
            # choose primary term: prefer explicit master key, then first topic, then first found term
            primary = None
            try:
                mk = extract_master_key(resolved_raw)
            except Exception:
                mk = None
            if mk and mk in found_terms:
                primary = mk
            elif topics:
                primary = topics[0]
            elif found_terms:
                primary = found_terms[0]
            if primary:
                blended_primary = term_blends.get(primary)
                if blended_primary:
                    return blended_primary
                # fallback to wikipedia summary if available
                try:
                    wiki_path = os.path.join(os.path.dirname(__file__), 'data', 'wikipedia_defs.json')
                    if os.path.exists(wiki_path):
                        with open(wiki_path, 'r', encoding='utf-8') as wf:
                            wdefs = json.load(wf)
                        ent = wdefs.get(primary) or wdefs.get(primary.lower())
                        if ent:
                            summ = ent.get('summary') if isinstance(ent, dict) else (ent if isinstance(ent, str) else None)
                            if summ:
                                s = re.split(r'(?<=[.!?])\s+', summ.strip())
                                return s[0] if s else summ
                except Exception:
                    pass
    except Exception:
        pass

    # Build response: keep only comparison output (omit per-term blended lines)
    out_lines = []

    # Pairwise analysis: predicate-aware comparisons when possible, else token intersections
    # Collect all predicate phrases (verb + prep + object) from the query
    predicate_phrases = []
    predicate_tokens = []
    evidence_pair = None
    pred_stop = {'do','does','did','move','moves','moved','be','is','are','have','has','by','with','using','use'}
    if 'nlp' in locals() and nlp:
        try:
            docq = nlp(resolved_raw)
            for tok in docq:
                # prefer the ROOT verb or a real verb that isn't a light auxiliary
                if tok.dep_ == 'ROOT' or (tok.pos_ == 'VERB' and tok.lemma_.lower() not in pred_stop):
                    toks = [tok.lemma_.lower()]
                    for child in tok.children:
                        if child.dep_ == 'prep':
                            toks.append(child.lemma_.lower())
                            for g in child.children:
                                if g.dep_ in ('pobj', 'dobj', 'obj'):
                                    toks.append(g.lemma_.lower())
                        if child.dep_ in ('dobj', 'pobj', 'obj'):
                            toks.append(child.lemma_.lower())
                    phrase = ' '.join(toks)
                    predicate_phrases.append(phrase)
                    predicate_tokens.append(set(toks))
        except Exception:
            predicate_phrases = []
            predicate_tokens = []
    else:
        # simple regex fallback: capture only common predicate verbs + optional 'by X'
        verb_whitelist = {'breathe','move','eat','contain','have','use','run','fly','swim','purr','contain','include'}
        for m in re.finditer(r"\b(\w+)(?:\s+by\s+(\w+))?\b", resolved_raw, re.I):
            verb = m.group(1).lower()
            obj = m.group(2).lower() if m.group(2) else None
            if verb in verb_whitelist:
                toks = [verb]
                if obj:
                    toks.extend(['by', obj])
                predicate_phrases.append(' '.join(toks))
                predicate_tokens.append(set(toks))

    if len(found_terms) >= 2:
        a = found_terms[0]
        b = found_terms[1]
        ta = term_token_sets.get(a, set())
        tb = term_token_sets.get(b, set())

        if predicate_phrases:
            # filter out generic predicate phrases that contain only stop words
            filtered = []
            for p_phrase, p_tokens in zip(predicate_phrases, predicate_tokens):
                core = set([p for p in p_tokens if p not in pred_stop])
                if core:
                    filtered.append((p_phrase, p_tokens))
            if not filtered:
                # fall back to original list if filtering removed everything
                filtered = list(zip(predicate_phrases, predicate_tokens))

            matched_any = False
            for p_phrase, p_tokens in filtered:
                pred_stop = {'do','does','did','move','moves','moved','be','is','are','have','has','by','with','using','use'}
                core = set([p for p in p_tokens if p not in pred_stop])

                def tokens_match(tokset, core_tokens, all_tokens):
                    if not tokset:
                        return False
                    if core_tokens:
                        if core_tokens & tokset:
                            return True
                        for p in core_tokens:
                            if p.rstrip('e') in tokset or (p + 's') in tokset:
                                return True
                        return False
                    if all_tokens & tokset:
                        return True
                    for p in all_tokens:
                        if p.rstrip('e') in tokset or (p + 's') in tokset:
                            return True
                    return False

                has_a = tokens_match(ta, core, p_tokens)
                has_b = tokens_match(tb, core, p_tokens)

                # Collect supporting / unsupporting fragments for each term
                def supporting_frags(term):
                    frs = term_raw_fragments.get(term, [])
                    sup = [f for f in frs if any((c in f.lower()) for c in (core or p_tokens))]
                    return sup

                def unsupporting_frags(term):
                    frs = term_raw_fragments.get(term, [])
                    neg_words = ('not', "n't", 'no', 'never', 'cannot', 'without')
                    uns = [f for f in frs if any(n in f.lower() for n in neg_words) and any((p in f.lower()) for p in p_tokens)]
                    return uns

                sup_a = supporting_frags(a)
                sup_b = supporting_frags(b)
                uns_a = unsupporting_frags(a)
                uns_b = unsupporting_frags(b)

                # record evidence for external inspection
                evidence_pair = {
                    'a': a,
                    'b': b,
                    'predicate_phrase': p_phrase,
                    'predicate_tokens': list(p_tokens),
                    'supporting_a': list(sup_a),
                    'supporting_b': list(sup_b),
                    'unsupporting_a': list(uns_a),
                    'unsupporting_b': list(uns_b),
                    'has_a': bool(has_a),
                    'has_b': bool(has_b),
                }

                if has_a and has_b:
                    # include brief supporting fragments if available
                    if sup_a or sup_b:
                        sa = ("; ".join(sup_a[:2])) if sup_a else "(no direct supporting fragments)"
                        sb = ("; ".join(sup_b[:2])) if sup_b else "(no direct supporting fragments)"
                        out_lines.append(f"{a.capitalize()} and {b.capitalize()} both clearly {p_phrase}. Supporting: {a.capitalize()}: {sa}; {b.capitalize()}: {sb}.")
                    else:
                        out_lines.append(f"{a.capitalize()} and {b.capitalize()} both clearly {p_phrase}.")
                    matched_any = True
                    break
            if not matched_any:
                if len(predicate_phrases) == 1:
                    out_lines.append(f"{a.capitalize()} and {b.capitalize()} do not clearly both {predicate_phrases[0]}.")
                else:
                    joined = ' or '.join(predicate_phrases)
                    out_lines.append(f"{a.capitalize()} and {b.capitalize()} do not clearly both {joined}.")

    # expose last evidence for inspection (supporting / unsupporting fragments)
    try:
        _last_evidence = {
            'found_terms': found_terms,
            'term_raw_fragments': term_raw_fragments,
            'predicate_phrases': predicate_phrases,
            'evidence_pair': evidence_pair,
            'out_lines': out_lines,
        }
    except Exception:
        _last_evidence = None

    return "\n".join(out_lines)


# ---------------------------------------------------------------------
# Simple CLI loop for manual testing
# ---------------------------------------------------------------------
# ---------------------------------------------------------------------
# Simple CLI loop for manual testing
# ---------------------------------------------------------------------

def test_blend_fragments():
    """Test and print the last sentence fragments used in blending."""
    if hasattr(blend_definitions, '_last_fragments'):
        print("Fragments used in last blend:")
        for i, frag in enumerate(blend_definitions._last_fragments, 1):
            print(f"Fragment {i}: {frag}")
    else:
        print("No fragments stored yet.")


def respond_with_evidence(defs: Dict[str, List[Dict[str, Any]]], text: str, verbose: bool = False):
    """Call `respond()` and return structured evidence.

    - If `verbose` is True, return the sentence string (same as `respond`).
    - If `verbose` is False, return a dict: `{'response': str, 'evidence': dict_or_None}`.
    This keeps `respond()` unchanged while providing a non-breaking API.
    """
    # call existing responder (it populates module-level `_last_evidence`)
    sentence = respond(defs, text)
    evidence = globals().get('_last_evidence')
    # If this was a direct definition request, and verbose requested, prefer the direct responder output
    try:
        if verbose and evidence and isinstance(evidence, dict) and evidence.get('direct_definition_request'):
            return sentence
    except Exception:
        pass
    if verbose:
        # prefer returning the learner-oriented narrative when verbose is requested
        try:
            detailed = detailed_comparison(defs, text)
            narrative = detailed.get('narrative') if isinstance(detailed, dict) else None
            return narrative or sentence
        except Exception:
            return sentence
    return {
        'response': sentence,
        'evidence': evidence,
    }


def detailed_comparison(defs: Dict[str, List[Dict[str, Any]]], text: str, predicate: Optional[str] = None) -> Dict[str, Any]:
    """Produce a full description of supportive and unsupportive likenesses/unlikenesses for the predicate.

    Returns a dict with keys:
      - `response`: short sentence (same as `respond()` would return)
      - `predicate`: predicate phrase used
      - `terms`: list of found terms
      - `supporting`: dict mapping term -> list of supporting fragments
      - `unsupporting`: dict mapping term -> list of unsupporting fragments
      - `shared_tokens`: tokens present in both term fragment token sets
      - `unique_tokens`: dict mapping term -> tokens unique to that term
      - `conclusion`: a short final judgement string

    This focuses primarily on the predicate provided or the first predicate discovered
    in the input. It highlights evidence (fragments) and lexical similarities/differences.
    """
    result = respond_with_evidence(defs, text, verbose=False)
    evidence = result.get('evidence')
    resp = result.get('response')

    if not evidence:
        return {'response': resp, 'predicate': predicate, 'terms': [], 'supporting': {}, 'unsupporting': {}, 'shared_tokens': set(), 'unique_tokens': {}, 'conclusion': resp}

    # If this was a direct definition request, assemble a single-term-style evidence dict
    if evidence and isinstance(evidence, dict) and evidence.get('direct_definition_request'):
        try:
            subjects = evidence.get('subjects', [])
            lines = []
            term_frags = {}
            supporting = {}
            unsupporting = {}
            for subj in subjects:
                # attempt to find local definition first
                ent = lookup_definition(defs, subj)
                frags = fragments_from_entry(ent) if ent else []
                blended = None
                try:
                    if frags:
                        blended = blend_definitions(frags, subject=subj)
                except Exception:
                    blended = None
                # wikipedia fallback
                if not blended:
                    try:
                        wiki_path = os.path.join(os.path.dirname(__file__), 'data', 'wikipedia_defs.json')
                        if os.path.exists(wiki_path):
                            with open(wiki_path, 'r', encoding='utf-8') as wf:
                                wdefs = json.load(wf)
                            ent2 = wdefs.get(subj) or wdefs.get(subj.lower())
                            if ent2:
                                blended = ent2.get('summary') if isinstance(ent2, dict) else (ent2 if isinstance(ent2, str) else None)
                                if blended:
                                    blended = re.split(r'(?<=[.!?])\s+', blended.strip())[0]
                    except Exception:
                        blended = blended
                if blended:
                    lines.append(f"{subj.capitalize()}: {blended}")
                    term_frags[subj] = [blended]
                    supporting[subj] = [blended]
                    unsupporting[subj] = []
                else:
                    lines.append(f"{subj.capitalize()}: (no definition found)")
                    term_frags[subj] = []
                    supporting[subj] = []
                    unsupporting[subj] = []
            narrative = '\n'.join(lines)
            return {
                'response': narrative,
                'predicate': predicate,
                'terms': subjects,
                'supporting': supporting,
                'unsupporting': unsupporting,
                'shared_tokens': set(),
                'unique_tokens': {s: set() for s in subjects},
                'conclusion': narrative,
                'narrative': narrative,
                'term_raw_fragments': term_frags
            }
        except Exception:
            # on failure, fall back to existing behavior
            pass

    found = evidence.get('found_terms', [])
    term_frags = evidence.get('term_raw_fragments', {})
    p_phrases = evidence.get('predicate_phrases', [])

    # choose predicate: explicit arg > first discovered > None
    p_choice = predicate or (p_phrases[0] if p_phrases else None)

    # predicates list to consider (explicit arg preferred, else discovered list)
    predicates_list = []
    if predicate:
        predicates_list = [predicate]
    elif p_phrases:
        predicates_list = p_phrases
    else:
        predicates_list = []

    predicate_count = len(predicates_list)

    # build token sets from fragments (simple alpha words)
    toksets = {}
    stop_small_local = set(["the","and","of","in","on","for","to","with","a","an","is","are","was","were","this","that"])
    # purely semantic tokens we do not want to treat as real-world evidence
    semantic_tokens = set(['by','or','using','use','via','per','both','also','try'])
    # numeric words to treat as modifiers (not standalone shared tokens)
    numeric_words = set(['one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve'])
    # auxiliaries to exclude unless used as nouns in context
    aux_tokens = set(['do','does','did','be','is','are','was','were','have','has','had','can','could','will','would','shall','should','may','might','must','ought'])

    def token_used_as_noun_in_frag(token: str, frag: str) -> bool:
        # prefer the spaCy analyzer initialized by respond(); fall back to heuristic
        nlp_local = globals().get('respond').__dict__.get('_nlp') if 'respond' in globals() else None
        if nlp_local:
            try:
                doc = nlp_local(frag)
                for tk in doc:
                    if tk.text.lower() == token and tk.pos_ in ('NOUN', 'PROPN'):
                        return True
            except Exception:
                pass
        # fallback heuristic: check for patterns like 'a TOKEN' or 'the TOKEN' or TOKEN followed by noun markers
        if re.search(r"\b(a|the|an)\s+" + re.escape(token) + r"\b", frag, re.I):
            return True
        return False

    for t in found:
        toks = set()
        for s in term_frags.get(t, []):
            for w in re.findall(r"\b[a-zA-Z]+\b", s.lower()):
                if w in stop_small_local:
                    continue
                # skip auxiliaries unless they are actually used as nouns in this fragment
                if w in aux_tokens and not token_used_as_noun_in_frag(w, s):
                    continue
                toks.add(w)
        toksets[t] = toks

    shared = set()
    unique = {}
    if len(found) >= 2:
        a = found[0]
        b = found[1]
        shared = toksets.get(a, set()) & toksets.get(b, set())
        unique[a] = toksets.get(a, set()) - shared
        unique[b] = toksets.get(b, set()) - shared
    else:
        for t in found:
            unique[t] = toksets.get(t, set())

    # supporting/unsupporting fragments (from _last_evidence/evidence_pair if available)
    supporting = {}
    unsupporting = {}
    ev_pair = evidence.get('evidence_pair')
    if ev_pair:
        for term_key in ('a','b'):
            tname = ev_pair.get(term_key)
            if tname:
                supporting[tname] = ev_pair.get(f'supporting_{term_key}', [])
                unsupporting[tname] = ev_pair.get(f'unsupporting_{term_key}', [])

    # Count predicate occurrences in fragments per term
    predicate_support_counts = {}
    predicate_total_counts = {p: 0 for p in predicates_list}
    for t in found:
        predicate_support_counts[t] = {}
        frlist = term_frags.get(t, [])
        text_blob = "\n".join(frlist).lower()
        for p in predicates_list:
            cnt = text_blob.count(p.lower())
            predicate_support_counts[t][p] = cnt
            predicate_total_counts[p] = predicate_total_counts.get(p, 0) + cnt

    # For each predicate, decide supportive status per term (count OR token match)
    predicate_support_summary = {}
    predicate_sentences = []
    for p in predicates_list:
        # derive meaningful core words for the predicate (exclude tiny/common words)
        pred_words = [w for w in re.findall(r"\b[a-zA-Z]+\b", p.lower()) if w not in stop_small_local and len(w) > 2]
        supportive_terms = []
        for t in found:
            # direct phrase count (exact predicate phrase)
            cnt = predicate_support_counts.get(t, {}).get(p, 0)

            # substring match: does any core predicate word appear in the term fragments?
            frag_match = False
            for fr in term_frags.get(t, []):
                s = fr.lower()
                for w in pred_words:
                    if w and (w in s or w.rstrip('e') in s):
                        frag_match = True
                        break
                if frag_match:
                    break

            if cnt > 0 or frag_match:
                supportive_terms.append(t)
        predicate_support_summary[p] = supportive_terms

        # build sentence: if all main terms support -> "They do <p>." else "They do not both <p>."
        # focus comparison on first two significant terms when available
        main_terms = found[:2]
        if main_terms and all(t in supportive_terms for t in main_terms):
            predicate_sentences.append(f"They do {p}.")
        else:
            predicate_sentences.append(f"They do not both {p}.")

    # Appraise shared tokens: counts, equality, and whether they appear in
    # supportive or unsupportive fragments. Produce human-friendly sentences
    # that keep the token observations together even if there's no predicate.
    shared_token_appraisal = {}
    shared_token_sentences = []
    filtered_shared = []
    # build a filtered shared list (exclude semantic and numeric tokens and action-like words)
    # Also exclude tokens that are just the subject names or simple variants (to avoid trivial overlap like 'football').
    def term_token_variants(term_name: str) -> set:
        toks = set()
        if not term_name:
            return toks
        for w in re.findall(r"\b\w+\b", term_name.lower()):
            toks.add(w)
            toks.add(singularize(w))
            if w.endswith('s'):
                toks.add(w.rstrip('s'))
        return toks

    term_norms = set()
    if len(found) >= 2:
        term_norms.update(term_token_variants(found[0]))
        term_norms.update(term_token_variants(found[1]))

    filtered_shared = [s for s in sorted(list(shared)) if s not in semantic_tokens and s not in numeric_words and s != 'try' and s not in term_norms]
    if len(found) >= 2:
        a = found[0]
        b = found[1]
        for token in filtered_shared:
            # counts in fragments
            a_count = sum(fr.lower().count(token) for fr in term_frags.get(a, []))
            b_count = sum(fr.lower().count(token) for fr in term_frags.get(b, []))
            if a_count == b_count:
                equality = 'equal'
            elif a_count > b_count:
                equality = f'more_in_{a}'
            else:
                equality = f'more_in_{b}'

            # supportive / unsupportive detection: check if token appears inside
            # supporting or unsupporting fragments for either term
            sup_in_a = any(token in s.lower() for s in supporting.get(a, []))
            sup_in_b = any(token in s.lower() for s in supporting.get(b, []))
            uns_in_a = any(token in s.lower() for s in unsupporting.get(a, []))
            uns_in_b = any(token in s.lower() for s in unsupporting.get(b, []))

            if (sup_in_a or sup_in_b) and not (uns_in_a or uns_in_b):
                status = 'supportive'
            elif (uns_in_a or uns_in_b) and not (sup_in_a or sup_in_b):
                status = 'unsupportive'
            elif (sup_in_a or sup_in_b) and (uns_in_a or uns_in_b):
                status = 'mixed'
            else:
                status = 'neutral'

            shared_token_appraisal[token] = {
                'counts': {a: a_count, b: b_count},
                'equality': equality,
                'status': status,
            }

            # sentence building
            if status == 'supportive':
                sent = f"Both {a} and {b} reference '{token}', which supports similarity." 
            elif status == 'unsupportive':
                sent = f"Both mention '{token}', but it's used in an unsupportive/negating context in at least one term." 
            elif status == 'mixed':
                sent = f"Both mention '{token}', with supportive and unsupportive evidence across the terms." 
            else:
                sent = f"Both mention '{token}', but without explicit supporting/unsupporting context."

            # append equality detail
            if equality == 'equal':
                sent += f" They appear equally often in both ({a_count} times)."
            elif equality.startswith('more_in_'):
                which = equality.split('_in_')[-1]
                sent += f" It appears more often in {which} ({a_count if which==a else b_count} vs {b_count if which==a else a_count})."

            shared_token_sentences.append(sent)

    # final sentences: predicates first (if any), then token appraisals
    final_sentences = []
    if predicate_sentences:
        final_sentences.extend(predicate_sentences)
    if shared_token_sentences:
        final_sentences.append('Additionally:')
        final_sentences.extend(shared_token_sentences)

    # Build a coherent narrative paragraph for learners
    narrative_parts = []
    # Predicates paragraph
    if predicate_sentences:
        # join predicate sentences into one smooth clause
        pred_para = ' '.join(predicate_sentences)
        narrative_parts.append(pred_para)

    # Shared tokens paragraph (require at least two found terms)
    if shared and len(found) >= 2:
        # filter out purely semantic tokens and numeric tokens from shared observations
        numeric_words = set(['one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve'])
        digits = set(str(i) for i in range(0,101))
        shared_list = [s for s in sorted(list(shared)) if s not in semantic_tokens and s not in numeric_words and s not in digits]
        # format token list with commas and 'and'
        if not shared_list:
            tokens_text = ''
        elif len(shared_list) == 1:
            tokens_text = shared_list[0]
        else:
            tokens_text = ', '.join(shared_list[:-1]) + ' and ' + shared_list[-1]

        # assess overall status from shared_token_appraisal
        statuses = [v.get('status', 'neutral') for v in shared_token_appraisal.values()]
        if all(s == 'supportive' for s in statuses):
            status_summary = 'These shared words consistently support similarity.'
        elif all(s == 'unsupportive' for s in statuses):
            status_summary = 'These shared words, however, appear in unsupportive contexts for one or both terms.'
        elif any(s == 'mixed' for s in statuses):
            status_summary = 'These shared words show mixed evidence: some usages support similarity while others do not.'
        else:
            status_summary = 'These shared words appear without clear supporting or contradicting context.'

        # group tokens into useful learner-oriented buckets
        a = found[0]
        b = found[1]
        group_use_ball = [t for t in shared_list if t in ('ball', 'ball(s)')]
        # exclude 'try' from game features (action-like verb)
        group_game_features = [t for t in shared_list if t in ('game', 'goal', 'opponents', 'players', 'teams')]
        others = [t for t in shared_list if t not in group_use_ball + group_game_features]

        if group_use_ball:
            # simple phrasing for ball usage
            narrative_parts.append('They both use a ball.')

        if group_game_features:
            feat_list = [t for t in group_game_features if t != 'game']
            # detect numeric mentions (words or digits) tied to tokens, per term
            number_words = {
                'one':'1','two':'2','three':'3','four':'4','five':'5','six':'6','seven':'7','eight':'8','nine':'9','ten':'10','eleven':'11','twelve':'12'
            }

            def find_number_for_token(term_name, token_name):
                frs = term_frags.get(term_name, [])
                for fr in frs:
                    # look for digit before token, e.g. '11 players' or word 'two teams'
                    m = re.search(r"\b(\d+|" + '|'.join(number_words.keys()) + r")\b\s+(?:of\s+)?" + re.escape(token_name) + r"s?\b", fr, re.I)
                    if m:
                        val = m.group(1).lower()
                        return number_words.get(val, val)
                return None

            numeric_sentences = []
            nonnumeric_feats = []
            for tok in feat_list:
                numa = find_number_for_token(a, tok)
                numb = find_number_for_token(b, tok)
                if numa or numb:
                    # pluralize token label appropriately
                    label = tok if (numa == '1' or numb == '1') else (tok if tok.endswith('s') else tok + 's')
                    if numa and numb:
                        if numa == numb:
                            numeric_sentences.append(f"Both {a} and {b} have {numa} {label}.")
                        else:
                            numeric_sentences.append(f"{a.capitalize()} has {numa} {label} and {b.capitalize()} has {numb} {label}.")
                    elif numa and not numb:
                        numeric_sentences.append(f"{a.capitalize()} has {numa} {label}; {b.capitalize()} does not specify a number for {tok}.")
                    elif numb and not numa:
                        numeric_sentences.append(f"{b.capitalize()} has {numb} {label}; {a.capitalize()} does not specify a number for {tok}.")
                else:
                    nonnumeric_feats.append(tok)

            # add numeric sentences first (they separate numeric token info)
            narrative_parts.extend(numeric_sentences)

            # then the general non-numeric summary
            if nonnumeric_feats:
                if len(nonnumeric_feats) == 1:
                    narrative_parts.append(f"They're both games with {nonnumeric_feats[0]}.")
                else:
                    feats_text = ', '.join(nonnumeric_feats[:-1]) + ' and ' + nonnumeric_feats[-1]
                    narrative_parts.append(f"They're both games with {feats_text}.")

        if others:
            # present remaining shared tokens compactly
            if len(others) == 1:
                narrative_parts.append(f"They also both mention {others[0]}.")
            else:
                if len(others) == 2:
                    oth_text = ' and '.join(others)
                else:
                    oth_text = ', '.join(others[:-1]) + ' and ' + others[-1]
                narrative_parts.append(f"They also both mention {oth_text}.")

        # do not include parenthetical examples or counts per user request
        narrative_parts = [p for p in narrative_parts if p]

    # If there's no predicate and no shared tokens, give a gentle learning prompt
    if not predicate_sentences and not shared:
        narrative_parts.append('I could not find a clear shared predicate or strong lexical overlap; try asking about a specific characteristic (for example, "do they both X?").')

    narrative = ' '.join(narrative_parts).strip()

    # craft a human-friendly conclusion that reconciles predicate evidence and narrative
    conclusion = None
    if ev_pair:
        ha = ev_pair.get('has_a')
        hb = ev_pair.get('has_b')
        ptext = ev_pair.get('predicate_phrase') or p_choice or ''
        a_name = ev_pair.get('a')
        b_name = ev_pair.get('b')

        # build a short shared-features phrase if available
        shared_features = [s for s in (filtered_shared if 'filtered_shared' in locals() else [])]
        shared_phrase = ''
        if shared_features:
            if len(shared_features) == 1:
                shared_phrase = f"They both mention {shared_features[0]}."
            else:
                sf_text = ', '.join(shared_features[:-1]) + ' and ' + shared_features[-1]
                shared_phrase = f"They both mention {sf_text}."

        # Cases
        if ha and hb:
            # both support predicate
            conclusion = f"Both {a_name} and {b_name} show evidence for '{ptext}'."
            if shared_phrase:
                conclusion += ' ' + shared_phrase
        elif ha and not hb:
            conclusion = f"{a_name.capitalize()} shows evidence for '{ptext}', but {b_name} does not."
            if shared_phrase:
                conclusion += ' ' + shared_phrase
        elif hb and not ha:
            conclusion = f"{b_name.capitalize()} shows evidence for '{ptext}', but {a_name} does not."
            if shared_phrase:
                conclusion += ' ' + shared_phrase
        else:
            # neither shows predicate support — emphasize shared features if they exist
            if shared_phrase:
                conclusion = f"They do not clearly both {ptext}. {shared_phrase}"
            else:
                conclusion = resp
    else:
        conclusion = resp

    return {
        'response': resp,
        'predicate': p_choice,
        'terms': found,
        'supporting': supporting,
        'unsupporting': unsupporting,
        'predicate_phrases': predicates_list,
        'predicate_count': predicate_count,
        'predicate_support_counts': predicate_support_counts,
        'predicate_total_counts': predicate_total_counts,
        'predicate_support_summary': predicate_support_summary,
        'predicate_sentences': predicate_sentences,
        'shared_token_appraisal': shared_token_appraisal,
        'shared_token_sentences': shared_token_sentences,
        'narrative': narrative,
        'final_sentences': final_sentences,
        'shared_tokens': sorted(list(filtered_shared)),
        'unique_tokens': {k: sorted(list(v)) for k, v in unique.items()},
        'conclusion': conclusion,
    }


# ---------------------------------------------------------------------
# Taxonomic grammar demo helper
# ---------------------------------------------------------------------
try:
    from taxonomic_grammar import analyze as _tg_analyze, render_response as _tg_render, generate_variations as _tg_variations
except Exception:
    _tg_analyze = None
    _tg_render = None
    _tg_variations = None
try:
    from nerve_center import nerve as _nerve
except Exception:
    _nerve = None

def taxonomy_demo(prompt=None, variations_steps=0):
    """Run taxonomic analysis on `prompt`. If `prompt` is None, read from stdin.

    If `variations_steps` > 0 and the variation generator is available, also print
    a sequence of alternative rendered summaries that traverse genus (`variable`) via a sine wave.
    """
    if _tg_analyze is None:
        print("taxonomic_grammar module not available")
        return None
    if prompt is None:
        prompt = input('Enter prompt for taxonomy analysis: ')
    import json
    out = _tg_analyze(prompt)
    # Print structured JSON and a friendly rendered response if available
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if _tg_render:
        print('\n--- Friendly taxonomy summary ---')
        print(_tg_render(out, max_items=6, positivity=True))

    if variations_steps and _tg_variations:
        print('\n--- Variations (sine-wave genus traversal) ---')
        variations = _tg_variations(out, steps=variations_steps, positivity=True)
        for v in variations:
            print('\n' + v)

    return out


# ---------------------------------------------------------------------
# Module-level blending function (exported for tests)
# ---------------------------------------------------------------------
def blend_fragments(def_list, subject=None):
    """Blend a list of definition fragments into a concise combined string.

    This is a module-level copy of the internal blending logic so tests and
    other modules can reuse it. Sets `. _last_fragments` on the function.
    """
    if not def_list:
        return ""
    import re
    # Forbidden endings and helper functions reused from nested implementation
    forbidden_endings = set([
        'about','above','across','after','against','along','amid','among','around','as','at','because','before','behind','below','beneath','beside','besides','between','beyond','but','by','concerning','considering','despite','down','during','except','following','for','from','in','including','inside','into','like','minus','near','of','off','on','onto','opposite','out','outside','over','past','per','plus','regarding','round','save','since','than','through','to','toward','towards','under','underneath','unlike','until','up','upon','versus','via','with','within','without','aboard','alongside','amidst','amongst','apropos','athwart','barring','circa','cum','excepting','excluding','failing','notwithstanding','pace','pending','pro','qua','re','sans','than','throughout','till','times','upon','vis-à-vis','whereas','whether','yet',
        'and','or','nor','so','for','yet','although','because','since','unless','until','while','whereas','though','lest','once','provided','rather','than','that','though','till','unless','until','when','whenever','where','wherever','whether','while','both','either','neither','not','only','but','also','even','if','just','still','then','too','very','well','now','however','thus','therefore','hence','moreover','furthermore','meanwhile','otherwise','besides','indeed','instead','likewise','next','still','then','yet','again','already','always','anyway','anywhere','everywhere','nowhere','somewhere','here','there','where','why','how','whose','which','what','who','whom','whichever','whatever','whoever','whomever',
        'a','an','the','this','that','these','those','my','your','his','her','its','our','their','whose','each','every','either','neither','some','any','no','other','another','such','much','many','more','most','several','few','fewer','least','less','own','same','enough','all','both','half','one','two','three','first','second','next','last','another','certain','various','which','what','whose','whichever','whatever','whoever','whomever','somebody','someone','something','anybody','anyone','anything','everybody','everyone','everything','nobody','noone','nothing','one','oneself','ones','myself','yourself','himself','herself','itself','ourselves','yourselves','themselves','who','whom','whose','which','that','whichever','whatever','whoever','whomever'
    ])

    def is_participle_local(word):
        return is_participle(word)

    def ends_with_forbidden(s):
        words = s.rstrip('.').split()
        return words and words[-1].lower() in forbidden_endings

    def clean_sentence(s):
        words = s.rstrip('.').split()
        while words and (words[-1].lower() in forbidden_endings or is_participle_local(words[-1])):
            words.pop()
        return ' '.join(words)

    # Clean fragments and remove duplicates while preserving order
    frags = []
    seen = set()
    for d in def_list:
        s = clean_sentence(strip_participles_from_end(d.strip()))
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        frags.append(s)
    if not frags:
        blend_fragments._last_fragments = []
        return ""
    blend_fragments._last_fragments = frags.copy()

    # If a wikipedia-derived summary exists for the subject, prefer it when it's informative
    try:
        if subject and isinstance(subject, str):
            wiki_path = os.path.join(os.path.dirname(__file__), 'data', 'wikipedia_defs.json')
            if os.path.exists(wiki_path):
                with open(wiki_path, 'r', encoding='utf-8') as wf:
                    wdefs = json.load(wf)
                ent = wdefs.get(subject) or wdefs.get(subject.lower())
                if ent:
                    summ = ent.get('summary') if isinstance(ent, dict) else (ent if isinstance(ent, str) else None)
                    if summ and len(summ.split()) >= 6:
                        # return the lead sentence
                        lead = re.split(r'(?<=[.!?])\s+', summ.strip())[0]
                        blend_fragments._last_fragments = [lead]
                        return lead
    except Exception:
        pass

    # Subject tokens for scoring
    subj_tokens = set()
    if subject and isinstance(subject, str):
        subj_tokens = set(re.findall(r"\b\w+\b", subject.lower()))

    # Score fragments by: subject-token overlap, presence of definitional verbs, sentence length, and completeness
    scored = []
    for s in frags:
        score = 0.0
        s_l = s.lower()
        words = re.findall(r"\b\w+\b", s_l)
        # completeness: ends with punctuation
        if re.search(r'[.!?]\s*$', s):
            score += 1.0
        # length contributes modestly
        score += min(len(words) / 20.0, 2.0)
        # definitional cue words
        for cue in (' is ', ' are ', ' means ', ' refers to ', ' defined as ', ' is called ', ' can be '):
            if cue in s_l:
                score += 2.0
        # overlap with subject tokens
        if subj_tokens:
            common = subj_tokens & set(words)
            score += len(common) * 1.5
        # prefer fragments that contain alphabetic content beyond stop words
        scored.append((score, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    # choose top two fragments (if available) and join cleanly
    chosen = [t for _, t in scored[:2]] if scored else []
    # ensure chosen fragments are cleaned and distinct
    out_parts = []
    seen_parts = set()
    for p in chosen:
        cp = p.strip()
        if not cp:
            continue
        if cp.lower() in seen_parts:
            continue
        seen_parts.add(cp.lower())
        # ensure it ends with a period
        if not re.search(r'[.!?]\s*$', cp):
            cp = cp + '.'
        out_parts.append(cp)
    if out_parts:
        blend_fragments._last_fragments = out_parts.copy()
        return ' '.join(out_parts)

    stop = set(["the","and","or","of","in","on","for","to","with","a","an","is"])

    # Lightweight noun heuristic: prefer tokens that look like nouns by
    # morphology (common noun suffixes), plural forms, or not matching common verb seeds.
    noun_suffixes = ('tion','ment','ness','ity','ism','ology','ship','age','ery','hood','graphy','scope','ence','ance','ist')
    verb_seed = set(["is","are","was","were","do","does","did","run","runs","move","moves","associate","associates","associated","involve","involves","contain","contains","include","includes","mean","means","use","uses","lead","leads","cause","causes","have","has","hold","held","form","forms","create","creates","convert","converts","breathe","emit","expel","draw"])

    def is_noun_like(w: str) -> bool:
        w = w.lower()
        if not w.isalpha() or len(w) <= 2:
            return False
        if w in verb_seed:
            return False
        if w.endswith('s') and len(w) > 3:
            return True
        for suf in noun_suffixes:
            if w.endswith(suf):
                return True
        # fallback: prefer words that are not clearly verbs (ending -ing/-ed) or adjectives
        if w.endswith('ing') or w.endswith('ed') or w.endswith('ly'):
            return False
        return True

        # final fallback: if spaCy is available use it
    # If spaCy loaded successfully prefer it for single-token checks
    def is_noun_final(w: str) -> bool:
        if is_noun_spacy(w):
            return True
        return is_noun_like(w)

    # Try to initialize spaCy for better POS tagging; if unavailable, fall back to heuristic
    _spacy_nlp = None
    try:
        import spacy
        try:
            _spacy_nlp = spacy.load('en_core_web_sm')
        except Exception:
            # model not installed; attempt to load generic if available
            try:
                _spacy_nlp = spacy.load('en_core_web_sm')
            except Exception:
                _spacy_nlp = None
    except Exception:
        _spacy_nlp = None

    def is_noun_spacy(w: str) -> bool:
        if not _spacy_nlp:
            return False
        try:
            doc = _spacy_nlp(w)
            if not doc:
                return False
            tok = doc[0]
            return tok.pos_ == 'NOUN' or tok.pos_ == 'PROPN'
        except Exception:
            return False

    frag_tokens = []
    for s in frags:
        toks_all = [t.lower() for t in re.findall(r"\b\w+\b", s)]
        toks = [t for t in toks_all if t not in stop and is_noun_final(t)]
        frag_tokens.append((s, set(toks)))

    ordered = []
    covered = set()
    if subj_tokens:
        scored = []
        for s, toks in frag_tokens:
            rel = len(toks & subj_tokens) / max(1, len(toks))
            scored.append((rel, len(toks), s, toks))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        for rel, _, s, toks in scored:
            novelty = len(toks - covered)
            if novelty <= 0 and len(ordered) >= 1:
                continue
            ordered.append((s, toks))
            covered.update(toks)
    else:
        scored = sorted(frag_tokens, key=lambda x: len(x[1]), reverse=True)
        for s, toks in scored:
            novelty = len(toks - covered)
            if novelty <= 0 and len(ordered) >= 1:
                continue
            ordered.append((s, toks))
            covered.update(toks)

    ordered = ordered[:4]
    texts = [s for s, _ in ordered]
    if not texts:
        return ""
    # Attempt to build compact fragments per user spec:
    # - Prefer 2-word fragments: [noun] [qualifier]
    # - If fragment contains a predicate (verb), produce 3-word: [noun_plural] [predicate]
    compact_phrases = []
    compact_meta = []  # list of (noun_candidate, qualifier, predicate, source_text)
    stop_small = set(["the","and","of","in","on","for","to","a","an","is","are","was","were","this","that"])
    for s, toks in ordered:
        toks_list = [w for w in re.findall(r"\b\w+\b", s.lower()) if w not in stop_small]
        if not toks_list:
            continue
        # find predicate (simple verb seed) and a noun subject (noun-like token)
        predicate = None
        for w in reversed(toks_list):
            if w in verb_seed:
                predicate = w
                break

        # pick a subject noun from tokens that pass noun-like heuristic (prefer spaCy)
        noun_candidate = None
        for w in toks_list:
            if is_noun_final(w):
                noun_candidate = w
                break
        if noun_candidate is None:
            # try any token as last resort
            noun_candidate = toks_list[0]

        # find a short noun-like qualifier adjacent to the noun (prefer next token)
        qualifier = None
        try:
            idx = toks_list.index(noun_candidate)
        except ValueError:
            idx = 0
        # prefer next token as qualifier (noun-like), then previous
        if idx + 1 < len(toks_list) and is_noun_like(toks_list[idx+1]):
            qualifier = toks_list[idx+1]
        elif idx - 1 >= 0 and is_noun_like(toks_list[idx-1]):
            qualifier = toks_list[idx-1]

        if not qualifier:
            # fallback generic qualifier to ensure 2-word fragment
            qualifier = 'thing'

        # plurality for predicate case
        noun_plural = noun_candidate
        if predicate or qualifier in ('both','these','they'):
            if not noun_plural.endswith('s'):
                if noun_plural.endswith('y'):
                    noun_plural = noun_plural[:-1] + 'ies'
                else:
                    noun_plural = noun_plural + 's'

        # build phrase: subject-first ordering (noun + qualifier)
        if predicate:
            compact_phrases.append(f"{noun_plural} {predicate}")
            compact_meta.append((noun_candidate, predicate, predicate, s))
        else:
            compact_phrases.append(f"{noun_candidate} {qualifier}")
            compact_meta.append((noun_candidate, qualifier, None, s))
    # If we have at least two different fragments, synthesize explicit blends
    # by taking the noun token from one fragment and qualifier from another.
    if len(compact_meta) >= 2:
        # prefer combining noun from first and qualifier from second
        n1, q1, p1, s1 = compact_meta[0]
        n2, q2, p2, s2 = compact_meta[1]
        # create two blend candidates that explicitly borrow tokens across fragments
        try:
            if n1 and q2:
                blend12 = f"{n1} {q2}"
                compact_phrases.insert(0, blend12)
            if n2 and q1:
                blend21 = f"{n2} {q1}"
                compact_phrases.insert(0, blend21)
        except Exception:
            pass
    # Deduplicate while preserving order
    seen_cp = set()
    compact_final = [p for p in compact_phrases if not (p in seen_cp or seen_cp.add(p))]
    if compact_final:
        # If there are exactly two, prefer 'Both X and Y' style
        if len(compact_final) == 2:
            a = compact_final[0]
            b = compact_final[1]
            # extract noun phrases after qualifiers
            return f"Both {a.split(' ',1)[1]} and {b.split(' ',1)[1]}"
        # if many, join with commas
        return '; '.join(compact_final[:4])

    # Fallback: robust, simple extraction — pick the longest content word from each selected fragment
    fallback_nouns = []
    for s, _ in ordered[:2]:
        toks = [w for w in re.findall(r"\b[a-zA-Z]+\b", s.lower()) if w not in stop_small]
        if not toks:
            continue
        # pick the longest token as proxy noun
        noun = max(toks, key=lambda w: len(w))
        # pluralize heuristically
        if not noun.endswith('s'):
            if noun.endswith('y'):
                noun_p = noun[:-1] + 'ies'
            else:
                noun_p = noun + 's'
        else:
            noun_p = noun
        fallback_nouns.append(noun_p)
    if len(fallback_nouns) == 2:
        return f"Both {fallback_nouns[0]} and {fallback_nouns[1]}"
    if len(fallback_nouns) == 1:
        return fallback_nouns[0]
    # Build token sets for selected fragments to detect overlap
    frag_token_sets = []
    for s, toks in ordered:
        frag_token_sets.append(toks)
    # If multiple fragments share a substantial fraction of tokens, summarize with a quantifier
    if len(frag_token_sets) >= 2:
        # compute pairwise overlap relative to smaller fragment
        overlaps = []
        for i in range(len(frag_token_sets)):
            for j in range(i+1, len(frag_token_sets)):
                a = frag_token_sets[i]
                b = frag_token_sets[j]
                if not a or not b:
                    continue
                inter = a & b
                frac = len(inter) / max(1, min(len(a), len(b)))
                overlaps.append((i, j, frac, inter))
        # pick significant overlaps
        significant = [t for t in overlaps if t[2] >= 0.4]
        if significant:
            # union the intersection tokens for all significant pairs
            shared = set()
            for _, _, _, inter in significant:
                shared.update(inter)
            if shared:
                # build a short phrase from shared tokens (prefer longer tokens)
                shared_list = sorted(shared, key=lambda w: (-len(w), w))[:4]
                shared_phrase = ', '.join(shared_list[:-1]) + ('' if len(shared_list) == 1 else f', and {shared_list[-1]}') if len(shared_list) > 1 else shared_list[0]
                if len(texts) == 2:
                    out = f"Both concern {shared_phrase}."
                else:
                    out = f"These concern {shared_phrase}."
                # ensure capitalization
                out = out[0].upper() + out[1:]
                return out
    if len(texts) == 1:
        out = texts[0]
    elif len(texts) == 2:
        out = f"{texts[0]}, and {texts[1]}"
    else:
        out = ', '.join(texts[:-1]) + f", and {texts[-1]}"

    if subject and subject.lower() not in out.lower():
        out = f"{subject.capitalize()} — {out[0].lower() + out[1:]}"
    else:
        out = out[0].upper() + out[1:]

    if ends_with_forbidden(out) and subject:
        out = out + ' ' + (f"the {subject}" if subject.endswith('s') else f"a {subject}")
    return out.strip()

# Provide a backward-compatible name for tests and other modules
blend_definitions = blend_fragments


def nerve_demo(prompt=None, variations_steps=0, top_n=5):
    """Create a nerve session from a prompt and show top items.

    - Runs taxonomy analysis (prints structured JSON and friendly summary).
    - Creates a persisted session in `data/nerve_sessions` via `nerve_center.NerveCenter`.
    - Prints top `top_n` items and expands the first variable found.
    Returns the session id (or None).
    """
    if _tg_analyze is None:
        print('taxonomic_grammar module not available')
        return None
    if prompt is None:
        prompt = input('Enter prompt for nerve demo: ')

    # Run taxonomy demo (it prints JSON + summary)
    result = taxonomy_demo(prompt, variations_steps=variations_steps)
    if result is None:
        return None

    if _nerve is None:
        print('nerve_center not available')
        return None

    sid = _nerve.create_session(result)
    print(f'Created nerve session: {sid}')

    tops = _nerve.get_top_items(sid, n=top_n)
    print('\nTop items:')
    import json
    print(json.dumps(tops, indent=2, ensure_ascii=False))

    if tops:
        first_var = tops[0].get('variable')
        if first_var:
            print('\nExpanding first variable:\n')
            print(_nerve.expand_variable(sid, first_var))

    print('\nUse nerve_center.nerve to inspect or load sessions programmatically.')
    return sid

