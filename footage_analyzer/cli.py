import argparse
import json
from pathlib import Path
from .voiceover import transcribe, sentence_segments, save_transcript
from .indexer import build_index
from .matcher import build_visual_edl
from .visual import enrich_index
from .planner import plan, save_plan

def main():
    p=argparse.ArgumentParser(description="Voiceover-driven footage analyzer")
    sub=p.add_subparsers(dest="cmd",required=True)
    t=sub.add_parser("transcribe"); t.add_argument("voiceover"); t.add_argument("--out",default="workspace/voiceover.json")
    i=sub.add_parser("index"); i.add_argument("footage"); i.add_argument("--out",default="workspace/footage_index.json"); i.add_argument("--max-files",type=int)
    v=sub.add_parser("enrich"); v.add_argument("--index",default="workspace/footage_index.json"); v.add_argument("--out",default="workspace/visual_index.json"); v.add_argument("--limit",type=int)
    pl=sub.add_parser("plan"); pl.add_argument("--voiceover",default="workspace/voiceover.json"); pl.add_argument("--out",default="workspace/visual_plan.json")
    e=sub.add_parser("edl"); e.add_argument("--voiceover",default="workspace/voiceover.json"); e.add_argument("--index",default="workspace/visual_index.json"); e.add_argument("--plan",default="workspace/visual_plan.json"); e.add_argument("--out",default="workspace/edl.json")
    a=p.parse_args()
    if a.cmd=="transcribe":
        transcript=transcribe(a.voiceover); transcript["narration_segments"]=sentence_segments(transcript); save_transcript(transcript,a.out); print(f"Saved {len(transcript['narration_segments'])} narration segments to {a.out}")
    elif a.cmd=="index":
        build_index(a.footage,a.out,a.max_files)
    elif a.cmd=="enrich":
        enrich_index(a.index,a.out,a.limit)
    elif a.cmd=="plan":
        voice=json.loads(Path(a.voiceover).read_text(encoding="utf-8")); reqs=plan(voice["narration_segments"]); save_plan(reqs,a.out); print(f"Saved {len(reqs)} visual requirements to {a.out}")
    else:
        voice=json.loads(Path(a.voiceover).read_text(encoding="utf-8")); index=json.loads(Path(a.index).read_text(encoding="utf-8")); plan_data=json.loads(Path(a.plan).read_text(encoding="utf-8")); edl=build_visual_edl(voice["narration_segments"],plan_data["requirements"],index["shots"])
        Path(a.out).parent.mkdir(parents=True,exist_ok=True); Path(a.out).write_text(json.dumps({"version":2,"master":"voiceover","clips":edl},ensure_ascii=False,indent=2),encoding="utf-8"); print(f"Saved {len(edl)} timeline clips to {a.out}")

if __name__=="__main__": main()
