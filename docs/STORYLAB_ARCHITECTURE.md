# Story Lab architecture

Story Lab is an additive subsystem. Shorts jobs, clip selection, social publishing, and existing project state are not modified by Story Lab analysis. The current integration points are FastAPI router registration and the existing text-only LLM adapter.

## Layers

1. API: /api/storylab/* in storylab/routes.py.
2. Domain contracts: storylab/models.py.
3. Persistence: storylab/service.py, stored under output/storylab/.
4. Ingestion: `storylab/ingestion.py` accepts project-owned video, audio, PDF, timed transcript, and text sources. Media metadata is probed locally; optional transcription calls the existing ASR adapter only when explicitly requested.
5. Analysis: storylab/analyzer.py uses llm_backend only when an OpenAI-compatible local endpoint is configured; otherwise it returns a deterministic non-fictional fallback.
6. Evidence: storylab/evidence.py records source ID, supporting quote, page/timestamp, confidence, and traceability. It never upgrades unlocated prose into a precise citation.
7. Story/script: storylab/script.py builds hook, context, events, conflict, consequences and significance into reviewable documentary sections with visual research classifications.
8. Review/render: every script section must be approved before `storylab/renderer.py` extracts source-backed visual ranges and creates a render manifest. Contextual/generated visuals remain clearly labelled for editorial sourcing.
8. UI: StoryLabTab.jsx is a separate dashboard destination.

## Planned next layers

- A full 16:9 composition layer that mixes narration audio, editor-supplied contextual assets, and generated assets. The present renderer assembles only approved source footage and writes a manifest for the remaining editorial assets.
- Browser playback, an inline script editor, and optional teaser-short export. These are intentionally not coupled to the Shorts job lifecycle.

## Evidence policy
Exact timestamps must come from a source with timing data or a verified scene-extraction result. LLM prose alone is never treated as timestamp evidence.

## Local integration requirement
Repository CI proves isolated Story Lab contracts and the dashboard build. Real movie/episode processing, ffmpeg extraction, Docker wiring, and Gemini/Ollama behavior require local integration tests with real media and the user's environment.
