"""Self-contained semantic and lexical ranking for Footage Analyzer."""
from __future__ import annotations
import hashlib, math, re
from functools import lru_cache
TOKEN_RE = re.compile(r"[a-z0-9']+", re.I)
DIM = 384
def _features(text):
    words = TOKEN_RE.findall((text or "").lower())
    out = ["w:" + w for w in words]
    for w in words:
        p = "^" + w + "$"
        for n in (3, 4, 5):
            out.extend("c:" + p[i:i+n] for i in range(max(0, len(p)-n+1)))
    return out
def _local_embed(text):
    v=[0.0]*DIM
    for f in _features(text):
        d=hashlib.blake2b(f.encode(),digest_size=8).digest()
        i=int.from_bytes(d[:4],"little") % DIM
        v[i] += 1.0 if d[4] & 1 else -1.0
    n=math.sqrt(sum(x*x for x in v))
    return [x/n for x in v] if n else v
def _cos(a,b): return max(-1.0,min(1.0,sum(x*y for x,y in zip(a,b))))
def lexical_overlap(q,t):
    a=set(TOKEN_RE.findall((q or "").lower())); b=set(TOKEN_RE.findall((t or "").lower()))
    return len(a & b)/len(a) if a else 0.0
@lru_cache(maxsize=1)
def _st_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", local_files_only=True)
def rank_texts(query,texts):
    try:
        model=_st_model()
        vec=model.encode([query]+list(texts),normalize_embeddings=True,convert_to_numpy=False)
        q=vec[0]; rows=[]
        for i,t in enumerate(texts):
            emb=max(0.0,(_cos(q,vec[i+1])+1)/2); lex=lexical_overlap(query,t)
            rows.append((i,0.7*emb+0.3*lex,emb,lex,"hybrid-sentence-transformers"))
    except Exception:
        q=_local_embed(query); rows=[]
        for i,t in enumerate(texts):
            emb=max(0.0,(_cos(q,_local_embed(t))+1)/2); lex=lexical_overlap(query,t)
            rows.append((i,0.7*emb+0.3*lex,emb,lex,"hybrid-local-vector"))
    return sorted(rows,key=lambda x:x[1],reverse=True)
