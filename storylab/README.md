# Story Lab

Story Lab is the long-form documentary/research subsystem for OpenShorts. It is isolated from Shorts job state and is designed to work without a paid AI API.

## Current pipeline

source → ingestion → evidence → story → documentary script → visual plan → review → render

### Sources

Story Lab accepts:
- PDF documents (local text extraction with pypdf)
- video/audio (local ffprobe metadata and optional local transcription)
- SRT/VTT/JSON timed transcripts
- plain text / Markdown

Uploaded sources are copied into a project-owned Story Lab directory and receive a SHA-256 checksum. Source records retain page numbers, timestamps and quoted supporting text where available.

### Evidence and traceability

Evidence is never allowed to silently invent a timestamp or page. Each evidence item records:
- source ID
- page and/or timestamp when available
- supporting source text
- confidence
- traceability (`source`, `derived`, `unverified`)

Plain text can still be useful for analysis, but it is explicitly marked unverified when it has no precise locator.

### Free/local AI plan

The application does **not require a paid model**.

If `LLM_BASE_URL` points to an OpenAI-compatible local server such as Ollama, LM Studio, llama.cpp or vLLM, Story Lab uses that model for higher-level story analysis. If no local model is active, Story Lab automatically falls back to deterministic analysis and still builds evidence and a documentary outline.

Example with Ollama:

    ollama serve
    ollama pull qwen2.5:7b
    export LLM_PROVIDER=ollama
    export LLM_BASE_URL=http://127.0.0.1:11434/v1
    export LLM_MODEL=qwen2.5:7b

A general instruction model is preferable to a coder-only model for documentary analysis. The existing `llm_backend.py` also supports other OpenAI-compatible local servers.

Video/audio transcription uses the existing local Whisper/Parakeet pipeline. PDF extraction is local. Therefore the core Story Lab workflow remains usable with **zero API spend**.

### Review and rendering

Script sections must be explicitly approved before rendering. Source-backed video visuals can be extracted through the existing FFmpeg primitive. Contextual and generated visuals are recorded in the manifest but are never silently treated as source footage.

The render output includes a machine-readable `render-manifest.json` so an editor can see which narration section maps to which evidence and source clip.

## API

- `POST /api/storylab/projects`
- `GET /api/storylab/projects`
- `GET /api/storylab/projects/{id}`
- `POST /api/storylab/projects/{id}/sources/text`
- `POST /api/storylab/projects/{id}/sources/upload`
- `POST /api/storylab/projects/{id}/analyze`
- `POST /api/storylab/projects/{id}/review`
- `POST /api/storylab/projects/{id}/render`

## Validation

Story Lab has an isolated pytest suite and a dedicated GitHub Actions workflow. The tests cover source ingestion, timestamp normalization, traceability and the review gate before rendering.