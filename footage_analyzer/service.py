"""Job orchestration for the independent Footage Analyzer backend."""
from __future__ import annotations
import json, os, threading, traceback, uuid, time
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
        original_name=Path(voiceover).name
        job={"id":jid,"status":"processing","stage":"starting","progress":0,"message":"Starting analyzer worker…","current_file":"",
             "voiceover":voiceover,"voiceover_original_name":original_name,"voiceover_job_path":"",
             "voiceover_sha256":"","voiceover_duration":0,"transcript_segment_count":0,
             "footage_root":root,"instruction":instruction,"error":None,"result":None,
             "updated_at":time.time(),"update_seq":0}
        with self.lock:
            self.jobs[jid]=job; self._save(job)
        threading.Thread(target=self._run_wrapper,args=(jid,),daemon=True,name=f"footage-analyzer-{jid[:8]}").start()
        return job

    def _run_wrapper(self,jid):
        try:
            self.run(jid)
        except Exception as e:
            j=self.get(jid)
            if j and j.get("status") not in {"complete","failed"}:
                root=j.get("footage_root","")
                self.update(jid,status="failed",stage="error",progress=0,message=str(e),
                             error={"type":type(e).__name__,"message":str(e),"traceback":traceback.format_exc(),
                                    "index_stats":self.cache_status(root) if root else {}})

    def get(self,jid):
        # Persisted job.json is authoritative. This prevents the UI from
        # remaining on the initial POST response after a process restart.
        p=self.root/jid/"job.json"
        try:
            if p.exists():
                disk=json.loads(p.read_text(encoding="utf-8"))
                with self.lock:
                    self.jobs[jid]=dict(disk)
                return disk
        except Exception:
            pass
        with self.lock:
            return dict(self.jobs[jid]) if jid in self.jobs else None

    def update(self,jid,**kw):
        with self.lock:
            job=self.jobs.get(jid)
            if job is None:
                p=self.root/jid/"job.json"
                if not p.exists(): return
                try: job=json.loads(p.read_text(encoding="utf-8"))
                except Exception: return
                self.jobs[jid]=job
            job.update(kw)
            job["updated_at"]=time.time()
            job["update_seq"]=int(job.get("update_seq",0))+1
            self._save(job)

    def _find_previous_job(self,root,exclude=None):
        root=str(Path(root).resolve()); best=None
        for p in self.root.iterdir():
            if not p.is_dir() or p.name=="library" or p.name==exclude: continue
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
            self.update(jid,status="processing",stage="starting",progress=1,message="Analyzer worker started…",current_file="")
            previous=self._find_previous_job(root,jid)
            if previous:
                self.update(jid,stage="resuming",progress=2,message="Resuming persistent index…",current_file="")
                seed_from_job(cache,previous)
            work.mkdir(parents=True,exist_ok=True)
            # Keep the exact uploaded filename inside the job directory so the
            # UI and persisted job state can prove which file is being processed.
            src=Path(j["voiceover"]).resolve()
            voice=work / Path(j.get("voiceover_original_name") or src.name).name
            voice.parent.mkdir(parents=True,exist_ok=True)
            if not voice.exists():
                import shutil; shutil.copy2(src,voice)
            self.update(jid,stage="transcription",progress=4,
                        message=f"🎙️ Uploaded voiceover confirmed · {voice.name}",
                        current_file=voice.name,voiceover_original_name=src.name,
                        voiceover_job_path=str(voice))
            tr_path=work/"voiceover.json"
            # Keep the transcript in the persistent footage-library cache too.
            # A new job after a crash/restart can therefore reuse transcription
            # instead of starting the whole voiceover stage again.
            import hashlib
            self.update(jid,status="processing",stage="transcription",progress=5,
                        message=f"🎙️ Preparing audio transcription · {voice.name}",current_file=voice.name)
                        # Stream the hash so a large WAV cannot block the worker at 5% while
            # the entire file is loaded into RAM.
            digest=hashlib.sha256()
            with voice.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    digest.update(chunk)
            voice_sha256=digest.hexdigest()
            self.update(jid,stage="transcription",progress=5,
                        message=f"🎙️ Processing uploaded file · {voice.name} · SHA256 {voice_sha256[:12]}…",
                        current_file=voice.name,voiceover_original_name=src.name,
                        voiceover_job_path=str(voice),voiceover_sha256=voice_sha256)
            cached_tr_path=cache/"voiceover_cache.json"
            cached_tr=None
            if cached_tr_path.exists():
                try:
                    cached=json.loads(cached_tr_path.read_text(encoding="utf-8"))
                    if cached.get("sha256")==voice_sha256 and cached.get("transcript"):
                        cached_tr=cached["transcript"]
                except Exception:
                    cached_tr=None

            if tr_path.exists():
                tr=json.loads(tr_path.read_text(encoding="utf-8"))
                self.update(jid,status="processing",stage="transcription",progress=8,
                            message=f"Voiceover transcription reused · {voice.name}",current_file=voice.name)
            elif cached_tr is not None:
                tr=cached_tr
                tr_path.write_text(json.dumps(tr,ensure_ascii=False,indent=2),encoding="utf-8")
                self.update(jid,status="processing",stage="transcription",progress=8,
                            message=f"Voiceover transcription reused · {voice.name}",current_file=voice.name)
            else:
                self.update(jid,status="processing",stage="transcription",progress=5,
                            message=f"🎙️ Transcribing audio · {voice.name}",current_file=voice.name)
                def transcription_progress(pct, duration, message):
                    # voiceover.py reports the analyzer-wide 5–20% range directly.
                    # Do not remap it again or the UI would remain near 5%.
                    self.update(
                        jid,
                        status="processing",
                        stage="transcription",
                        progress=max(5, min(20, int(pct))),
                        message=message,
                        current_file=voice.name,
                    )
                tr=transcribe(str(voice), progress=transcription_progress)
                tr_path.write_text(json.dumps(tr,ensure_ascii=False,indent=2),encoding="utf-8")
                from .cache import atomic_json
                atomic_json(cached_tr_path,{"version":1,"sha256":voice_sha256,"transcript":tr})
                self.update(jid,status="processing",stage="transcription",progress=18,
                            message=f"🎙️ Transcription complete · {voice.name}",current_file=voice.name)
            narr=sentence_segments(tr)
            self.update(jid,stage="transcription",progress=20,
                        message=f"🎙️ Voiceover ready · {voice.name} · {len(narr)} transcript segments",
                        current_file=voice.name,transcript_segment_count=len(narr),
                        voiceover_duration=float(tr.get("duration",0) or 0))
            if not narr: raise RuntimeError("No speech segments were detected in the voiceover.")

            self.update(jid,stage="indexing",progress=20,message="Resuming persistent footage index…")
            idx=cache/"footage_index.json"
            def index_progress(done,total,name,stats=None):
                s=dict(stats or {})
                s.update({"done":done,"total":total})
                self.update(jid,progress=20+int(15*done/max(total,1)),
                            message=f"Indexing footage · {done}/{total} · reused {s.get('reused',0)} · {name}",
                            current_file=name,index_stats=s)
            shots=build_index(root,str(idx),progress=index_progress)
            if not shots: raise RuntimeError("No video files were found in the selected footage folder.")

            self.update(jid,stage="visual_analysis",progress=35,message=f"Resuming visual analysis · {len(shots)} shots")
            vis=cache/"visual_index.json"
            def visual_progress(done,total,current,stats=None):
                s=dict(stats or {})
                s.update({"done":done,"total":total})
                self.update(jid,progress=35+int(35*done/max(total,1)),
                            message=f"Visual analysis · scene {done}/{total} · reused {s.get('reused',0)} · {current}",
                            current_file=current,visual_stats=s)
            data=enrich_index(str(idx),str(vis),progress=visual_progress)
            analyzed_shots=[s for s in data.get("shots",[]) if str(s.get("description","")).strip()]
            visual_failed=sum(1 for s in data.get("shots",[]) if not str(s.get("description","")).strip())
            self.update(
                jid,
                stage="visual_analysis",
                progress=70,
                message=f"Visual analysis complete · {len(analyzed_shots)} usable scenes · {visual_failed} failed/retry",
                current_file="",
                visual_stats={
                    "done": len(data.get("shots",[])),
                    "total": len(data.get("shots",[])),
                    "reused": int(self.get(jid).get("visual_stats",{}).get("reused",0) or 0),
                    "failed": visual_failed,
                    "usable": len(analyzed_shots),
                },
            )
            if not analyzed_shots:
                raise RuntimeError(
                    "Visual analysis produced no usable scenes. Check the Gemini API/key "
                    "and retry; completed indexing is preserved."
                )

            self.update(jid,stage="visual_plan",progress=72,message="Planning visual intent from narration")
            req=plan(narr,j["instruction"])
            (work/"visual_plan.json").write_text(
                json.dumps({"version":2,"requirements":req},ensure_ascii=False,indent=2),
                encoding="utf-8",
            )
            self.update(
                jid,
                stage="matching",
                progress=84,
                message=f"Matching {len(narr)} narration segments to {len(analyzed_shots)} usable scenes",
            )
            edl=build_visual_edl(narr,req,analyzed_shots)
            duration=max((float(x["end"]) for x in narr),default=0)
            result={
                "version":4,
                "master":"voiceover",
                "voiceover_duration":duration,
                "clips":edl,
                "requirements":req,
                "narration_segments":len(narr),
                "shot_count":len(analyzed_shots),
                "visual_failed":visual_failed,
                "timeline_order":"voiceover",
                "coverage_complete":True,
            }
            (work/"edl.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
            self.update(jid,status="complete",stage="complete",progress=100,
                        message=f"Complete · {len(edl)} timeline clips",result=result,index_stats=self.cache_status(root))
        except Exception as e:
            self.update(jid,status="failed",stage="error",progress=0,message=str(e),
                        error={"type":type(e).__name__,"message":str(e),"traceback":traceback.format_exc(),
                               "index_stats":self.cache_status(root)})

