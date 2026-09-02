#!/usr/bin/env python3
"""Build Anemone's grep-friendly 3-word background from its existing dictionary and encyclopedia."""
from pathlib import Path
import argparse, csv, json, re

LEVELS=('kingdom','phylum','family','order','genus','species','type','name')
STOP=set('a an the of in on at to for from by with and or that which who where when is are was were be been being as this these those its their his her into over under about'.split())


def slug(s):
    s=str(s or '').lower().replace('&',' and ')
    s=re.sub(r'[^a-z0-9]+','_',s).strip('_')
    return s or 'unknown'


def compact_concept(text, max_words=4):
    words=re.findall(r'[A-Za-z0-9]+', str(text).lower())
    words=[w for w in words if w not in STOP]
    return '_'.join(words[:max_words]) if words else 'unknown_concept'


def classify(text, rules):
    t=str(text).lower(); best=None
    for kingdom, phyla in rules.items():
        for phylum, cues in phyla.items():
            score=sum(1 for cue in cues if cue in t)
            if score and (best is None or score>best[0]):
                best=(score, kingdom, phylum)
    return (best[1], best[2]) if best else ('knowledge','general')


def relation_fact(name, text):
    subject=slug(name)
    s=' '.join(str(text).replace('\n',' ').split())
    patterns=[
        (r'\b(?:is|are|was|were)\s+(?:an?|the)?\s*(.+)', 'is'),
        (r'\b(?:refers? to|means?)\s+(.+)', 'means'),
        (r'\b(?:represents?|denotes?)\s+(.+)', 'represents'),
        (r'\b(?:consists? of|comprises?)\s+(.+)', 'contains'),
        (r'\b(?:causes?|produces?|generates?)\s+(.+)', 'causes'),
        (r'\b(?:contains?|includes?)\s+(.+)', 'contains'),
        (r'\b(?:measures?|quantifies?)\s+(.+)', 'measures'),
        (r'\b(?:describes?|characterizes?)\s+(.+)', 'describes'),
    ]
    for pat, rel in patterns:
        m=re.search(pat, s, re.I)
        if m:
            return [subject, rel, compact_concept(m.group(1))]
    return [subject, 'means', compact_concept(s)]


def taxonomy_chain(name, kingdom, phylum, family='concept', order='defined_concept', genus=None, species=None, typ='definition'):
    p={'kingdom':slug(kingdom),'phylum':slug(phylum),'family':slug(family),'order':slug(order),
       'genus':slug(genus or name),'species':slug(species or name),'type':slug(typ),'name':slug(name)}
    vals=[p[k] for k in LEVELS]
    tf=[]
    for a,b in zip(reversed(vals[1:]), reversed(vals[:-1])):
        if a != b:
            tf.append([a,'belongs',b])
    return p, tf


def iter_source(path):
    try:
        import ijson
        with open(path,'rb') as f:
            yield from ijson.kvitems(f,'')
        return
    except ImportError:
        pass
    with open(path,'r',encoding='utf-8') as f:
        data=json.load(f)
    yield from data.items()


def encyclopedia_text(v):
    if not isinstance(v,dict): return str(v)
    fr=v.get('fragment_def')
    if isinstance(fr,list) and fr: return ' '.join(map(str,fr[:3]))
    s=v.get('summary','')
    return ' '.join(map(str,s)) if isinstance(s,list) else str(s)


def dictionary_text(v):
    return str(v.get('definition','')) if isinstance(v,dict) else str(v)


def emit(outf, rec, index_rows, relfile):
    raw=(json.dumps(rec,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8')
    off=outf.tell(); outf.write(raw)
    for n in [rec.get('name')]+list(rec.get('aliases') or []):
        if n: index_rows.append((slug(n),relfile,off,len(raw)))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--repo',default='.')
    ap.add_argument('--out',default='data/background3/generated')
    ap.add_argument('--rules',default='data/background3/taxonomy_rules.json')
    args=ap.parse_args()
    repo=Path(args.repo); out=repo/args.out; out.mkdir(parents=True,exist_ok=True)
    rules=json.loads((repo/args.rules).read_text(encoding='utf-8'))
    sources=[('dictionary',repo/'data/definitions.json',dictionary_text),('encyclopedia',repo/'data/wikipedia_defs.json',encyclopedia_text)]
    index_rows=[]
    for source,path,textfn in sources:
        outpath=out/f'{source}.jsonl'
        with open(outpath,'wb') as outf:
            for name,val in iter_source(path):
                text=textfn(val)
                if not text.strip(): continue
                kingdom,phylum=classify(name+' '+text,rules)
                p,tf=taxonomy_chain(name,kingdom,phylum)
                aliases=[]
                if source=='dictionary' and isinstance(val,dict): aliases=[slug(x) for x in val.get('synonyms',[])[:24]]
                rec={'name':slug(name),'kind':'concept','taxonomy':p,'facts':[relation_fact(name,text)],'taxonomy_facts':tf,
                     'traits':{},'aliases':aliases,'source':{'kind':source,'title':val.get('title') if isinstance(val,dict) else None,
                     'url':val.get('url') if isinstance(val,dict) else None,'definition':text}}
                emit(outf,rec,index_rows,outpath.relative_to(repo/'data/background3').as_posix())
    with open(repo/'data/background3/index.tsv','w',encoding='utf-8',newline='') as f:
        w=csv.writer(f,delimiter='\t'); w.writerow(['name','file','offset','length']); w.writerows(index_rows)
    print(f'wrote {len(index_rows):,} indexed names to {out}')


if __name__=='__main__':
    main()
