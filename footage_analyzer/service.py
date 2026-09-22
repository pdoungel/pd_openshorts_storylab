"""Job orchestration for the independent Footage Analyzer backend."""
from __future__ import annotations
import json, os, threading, traceback, uuid
from pathlib import Path
from .voiceover import transcribe, sentence_segments
from .indexer import build_index
from .visual import enrich_index
from .planner import plan
from .matcher import build_visual_edl

class JobStore:
    def __init__(self, root=None):
        self.root=Path(root or os.getenv("FOOTAGE_ANALYZER_WORKDIR","workspace/footage_analyzer")).expanduser()
        self.root.mkdir(parents=True,exist_ok=True)
        self.jobs={}
        self.lock=threading.Lock()

    def _save(self,j):
        p=self.root/j["id"]; p.mkdir(parents=True,exist_ok=True)
        (p/"job.json").write_text(json.dumps(j,ensure_ascii=False,indent=2),encoding="utf-8")

    def create(self,voiceover,footage_root,instruction=""):
        jid=str(uuid.uuid4())
        job={"id":jid,"status":"queued","stage":"queued","progress":0,"message":"Queued",
             "voiceover":voiceover,"footage_root":str(Path(footage_root).expanduser().resolve()),
             "instruction":instruction,"error":None,"result":None}
        with self.lock:
            self.jobs[jid]=job
            self._save(job)
        threading.Thread(target=self.run,args=(jid,),daemon=True).start()
        return job

    def get(self,jid):
        with self.lock:
            if jid in self.jobs:return dict(self.jobs[jid])
        p=self.root/jid/"job.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def update(self,jid,**kw):
        with self.lock:
            self.jobs[jid].update(kw)
            self._save(self.jobs[jid])

    def run(self,jid):
        j=self.get(jid)
        work=self.root/jid
        try:
            voice=work / ("voiceover" + Path(j["voiceover"]).suffix)
            if not voice.exists():
                # server stages the upload at incoming; copy it into the job for durability
                src=Path(j["voiceover"]); voice.parent.mkdir(parents=True,exist_ok=True)
                import shutil; shutil.copy2(src,voice)
            self.update(jid,status="processing",stage="transcription",progress=5,message="Transcribing voiceover")
            tr=transcribe(str(voice))
            (work/"voiceover.json").write_text(json.dumps(tr,ensure_ascii=False,indent=2),encoding="utf-8")
            narr=sentence_segments(tr)
            if not narr: raise RuntimeError("No speech segments were detected in the voiceover.")

            self.update(jid,stage="indexing",progress=20,message="Detecting shots in footage")
            idx=work/"footage_index.json"
            shots=build_index(j["footage_root"],str(idx))
            if not shots: raise RuntimeError("No video files were found in the selected footage folder.")

            self.update(jid,stage="visual_analysis",progress=35,message=f"Analyzing footage frames · 0/{len(shots)}")
            vis=work/"visual_index.json"
            data=enrich_index(str(idx),str(vis),
                              progress=lambda done,total:self.update(
                                  jid,progress=35+int(35*done/max(total,1)),
                                  message=f"Visual analysis · {done}/{total} shots"))
            self.update(jid,stage="visual_plan",progress=72,message="Planning visual intent from narration")
            req=plan(narr,j["instruction"])
            (work/"visual_plan.json").write_text(json.dumps({"version":2,"requirements":req},ensure_ascii=False,indent=2),encoding="utf-8")

            self.update(jid,stage="matching",progress=84,message="Matching narration to footage")
            edl=build_visual_edl(narr,req,data.get("shots",[]))
            duration=max((float(x["end"]) for x in narr),default=0)
            result={"version":3,"master":"voiceover","voiceover_duration":duration,
                    "clips":edl,"requirements":req,"shot_count":len(data.get("shots",[]))}
            (work/"edl.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
            self.update(jid,status="complete",stage="complete",progress=100,
                        message=f"Complete · {len(edl)} timeline clips",result=result)
        except Exception as e:
            self.update(jid,status="failed",stage="error",progress=0,message=str(e),
                        error={"type":type(e).__name__,"message":str(e),"traceback":traceback.format_exc()})
