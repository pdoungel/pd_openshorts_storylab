"""Script-to-voiceover synthesis with Gemini TTS."""
from __future__ import annotations

import os
import re
import time
import wave
from pathlib import Path

SAMPLE_RATE = 24000
MAX_CHARS = 3500


def _chunks(script):
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", script) if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        pieces = [para] if len(para) <= MAX_CHARS else re.split(r"(?<=[.!?])\s+", para)
        for piece in pieces:
            if current and len(current) + len(piece) + 2 > MAX_CHARS:
                chunks.append(current)
                current = ""
            current = f"{current}\n\n{piece}".strip() if current else piece
    if current:
        chunks.append(current)
    return chunks


def _synthesize_chunk(client, types, text, voice, style):
    # A style instruction is spoken aloud by some TTS models, so it is opt-in.
    prompt = f"{style.strip()}:\n\n{text}" if style.strip() else text
    last = None
    for attempt in range(4):
        try:
            response = client.models.generate_content(
                model=os.getenv("FOOTAGE_TTS_MODEL", "gemini-3.8-flash-tts"),
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                        )
                    ),
                ),
            )
            data = response.candidates[0].content.parts[0].inline_data.data
            if not data:
                raise RuntimeError("Gemini TTS returned no audio")
            return data
        except Exception as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Gemini TTS failed: {last}")


def synthesize(script, out_path, progress=None):
    from google import genai
    from google.genai import types

    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("Script input needs GEMINI_API_KEY to generate the voiceover.")
    chunks = _chunks(script)
    if not chunks:
        raise RuntimeError("The script is empty.")

    client = genai.Client(api_key=key)
    voice = os.getenv("FOOTAGE_TTS_VOICE", "Charon")
    style = os.getenv("FOOTAGE_TTS_STYLE", "")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        for i, chunk in enumerate(chunks, 1):
            if progress:
                progress(i - 1, len(chunks))
            wav.writeframes(_synthesize_chunk(client, types, chunk, voice, style))
            wav.writeframes(b"\x00\x00" * int(SAMPLE_RATE * 0.35))
    if progress:
        progress(len(chunks), len(chunks))
    return str(out)
