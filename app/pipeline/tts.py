"""Narração: Edge TTS (gratuito) ou ElevenLabs, ambos com tempo por palavra para as legendas."""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import List, Optional, Tuple

from app import settings
from app.models import SceneAudio, Word
from app.pipeline import ffmpeg

TICKS_PER_SECOND = 10_000_000  # edge-tts reporta offset/duração em unidades de 100 ns


def default_voice(engine: str, language: str) -> str:
    voices = settings.presets()["voices"][engine].get(language) or []
    if not voices:
        raise RuntimeError(f"Nenhuma voz {engine} configurada para '{language}' em presets.yaml")
    return voices[0]["id"]


class TTS:
    def __init__(self, engine: str, language: str, voice: Optional[str] = None) -> None:
        self.engine = engine
        self.voice = voice or default_voice(engine, language)
        cfg = settings.config()["narration"]
        self.pause = float(cfg.get("pause_between_scenes", 0.25))
        self.edge_rate = cfg.get("edge_rate", "+0%")
        self._eleven = None
        if engine == "elevenlabs":
            key = settings.env("ELEVENLABS_API_KEY")
            if not key:
                raise RuntimeError("ELEVENLABS_API_KEY não configurada no .env")
            from elevenlabs.client import ElevenLabs

            self._eleven = ElevenLabs(api_key=key)

    def synthesize(self, text: str, out_dir: Path, index: int) -> SceneAudio:
        raw = out_dir / f"scene_{index:03d}.mp3"
        if self.engine == "elevenlabs":
            words = self._elevenlabs(text, raw)
        else:
            words = asyncio.run(self._edge(text, raw))

        # WAV com pausa no final: concatenação exata e duração confiável.
        wav = out_dir / f"scene_{index:03d}.wav"
        ffmpeg.run(["-i", raw, "-af", f"apad=pad_dur={self.pause}", "-ar", "44100", "-ac", "1", wav])
        return SceneAudio(path=str(wav), duration=ffmpeg.duration(wav), words=words)

    async def _edge(self, text: str, out: Path) -> List[Word]:
        import edge_tts

        communicate = edge_tts.Communicate(text, self.voice, rate=self.edge_rate, boundary="WordBoundary")
        words: List[Word] = []
        with open(out, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / TICKS_PER_SECOND
                    words.append(Word(text=chunk["text"], start=start, end=start + chunk["duration"] / TICKS_PER_SECOND))
        if not words:
            words = estimate_words(text, ffmpeg.duration(out))
        return words

    def _elevenlabs(self, text: str, out: Path) -> List[Word]:
        res = self._eleven.text_to_speech.convert_with_timestamps(
            self.voice,
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )
        out.write_bytes(base64.b64decode(res.audio_base_64))
        al = res.alignment
        if al is None:
            return estimate_words(text, ffmpeg.duration(out))
        return words_from_chars(al.characters, al.character_start_times_seconds, al.character_end_times_seconds)


def speed_up(audio: SceneAudio, factor: float, out_dir: Path) -> SceneAudio:
    """Acelera a narração sem mudar o tom (atempo) e reescala o tempo das palavras."""
    if factor <= 1.001:
        return audio
    src = Path(audio.path)
    out = out_dir / f"{src.stem}_x{factor:.2f}.wav"
    ffmpeg.run(["-i", src, "-filter:a", f"atempo={factor:.4f}", "-ar", "44100", "-ac", "1", out])
    words = [Word(text=w.text, start=w.start / factor, end=w.end / factor) for w in audio.words]
    return SceneAudio(path=str(out), duration=ffmpeg.duration(out), words=words)


def words_from_chars(chars: List[str], starts: List[float], ends: List[float]) -> List[Word]:
    words: List[Word] = []
    current: List[Tuple[str, float, float]] = []

    def flush() -> None:
        if current:
            words.append(Word(text="".join(c for c, _, _ in current), start=current[0][1], end=current[-1][2]))
            current.clear()

    for c, s, e in zip(chars, starts, ends):
        if c.isspace():
            flush()
        else:
            current.append((c, s, e))
    flush()
    return words


def estimate_words(text: str, total: float) -> List[Word]:
    """Distribui as palavras proporcionalmente ao número de letras (fallback sem alinhamento)."""
    tokens = text.split()
    if not tokens:
        return []
    weights = [len(t) + 1 for t in tokens]
    scale = total / sum(weights)
    t, words = 0.0, []
    for tok, w in zip(tokens, weights):
        words.append(Word(text=tok, start=t, end=t + w * scale))
        t += w * scale
    return words
