"""Job orchestration for the independent Footage Analyzer backend."""
from __future__ import annotations
import json, os, threading, traceback, uuid
from pathlib import Path
from .voiceover import transcribe, sentence_segments
from .indexer import build_index
from .visual import enrich_index
from .planner import plan
from .matcher import build_visual_edl
from .cache import cache_dir, cache_size, human_size, seed_from_job, clear_cache

class JobStore:
    def __init__(self, root=None):
        self.root=Path(root or os.getenv("FOOTAGE_ANALYZER_WORKDIR","workspace/footage_analyzer")).expanduser()
        self.root.mkdir(parents=True,exist_ok=True)
        self.jobs={}; self.lock=threading.RLock()

    def _save(self,j):
        p=self.root/j["id"]; p.mkdir(parents=True,exist_ok=True)
        tmp=p/"job.json.tmp"; tmp.write_text(json.dumps(j,ensure_ascii=False,indent=2),encoding="utf-8"); tmp.replace(p/"job.json")

    def create(self,voiceover,footage_root,instruction=""):
        jid=str(uuid.uuid4()); root=str(Path(footage_root).expanduser().resolve())
        job={"id":jid,"status":"queued","stage":"queued","progress":0,"message":"Queued",
             "voiceover":voiceover,"footage_root":root,"instruction":instruction,"error":None,"result":None}
        with self.lock:
            self.jobs[jid]=job; self._save(job)
        threading.Thread(target=self.run,args=(jid,),daemon=True).start()
        return job

    def get(self,jid):
        with self.lock:
            if jid in self.jobs:return dict(self.jobs[jid])
        p=self.root/jid/"job.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def update(self,jid,**kw):
        with self.lock:
            if jid not in self.jobs: return
            self.jobs[jid].update(kw); self._save(self.jobs[jid])

    def _find_previous_job(self,root):
        root=str(Path(root).resolve()); best=None
        for p in self.root.iterdir():
            if not p.is_dir() or p.name=="library": continue
            meta=p/"job.json"
            if not meta.exists(): continue
            try:
                j=json.loads(meta.read_text(encoding="utf-8"))
                if str(Path(j.get("footage_root","")).resolve())==root:
                    if best is None or meta.stat().st_mtime > best[1]: best=(p,meta.stat().st_mtime)
            except Exception: pass
        return best[0] if best else None

    def cache_status(self,root):
        c=cache_dir(self.root,root); size=cache_size(c)
        manifest=c/"file_manifest.json"; visual=c/"visual_index.json"
        stats={}
        try: stats=json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
        except Exception: stats={}
        entries=list(stats.values()); total=len(entries)
        complete=sum(1 for x in entries if x.get("status")=="complete")
        failed=sum(1 for x in entries if x.get("status")=="failed")
        visual_done=0
        if visual.exists():
            try: visual_done=sum(1 for x in json.loads(visual.read_text(encoding="utf-8")).get("shots",[]) if x.get("description"))
            except Exception: pass
        return {"root":str(Path(root).resolve()),"cache_path":str(c),"size_bytes":size,
                "size":human_size(size),"files_total":total,"files_indexed":complete,
                "files_failed":failed,"visual_shots_completed":visual_done}

    def clear_cache(self,root):
        return clear_cache(self.root,root)

    def run(self,jid):
        j=self.get(jid); work=self.root/jid
        root=j["footage_root"]; cache=cache_dir(self.root,root)
        try:
            previous=self._find_previous_job(root)
            if previous: seed_from_job(cache,previous)
            work.mkdir(parents=True,exist_ok=True)
            voice=work / ("voiceover" + Path(j["voiceover"]).suffix)
            if not voice.exists():
                src=Path(j["voiceover"]); voice.parent.mkdir(parents=True,exist_ok=True)
                import shutil; shutil.copy2(src,voice)
            tr_path=work/"voiceover.json"
            if tr_path.exists():
                tr=json.loads(tr_path.read_text(encoding="utf-8"))
            else:
                self.update(jid,status="processing",stage="transcription",progress=5,message=f"Transcribing voiceover · {voice.name}")
                tr=transcribe(str(voice))
                tr_path.write_text(json.dumps(tr,ensure_ascii=False,indent=2),encoding="utf-8")
            narr=sentence_segments(tr)
            if not narr: raise RuntimeError("No speech segments were detected in the voiceover.")

            self.update(jid,stage="indexing",progress=20,message="Resuming persistent footage index…")
            idx=cache/"footage_index.json"
            def index_progress(done,total,name,stats=None):
                s=stats or {}
                self.update(jid,progress=20+int(15*done/max(total,1)),
                            message=f"Indexing footage · {done}/{total} · reused {s.get('reused',0)} · {name}",
                            index_stats=s)
            shots=build_index(root,str(idx),progress=index_progress)
            if not shots: raise RuntimeError("No video files were found in the selected footage folder.")

            self.update(jid,stage="visual_analysis",progress=35,message=f"Resuming visual analysis · {len(shots)} shots")
            vis=cache/"visual_index.json"
            def visual_progress(done,total,current,stats=None):
                s=stats or {}
                self.update(jid,progress=35+int(35*done/max(total,1)),
                            message=f"Visual analysis · {done}/{total} · reused {s.get('reused',0)} · {current}",
                            visual_stats=s)
            data=enrich_index(str(idx),str(vis),progress=visual_progress)

            self.update(jid,stage="visual_plan",progress=72,message="Planning visual intent from narration")
            req=plan(narr,j["instruction"])
            (work/"visual_plan.json").write_text(json.dumps({"version":2,"requirements":req},ensure_ascii=False,indent=2),encoding="utf-8")
            self.update(jid,stage="matching",progress=84,message="Matching narration to footage")
            edl=build_visual_edl(narr,req,data.get("shots",[]))
            duration=max((float(x["end"]) for x in narr),default=0)
            result={"version":3,"master":"voiceover","voiceover_duration":duration,"clips":edl,
                    "requirements":req,"shot_count":len(data.get("shots",[]))}
            (work/"edl.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
            self.update(jid,status="complete",stage="complete",progress=100,
                        message=f"Complete · {len(edl)} timeline clips",result=result,index_stats=self.cache_status(root))
        except Exception as e:
            self.update(jid,status="failed",stage="error",progress=0,message=str(e),
                        error={"type":type(e).__name__,"message":str(e),"traceback":traceback.format_exc(),
                               "index_stats":self.cache_status(root)})

