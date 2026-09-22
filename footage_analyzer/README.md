# Footage Analyzer MVP

Voiceover-first footage planning for OpenShorts / Story Lab.

The voiceover is the master clock. The system first produces timestamped narration segments, then indexes local footage into reusable shots, then builds an edit-decision list (EDL). Footage never determines narration timing.

## Current MVP

- transcribe: reuses the existing OpenShorts/Story Lab faster-whisper backend.
- index: recursively scans local video and reuses scene_detection.py.
- edl: creates a transparent baseline EDL and preserves alternatives.

## Usage

From the repository root:

python -m footage_analyzer.cli transcribe /path/to/voiceover.wav
python -m footage_analyzer.cli index /path/to/footage --out workspace/footage_index.json
python -m footage_analyzer.cli edl

The EDL is the contract for the next phase: visual descriptions/embeddings, Gemini visual-intent planning, review UI, and direct timeline/render integration.

The baseline matcher deliberately does not claim a shot visually matches merely because its filename matches. Until visual enrichment is enabled, scores are primarily duration-based.
