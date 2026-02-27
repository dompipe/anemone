# shell.py


from eng1neer import respond_subject_specific

if __name__ == "__main__":
    # Only load the thesaurus association file at startup
    import json
    assoc_path = 'thesaurus_assoc.json'
    with open(assoc_path, 'r', encoding='utf-8') as f:
        thesaurus_assoc = json.load(f)
    import re

    # lightweight terminal spinner to show progress during code generation
    class Spinner:
        def __init__(self, msg=''):
            import sys, threading, itertools, time
            self.msg = msg
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._sys = sys
            self._itertools = itertools
            self._time = time

        def _spin(self):
            for ch in self._itertools.cycle('|/-\\'):
                if self._stop.is_set():
                    break
                self._sys.stdout.write('\r' + (self.msg + ' ' if self.msg else '') + ch)
                self._sys.stdout.flush()
                self._time.sleep(0.08)
            # clear
            self._sys.stdout.write('\r' + (' ' * (len(self.msg) + 2)) + '\r')
            self._sys.stdout.flush()

        def start(self):
            self._thread.start()

        def stop(self):
            self._stop.set()
            self._thread.join()

    # Threaded runner with watch: runs `func` in a daemon thread, watches for ESC or Ctrl+C,
    # and returns early if cancelled or timed out. Cannot forcibly kill threads; uses daemon threads.
    def run_with_watch(func, timeout=30.0, poll=0.1):
        import threading, time
        result = {}

        def runner():
            try:
                result['value'] = func()
            except Exception as e:
                result['error'] = e

        th = threading.Thread(target=runner, daemon=True)
        th.start()
        start = time.time()
        cancelled = False
        timed_out = False
        try:
            while th.is_alive():
                time.sleep(poll)
                # timeout
                if (time.time() - start) > timeout:
                    timed_out = True
                    break
                # ESC detection on Windows
                try:
                    import msvcrt
                    if msvcrt.kbhit():
                        ch = msvcrt.getch()
                        # ESC
                        if ch == b'\x1b':
                            cancelled = True
                            break
                except Exception:
                    # non-Windows or msvcrt not available; rely on KeyboardInterrupt
                    pass
        except KeyboardInterrupt:
            cancelled = True

        if th.is_alive():
            # cannot kill thread; leave as daemon and return control
            return False, result.get('value'), cancelled, timed_out
        if 'error' in result:
            raise result['error']
        return True, result.get('value'), cancelled, timed_out

    while True:
        try:
            line = input("@#!$ > ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not line:
            continue

        # --- Inline paragraph-compare utilities (embedded to avoid dynamic import) ---
        # small, local helpers copied and trimmed from scripts/compare_subjects.py
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

        def _clean_definition_text(s: str) -> str:
            if not s:
                return ''
            t = str(s)
            t = re.sub(r'https?://\S+', ' ', t)
            t = re.sub(r'www\.\S+', ' ', t)
            t = re.sub(r'\borg/wiki/\S+', ' ', t, flags=re.IGNORECASE)
            t = re.sub(r'\b(wikipedia|wiki|org|com|net|edu|gov)\b', ' ', t, flags=re.IGNORECASE)
            t = re.sub(r"\[.*?\]", ' ', t)
            t = re.sub(r'\s+', ' ', t).strip()
            return t

        def _ensure_sentence_end(s: str) -> str:
            s = (s or '').strip()
            if not s:
                return ''
            if s[-1] not in '.!?':
                return s + '.'
            return s

        def _capitalize_first_alpha(s: str) -> str:
            if not s:
                return ''
            m = re.search(r'[A-Za-z]', s)
            if not m:
                return s
            i = m.start()
            return s[:i] + s[i].upper() + s[i+1:]

        def _ensure_periods_in_text(text: str) -> str:
            if not text:
                return ''
            parts = [p.strip() for p in re.split(r'[\n]+', text) if p.strip()]
            sentences = []
            for p in parts:
                subs = re.split(r'(?<=[.!?])\s+', p)
                for s in subs:
                    ss = s.strip()
                    if not ss:
                        continue
                    sentences.append(_capitalize_first_alpha(_ensure_sentence_end(ss)))
            return ' '.join(sentences)

        def _strip_leading_term(text: str, name: str) -> str:
            if not text or not name:
                return text or ''
            dup_pattern = re.compile(r'^\s*' + re.escape(name) + r'\s+' + re.escape(name) + r'\b', flags=re.IGNORECASE)
            if dup_pattern.search(text):
                return re.sub(dup_pattern, name, text, count=1).lstrip()
            return text

        def load_subject_definitions(data_dir='data'):
            import os
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

        def load_thesaurus(path='thesaurus_assoc.json'):
            import os
            if not os.path.exists(path):
                return {}
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)

        def _first_sentence_containing(text: str, term: str) -> str:
            if not text:
                return ''
            for s in re.split(r'[\n\.]', text):
                if term.lower() in s.lower():
                    s = s.strip()
                    return s if len(s) <= 240 else (s[:237] + '...')
            return ''

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
                        sent = ss if len(ss) <= 400 else ss[:397] + '...'
                        out.append(_capitalize_first_alpha(_ensure_sentence_end(sent)))
                        break
                if len(out) >= max_n:
                    break
            return out

        def generate_paragraph(name_a, name_b, defs, thesaurus):
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
                a_high = ', '.join(a_only[:8]) or 'distinct focus'
                b_high = ', '.join(b_only[:8]) or 'distinct focus'
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
        # --- end inline paragraph utilities ---

        # Quick code-intent check and suggestion via cross-referencer
        try:
            import importlib.util
            import time
            from pathlib import Path
            # use a unique module name each time to avoid any cached version
            unique_name = f'cross_reference_prompt_{int(time.time()*1000)}'
            spec = importlib.util.spec_from_file_location(unique_name, str(Path('scripts') / 'cross_reference_prompt.py'))
            cr = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cr)
            if cr.is_code_request(line):
                try:
                    index = cr.load_index()
                    items, shorthand, params = cr.cross_reference(line, index)
                    sugg = cr.suggest_function_signature(items, params, line)
                    # show a concise one-line suggestion instead of full JSON
                    sig = sugg.get('signature') or sugg.get('name') or ''
                    if sig:
                        print(f"Code intent detected — suggested: {sig}")
                    else:
                        print('Code intent detected — suggested function')
                    # Automatically generate code from the suggestion (original behavior)
                    directive = f"Generate only Python code, no explanation. {line}"
                    if 'code_engine' not in globals():
                        from new_natural_code_engine import NaturalCodeEngine
                        globals()['code_engine'] = NaturalCodeEngine('data')
                    try:
                        spinner = Spinner('Generating code...')
                        spinner.start()
                        try:
                            finished, code, cancelled, timed_out = run_with_watch(lambda: globals()['code_engine'].generate_code(directive), timeout=30.0)
                        finally:
                            spinner.stop()
                        if not finished:
                            if cancelled:
                                print('\nGeneration cancelled by user (ESC/Ctrl+C).')
                            elif timed_out:
                                print('\nGeneration timed out.')
                            else:
                                print('\nGeneration halted.')
                            code = None
                        # if the engine returns an empty or placeholder result, synthesize a simple fallback
                        if not code or 'No actionable' in code or len(code.strip()) < 40:
                            # synthesize from suggestion or prompt: simple loop/print template
                            try:
                                prompt = line.lower()
                                import re
                                m = re.search(r'from\s*(\d+)\s*to\s*(\d+)', prompt)
                                if m:
                                    a = int(m.group(1)); b = int(m.group(2))
                                    name = sugg.get('name') or 'generated_fn'
                                    fname = name if name.endswith('.py') else name + '.py'
                                    code = (f"def {name}():\n"
                                            f"    for i in range({a},{b}+1):\n"
                                            f"        print(i)\n\n"
                                            f"if __name__ == '__main__':\n"
                                            f"    {name}()\n")
                                else:
                                    # generic fallback: if prompt contains 'count' and two numbers, find numbers
                                    nums = re.findall(r"\d+", prompt)
                                    if len(nums) >= 2:
                                        a = int(nums[0]); b = int(nums[1])
                                        name = sugg.get('name') or 'generated_fn'
                                        fname = name if name.endswith('.py') else name + '.py'
                                        code = (f"def {name}():\n"
                                                f"    for i in range({a},{b}+1):\n"
                                                f"        print(i)\n\n"
                                                f"if __name__ == '__main__':\n"
                                                f"    {name}()\n")
                                    else:
                                        # last-resort: use suggested skeleton if available
                                        sk = (sugg.get('skeletons') or [])
                                        if sk:
                                            code = sk[0]
                                        else:
                                            code = '# No actionable code structure detected from prompt.\n'
                            except Exception:
                                code = '# No actionable code structure detected from prompt.\n'
                        print(code)
                        # save to examples/<name>.py when suggestion provides a name
                        try:
                            name = sugg.get('name') or None
                            if name:
                                from pathlib import Path
                                p = Path('examples')
                                p.mkdir(parents=True, exist_ok=True)
                                fname = name if name.endswith('.py') else name + '.py'
                                outp = p / fname
                                outp.write_text(code, encoding='utf-8')
                                print('Wrote', str(outp))
                        except Exception:
                            pass
                    except Exception as e:
                        print('Code engine error:', e)
                    continue
                except Exception as e:
                    print('Cross-referencer error:', e)
        except Exception:
            # fail silently; cross-referencer is optional
            pass

        if line.lower() in {"quit", "exit"}:
            break

        # If the user asks for date operations, forward to date_calculator
        if line.lower().startswith('date '):
            # format: date <subcmd> [args...]
            parts = line.split()[1:]
            try:
                from date_calculator import cli as date_cli
                ret = date_cli(parts)
                # cli prints output; return code printed as needed
            except Exception as e:
                print('Date command failed:', e)
            continue

        # verify <termA> <termB> -- compare definitions across dictionaries
        if line.lower().startswith('verify '):
            parts = line.split()[1:]
            try:
                from equality_verifier import cli as verify_cli
                verify_cli(parts)
            except Exception as e:
                print('Verify command failed:', e)
            continue

        # If the prompt starts with 'code:' force the code engine to return code-only output.
        if line.lower().startswith('code:') or line.lower().startswith('generate code'):
            raw = line.split(':', 1)[1].strip() if ':' in line else line
            # support an optional leading file specification: "file <name.py> <rest of prompt>"
            fname = None
            rest = raw
            try:
                import re
                m = re.match(r'file[: ]+(\S+)\s*(.*)', raw, re.I)
                if m:
                    fname = m.group(1)
                    rest = m.group(2) or ''
            except Exception:
                pass

            # Build a directive to the code engine to return code only
            directive = f"Generate only Python code, no explanation. {rest}".strip()
            # Lazy-load code engine only if needed
            if 'code_engine' not in globals():
                from new_natural_code_engine import NaturalCodeEngine
                globals()['code_engine'] = NaturalCodeEngine('data')
            try:
                spinner = Spinner('Generating code...')
                spinner.start()
                try:
                    finished, code, cancelled, timed_out = run_with_watch(lambda: globals()['code_engine'].generate_code(directive), timeout=30.0)
                finally:
                    spinner.stop()
                if not finished:
                    if cancelled:
                        print('\nGeneration cancelled by user (ESC/Ctrl+C).')
                    elif timed_out:
                        print('\nGeneration timed out.')
                    else:
                        print('\nGeneration halted.')
                    continue
            except Exception as e:
                print('Code engine error:', e)
                continue
            # print and optionally save to examples/<fname>
            print(code)
            if fname:
                try:
                    from pathlib import Path
                    p = Path('examples')
                    p.mkdir(parents=True, exist_ok=True)
                    outp = p / fname
                    outp.write_text(code, encoding='utf-8')
                    print('Wrote', str(outp))
                except Exception as e:
                    print('Failed to write file:', e)
            continue
        # If the prompt looks like an algebraic equation, solve for variables
        elif '=' in line:
            try:
                from sympy import symbols, Eq, solve, sympify
                # Split on '=' and build equations
                eqs = [eq.strip() for eq in line.split(',') if '=' in eq]
                if len(eqs) > 10:
                    print("... (truncated to 10 equations)")
                    eqs = eqs[:10]
                sympy_eqs = []
                all_vars = set()
                for eq in eqs:
                    left, right = eq.split('=', 1)
                    left_expr = sympify(left)
                    right_expr = sympify(right)
                    sympy_eqs.append(Eq(left_expr, right_expr))
                    all_vars.update(left_expr.free_symbols)
                    all_vars.update(right_expr.free_symbols)
                if not sympy_eqs:
                    raise ValueError
                sol = solve(sympy_eqs, list(all_vars), dict=True)
                if sol:
                    for s in sol:
                        out = ', '.join(f"{str(k)} = {v}" for k, v in s.items())
                        if len(s) > 10:
                            out = ', '.join(list(out.split(', ')[:10])) + ', ...'
                        print(out)
                else:
                    print("No solution found.")
            except Exception as e:
                print(f"Could not solve equation(s): {e}")
        # If the prompt looks like a math expression, evaluate it
        elif any(c in line for c in '+-*/^()') and any(ch.isdigit() for ch in line):
            from eng1neer import try_eval_expression
            result = try_eval_expression(line)
            if result is not None:
                print(result)
            else:
                print("Invalid math expression.")
        else:
            # special command: compare <subjectA> <subjectB> -> produce paragraph summary
            if line.lower().startswith('compare ') or line.lower().startswith('paragraph '):
                # preserve the remainder for flag/keyword detection (e.g. 'bullets')
                cmd = line.split()[0].lower()
                rest = line[len(cmd):].strip()
                tokens = rest.split()
                if len(tokens) >= 2:
                    a = tokens[0]
                    b = tokens[1]
                    # show blended description only when user requests bullet-style output
                    rest_lower = rest.lower()
                    show_blend = any(k in rest_lower for k in ('bullets', 'bullet-list', 'bullet list', 'points', '--bullets', '-b'))
                    try:
                        # use local inline helpers defined above
                        try:
                            thes = load_thesaurus()
                            defs = load_subject_definitions()
                            para = generate_paragraph(a, b, defs, thes)
                            print(para)
                            if show_blend:
                                try:
                                    # load the richer blended-summary helper from scripts only when requested
                                    import importlib.util
                                    from pathlib import Path
                                    spec = importlib.util.spec_from_file_location('compare_mod', str(Path('scripts') / 'compare_subjects.py'))
                                    compare_mod = importlib.util.module_from_spec(spec)
                                    spec.loader.exec_module(compare_mod)
                                    blended = compare_mod.blend_descriptions(a, b, defs, thes)
                                    print('\nBLENDED SUMMARY:\n')
                                    print(blended)
                                except Exception:
                                    pass
                        except Exception as e:
                            print('Compare command failed:', e)
                    except Exception as e:
                        print('Compare command failed:', e)
                    continue
                else:
                    print('Usage: compare <subjectA> <subjectB>')
                    continue

            # Use subject-specific response, loading subject files only as needed
            try:
                finished, resp, cancelled, timed_out = run_with_watch(lambda: respond_subject_specific(line, assoc_path=assoc_path, data_dir='data'), timeout=20.0)
            except Exception as e:
                print('Error while processing prompt:', e)
                continue
            if not finished:
                if cancelled:
                    print('\nOperation cancelled by user (ESC/Ctrl+C).')
                elif timed_out:
                    print('\nOperation timed out.')
                else:
                    print('\nOperation halted.')
                continue
            print(resp)
