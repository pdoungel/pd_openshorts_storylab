# Story Lab architecture

Story Lab is an additive subsystem. Shorts jobs, clip selection, social publishing, and existing project state are not modified by Story Lab analysis. The current integration points are FastAPI router registration and the existing text-only LLM adapter.

## Layers

1. API: /api/storylab/* in storylab/routes.py.
2. Domain contracts: storylab/models.py.
3. Persistence: storylab/service.py, stored under output/storylab/.
4. Analysis: storylab/analyzer.py. It uses llm_backend only when an OpenAI-compatible local endpoint is configured; otherwise it returns a deterministic non-fictional fallback.
5. Evidence: storylab/evidence.py normalizes ranges and refuses to invent timestamps.
6. Script: storylab/script.py turns analysis into a documentary outline.
7. Rendering primitive: storylab/renderer.py extracts a source range with ffmpeg.
8. UI: StoryLabTab.jsx is a separate dashboard destination.

## Planned next layers

- Source/media ingestion and ffprobe metadata.
- Timestamp-preserving transcript ingestion through an adapter to existing ASR/subtitle infrastructure, without changing Shorts.
- Evidence browser with clickable timestamp playback.
- Scene extraction queue and scene manifest.
- Documentary script editor with evidence references.
- 16:9 Remotion/renderer composition and final-video artifact tracking.
- Optional teaser-short export through an explicit handoff into the existing clip renderer.

## Evidence policy
Exact timestamps must come from a source with timing data or a verified scene-extraction result. LLM prose alone is never treated as timestamp evidence.

## Local integration requirement
Repository CI proves isolated Story Lab contracts and the dashboard build. Real movie/episode processing, ffmpeg extraction, Docker wiring, and Gemini/Ollama behavior require local integration tests with real media and the user's environment.
