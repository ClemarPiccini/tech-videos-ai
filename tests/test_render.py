"""Renderização ponta a ponta com ffmpeg, sem nenhuma API externa."""
from pathlib import Path

import pytest

from app.models import Word
from app.pipeline import ffmpeg
from app.pipeline.captions import CaptionRenderer
from app.pipeline.render import Renderer, Segment, plan_segments
from app.pipeline.thumbnail import make_thumbnail
from app.pipeline.visuals import Visual, VisualFinder

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg não instalado")

SIZE = (360, 640)  # vertical pequeno para o teste ser rápido


def _tone(path: Path, seconds: float, freq: int) -> Path:
    ffmpeg.run(["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", "-ar", "44100", "-ac", "1", path])
    return path


def _clip(path: Path, seconds: float) -> Path:
    ffmpeg.run(["-f", "lavfi", "-i", f"testsrc=size=640x360:rate=25:duration={seconds}", "-pix_fmt", "yuv420p", path])
    return path


def test_full_render(tmp_path, monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "")
    monkeypatch.setenv("PIXABAY_API_KEY", "")
    monkeypatch.setattr(VisualFinder, "_openverse_photo", lambda self, q: None)  # sem rede no teste
    renderer = Renderer(SIZE)

    wavs = [_tone(tmp_path / "a0.wav", 2.6, 220), _tone(tmp_path / "a1.wav", 3.4, 330)]
    durations = [ffmpeg.duration(w) for w in wavs]
    total = sum(durations)
    narration = Renderer.concat_audio(wavs, tmp_path / "narration.wav")

    finder = VisualFinder("vertical", SIZE)
    stock = Visual(path=_clip(tmp_path / "stock.mp4", 1.5), kind="video", duration=1.5)  # força loop
    placeholder = finder.find("anything", 2.0)  # sem fontes -> fundo gerado (imagem/Ken Burns)
    assert placeholder.provider == "gerado"
    visuals = [stock, placeholder]

    plan = plan_segments(durations, [1, 2], renderer.fps, min_clip=1.0)
    clips, n = [], 0
    for frames_list in plan:
        for frames in frames_list:
            clips.append(renderer.render_segment(Segment(visuals[n % 2], frames), tmp_path / f"c{n}.mp4", n))
            n += 1
    visual = renderer.concat_video(clips, tmp_path / "visual.mp4")
    assert abs(ffmpeg.duration(visual) - total) < 0.1

    words = [Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4) for i, t in enumerate("isso nunca deveria ter acontecido".split())]
    captions = CaptionRenderer(SIZE, vertical=True).build_track(words, total, tmp_path / "caps")

    music = _tone(tmp_path / "music.wav", 1.0, 440)  # mais curta que o vídeo -> loop
    out = renderer.final_mix(visual, narration, total, tmp_path / "video.mp4", music, captions)
    assert out.exists()
    assert abs(ffmpeg.duration(out) - total) < 0.15

    thumb = make_thumbnail(visual, "NÃO ABRA ESSA PORTA", tmp_path / "thumbnail.jpg", vertical=True, at=1.0)
    assert thumb.exists() and thumb.stat().st_size > 10_000
