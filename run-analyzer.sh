#!/usr/bin/env bash
# Run the Footage Analyzer natively on macOS/Linux (no Docker).
# Needs python3 (3.11+) and ffmpeg on PATH (macOS: brew install python ffmpeg).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv-fa ]; then
  python3 -m venv .venv-fa
  .venv-fa/bin/pip install -q -r footage_analyzer/requirements.txt
fi

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

export FOOTAGE_ANALYZER_WORKDIR="$PWD/workspace/footage_analyzer"
export PYTHONUNBUFFERED=1
exec .venv-fa/bin/python -m uvicorn footage_analyzer.server:app --host 127.0.0.1 --port 8010
