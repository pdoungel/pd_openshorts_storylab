"""Self-contained semantic and lexical ranking for Footage Analyzer."""
from __future__ import annotations
import hashlib, json, math, os, re, threading, time
from functools import lru_cache
from pathlib import Path
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
_gemini_lock=threading.Lock()
_gemini_cache=None
_gemini_disabled=False

def _gemini_cache_path():
    root=os.getenv("FOOTAGE_ANALYZER_WORKDIR","workspace/footage_analyzer")
    return Path(root)/"library"/"embeddings_cache.json"

def _gemini_embed(texts):
    """Embed texts with Gemini, caching vectors on disk keyed by model+text."""
    global _gemini_cache
    from google import genai
    from google.genai import types
    key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key: raise RuntimeError("no Gemini key")
    model=os.getenv("FOOTAGE_EMBED_MODEL","gemini-embedding-2")
    with _gemini_lock:
        if _gemini_cache is None:
            try: _gemini_cache=json.loads(_gemini_cache_path().read_text(encoding="utf-8"))
            except Exception: _gemini_cache={}
        keys=[hashlib.sha1(f"{model}|{t}".encode()).hexdigest() for t in texts]
        missing=[(k,t) for k,t in dict(zip(keys,texts)).items() if k not in _gemini_cache]
        if missing:
            from concurrent.futures import ThreadPoolExecutor
            client=genai.Client(api_key=key)
            # gemini-embedding-2 folds a list of contents into one vector, so embed texts individually.
            def one(text):
                res=client.models.embed_content(
                    model=model,contents=text or " ",
                    config=types.EmbedContentConfig(output_dimensionality=768),
                )
                v=list(res.embeddings[0].values); n=math.sqrt(sum(x*x for x in v)) or 1.0
                return [round(x/n,6) for x in v]
            with ThreadPoolExecutor(max_workers=8) as pool:
                for (k,_),vec in zip(missing,pool.map(one,[t for _,t in missing])):
                    _gemini_cache[k]=vec
            from .cache import atomic_json
            atomic_json(_gemini_cache_path(),_gemini_cache)
        return [_gemini_cache[k] for k in keys]

def warm(texts):
    """Embed every text up front in one parallel pass so ranking hits the cache."""
    if os.getenv("FOOTAGE_EMBEDDINGS","gemini")!="gemini" or not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        return
    try:
        _gemini_embed(list(dict.fromkeys(texts)))
    except Exception as exc:
        print(f"[footage-analyzer] embedding warm-up failed: {exc}",flush=True)

def rank_texts(query,texts):
    global _gemini_disabled
    if _gemini_disabled and time.monotonic()-_gemini_disabled>120:
        _gemini_disabled=False
    if not _gemini_disabled and os.getenv("FOOTAGE_EMBEDDINGS","gemini")=="gemini" and (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        try:
            import numpy as np
            vecs=_gemini_embed([query]+list(texts))
            sims=np.asarray(vecs[1:],dtype=np.float32)@np.asarray(vecs[0],dtype=np.float32) if texts else []
            rows=[]
            for i,t in enumerate(texts):
                emb=max(0.0,float(sims[i])); lex=lexical_overlap(query,t)
                rows.append((i,0.8*emb+0.2*lex,emb,lex,"hybrid-gemini-embedding"))
            return sorted(rows,key=lambda x:x[1],reverse=True)
        except Exception as exc:
            print(f"[footage-analyzer] Gemini embeddings unavailable, using local ranking: {exc}",flush=True)
            _gemini_disabled=time.monotonic()
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
