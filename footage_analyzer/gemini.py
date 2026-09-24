"""Shared Gemini text/vision caller with model fallback.

Free-tier keys get a small daily request quota *per model*, and busy models answer
503. Each stage lists several models; a call moves to the next model when one is
overloaded or out of quota, and a model that reported its daily quota exhausted
is skipped for the rest of the process.
"""
from __future__ import annotations

import os
import threading
import time

_exhausted = set()
_lock = threading.Lock()
_client = None

DEFAULTS = {
    "vision": "gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemini-3-flash-preview,gemini-3.5-flash,gemini-flash-lite-latest",
    "planner": "gemini-3.5-flash,gemini-3-flash-preview,gemini-3.7-flash,gemini-3.8-flash,gemma-4-31b-it",
    "rerank": "gemini-3.8-flash,gemini-3.5-flash,gemini-3-flash-preview,gemini-3.7-flash,gemma-4-31b-it",
    "metadata": "gemini-3.7-flash,gemini-3.5-flash,gemini-3-flash-preview,gemini-3.8-flash,gemma-4-31b-it",
}
ENV = {
    "vision": "FOOTAGE_VISION_MODEL",
    "planner": "FOOTAGE_PLANNER_MODEL",
    "rerank": "FOOTAGE_RERANK_MODEL",
    "metadata": "FOOTAGE_METADATA_MODEL",
}


class QuotaExhausted(RuntimeError):
    pass


def api_key():
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def client():
    global _client
    from google import genai

    with _lock:
        if _client is None:
            key = api_key()
            if not key:
                raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY.")
            _client = genai.Client(api_key=key)
        return _client


def models_for(stage):
    raw = os.getenv(ENV[stage]) or DEFAULTS[stage]
    return [m.strip() for m in raw.split(",") if m.strip()]


def generate(stage, contents, attempts_per_model=2):
    """Return response text, trying each configured model for this stage in order."""
    last = None
    for model in models_for(stage):
        if model in _exhausted:
            continue
        for attempt in range(attempts_per_model):
            try:
                response = client().models.generate_content(model=model, contents=contents)
                return getattr(response, "text", "") or ""
            except Exception as exc:
                last = exc
                msg = str(exc).lower()
                print(f"[footage-analyzer] {stage} via {model} attempt {attempt + 1} failed: {str(exc)[:160]}", flush=True)
                if "resource_exhausted" in msg or "429" in msg:
                    if "perday" in msg or "per day" in msg:
                        _exhausted.add(model)
                        break
                    time.sleep(min(30.0, 5.0 * (attempt + 1)))
                    continue
                if any(x in msg for x in ("503", "unavailable", "500", "502", "overloaded", "timeout", "deadline",
                                          "getaddrinfo", "connection", "network", "temporarily", "reset by peer")):
                    time.sleep(3.0 * (attempt + 1))
                    continue
                if "not found" in msg or "404" in msg:
                    break
                raise
    if last and ("resource_exhausted" in str(last).lower() or "429" in str(last)):
        raise QuotaExhausted(f"Gemini quota exhausted for every {stage} model: {last}")
    raise last or RuntimeError(f"No Gemini model available for {stage}")
