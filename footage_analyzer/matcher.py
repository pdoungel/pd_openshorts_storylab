"""Semantic visual matcher and voiceover-master EDL builder."""
from __future__ import annotations

def _text(shot):
    return " ".join([shot.get("description","")," ".join(shot.get("subjects",[]))," ".join(shot.get("actions",[]))," ".join(shot.get("setting",[]))," ".join(shot.get("tags",[]))])

def rank(requirement,shots,topn=5):
    from storylab.embeddings import rank_texts
    texts=[_text(s) for s in shots]; rows=rank_texts(requirement.get("visual_query",""),texts,mode="hybrid",provider="auto")
    return [{"shot":shots[i],"score":round(score,4),"embedding_score":round(emb,4),"lexical_score":round(lex,4),"method":method} for i,score,emb,lex,method in rows[:topn]]

def build_visual_edl(narrations,requirements,shots):
    by_index={r["narration_index"]:r for r in requirements}; used=set(); edl=[]
    for n in narrations:
        req=by_index.get(n["index"],{"narration_index":n["index"],"visual_query":n["text"]})
        candidates=rank(req,[s for s in shots if s["id"] not in used],10) or rank(req,shots,10)
        if not candidates: continue
        best=candidates[0]; shot=best["shot"]; required=float(n["end"])-float(n["start"])
        source_start=float(shot["start"]); source_end=min(float(shot["end"]),source_start+required)
        source_duration=source_end-source_start; fit=min(1.0,source_duration/max(required,0.001))
        used.add(shot["id"])
        edl.append({"timeline_start":float(n["start"]),"timeline_end":float(n["end"]),"duration":required,
                    "source_path":shot["video_path"],"source_start":source_start,"source_end":source_end,
                    "source_duration":source_duration,"narration_index":n["index"],"narration":n["text"],
                    "visual_query":req["visual_query"],"score":round(0.85*best["score"]+0.15*fit,4),
                    "match_method":best["method"],"duration_fit":round(fit,4),
                    "reason":"source is shorter than narration; needs secondary shot/hold" if fit<1 else "semantic visual match with duration fit",
                    "alternatives":[{"shot_id":x["shot"]["id"],"source_path":x["shot"]["video_path"],"score":x["score"]} for x in candidates[1:5]]})
    return edl
