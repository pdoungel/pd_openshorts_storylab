# Footage Analyzer

Voiceover-first b-roll editing for OpenShorts / Story Lab: give it a voiceover (or a script) and a folder of voiceless clips, and it picks the best shot for every line, renders the finished video and writes the YouTube title, description and tags.

## Pipeline

1. **Narration** — upload a voiceover, or paste a script and Gemini TTS (`gemini-3.8-flash-tts`) narrates it. The voiceover is the master clock.
2. **Transcribe** — Gemini transcription with word timestamps; local faster-whisper fallback.
3. **Index** — PySceneDetect splits every clip into shots (a clip with no cut is one shot). Cached per file; unchanged files are skipped on later runs.
4. **Describe** — FFmpeg samples frames per shot and Gemini Vision describes what is visible, 8 shots per request. Only sampled frames leave the machine.
5. **Plan** — each narration line becomes a concrete visual intent, using the optional **visual cues** as alternatives.
6. **Match** — Gemini embeddings (`gemini-embedding-2`, cached on disk) shortlist shots per line, then a Gemini editor pass picks the best one, avoiding repeats.
7. **Metadata** — title options, description with YouTube-valid chapters, tags and hashtags.
8. **Render** — clips cut to the voiceover and rendered in **9:16, 16:9, 1:1 or 4:5** (fit with blurred background, center crop, or black bars). A finished job can be re-rendered in another format without re-analysis.

## Running it

**macOS (Docker, recommended):** `docker compose up --build footage-analyzer frontend`. `/Users` and `/Volumes` are mounted read-only so the folder picker resolves Finder folders.

**macOS / Linux (native):** needs Python 3.11+ and ffmpeg (`brew install python ffmpeg`), then `./run-analyzer.sh`.

**Windows (native):** needs Python 3.11+ and ffmpeg on PATH, then:

```powershell
python -m venv .venv-fa; .\.venv-fa\Scripts\pip install -r footage_analyzer\requirements.txt
powershell -ExecutionPolicy Bypass -File run-analyzer.ps1
```

Dashboard: `cd dashboard && npx vite --port 5175`, then open the **footage analyzer** tab. Either choose the footage folder or paste its path.

Put `GEMINI_API_KEY` in `.env` at the repository root.

## Where results go

- `exports/<voiceover>_<format>_<timestamp>.mp4` plus `.youtube.txt` (title, options, description, tags). Override with `FOOTAGE_EXPORT_DIR`.
- `workspace/footage_analyzer/<job id>/` holds the job state, `edl.json`, `metadata.json` and `final.mp4`.
- `workspace/footage_analyzer/library/` is the persistent per-folder index. **Clear index / free storage** in the UI removes it; original footage is never touched.

## Gemini quota

Free-tier keys allow roughly 20 requests per model per day. The analyzer batches vision requests and falls back across several models per stage (`footage_analyzer/gemini.py`); a model that reports its daily quota exhausted is skipped. When shots still cannot be analyzed, the job completes with a warning and finished work is kept, so a retry later continues where it stopped. Large libraries need a billed key.

## Configuration

| Variable | Purpose |
|---|---|
| `FOOTAGE_VISION_MODEL`, `FOOTAGE_PLANNER_MODEL`, `FOOTAGE_RERANK_MODEL`, `FOOTAGE_METADATA_MODEL` | Comma-separated model fallback list per stage |
| `FOOTAGE_TTS_MODEL`, `FOOTAGE_TTS_VOICE`, `FOOTAGE_TTS_STYLE` | Script narration |
| `FOOTAGE_EMBED_MODEL`, `FOOTAGE_EMBEDDINGS=local` | Embedding model, or offline ranking |
| `FOOTAGE_VISUAL_BATCH` | Shots per vision request (default 8) |
| `FOOTAGE_RENDER_FPS`, `FOOTAGE_RENDER_PRESET`, `FOOTAGE_RENDER_WORKERS` | Render settings |
| `FOOTAGE_SEARCH_ROOTS` | Where the folder picker searches (path-separator list) |
| `FOOTAGE_EXPORT_DIR` | Export folder |

## CLI

```bash
python -m footage_analyzer.cli transcribe /path/to/voiceover.wav --out workspace/voiceover.json
python -m footage_analyzer.cli index /path/to/footage --out workspace/footage_index.json --max-files 1
python -m footage_analyzer.cli enrich --index workspace/footage_index.json --out workspace/visual_index.json --limit 5
python -m footage_analyzer.cli plan --voiceover workspace/voiceover.json --out workspace/visual_plan.json
python -m footage_analyzer.cli edl --voiceover workspace/voiceover.json --index workspace/visual_index.json --plan workspace/visual_plan.json --out workspace/edl.json
```
