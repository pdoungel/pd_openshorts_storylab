from __future__ import annotations
import os, subprocess
from pathlib import Path
def extract_scene(source_path: str, output_path: str, start: float, end: float) -> str:
    if not os.path.isfile(source_path): raise FileNotFoundError(source_path)
    if end <= start: raise ValueError("Scene end must be greater than start")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg","-y","-ss",f"{start:.3f}","-i",source_path,"-t",f"{end-start:.3f}","-c","copy",output_path],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=1800)
    return output_path
