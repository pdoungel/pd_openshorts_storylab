# Footage Analyzer — Phase 2

Voiceover-first visual matching for OpenShorts / Story Lab.

Pipeline:
1. transcribe — existing faster-whisper transcript; voiceover is the master clock.
2. index — existing TransNetV2/PySceneDetect creates reusable shots.
3. enrich — FFmpeg samples 3 representative frames per shot and Gemini Vision describes visible content. Results are cached.
4. plan — Gemini turns each narration segment into a concrete visual requirement.
5. edl — Story Lab embeddings rank actual visual descriptions against the visual requirement and build a duration-aware EDL with alternatives.

Gemini is used for the vision/reasoning stages. Raw footage stays local except for sampled contact-sheet images sent for visual analysis. Do not use this mode for footage that cannot be sent to a third-party API.

Test from repository root after setting GEMINI_API_KEY:
python -m footage_analyzer.cli transcribe /path/to/voiceover.wav --out workspace/voiceover.json
python -m footage_analyzer.cli index /path/to/footage --out workspace/footage_index.json --max-files 1
python -m footage_analyzer.cli enrich --index workspace/footage_index.json --out workspace/visual_index.json --limit 5
python -m footage_analyzer.cli plan --voiceover workspace/voiceover.json --out workspace/visual_plan.json
python -m footage_analyzer.cli edl --voiceover workspace/voiceover.json --index workspace/visual_index.json --plan workspace/visual_plan.json --out workspace/edl.json

## Persistent indexing

The analyzer stores a durable per-footage-library cache under `workspace/footage_analyzer/library/`. Each video gets a fingerprint (size + modification time) and an atomic status record. Successful files are reused on later runs; changed files are re-indexed; failed or interrupted files are retried. Visual shot descriptions are also saved atomically after each shot.

The existing per-job `footage_index.json` and `visual_index.json` are automatically migrated into the persistent cache the first time that footage folder is analyzed, so previously completed analyses are preserved.

The dashboard exposes the cache size, indexed/total file count, completed visual-analysis count, failed/retry count, and **Clear Index / Free Storage**. Clearing removes only analyzer-generated cache data; original footage is never deleted.

The Docker Compose configuration mounts `./workspace` so the persistent index survives analyzer-container restarts.

Start small before indexing the complete library.
