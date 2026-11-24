"""Orquestra o pipeline completo: roteiro -> narração -> visuais -> montagem -> thumbnail -> metadados."""
from __future__ import annotations

import json
import random
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Callable, Dict, List, Optional

from app import settings
from app.models import VideoRequest, VideoScript, Word
from app.pipeline import ffmpeg
from app.pipeline.captions import CaptionRenderer
from app.pipeline.render import Renderer, Segment, plan_segments
from app.pipeline.script import ScriptGenerator, provider_label
from app.pipeline.thumbnail import make_thumbnail
from app.pipeline.tts import TTS, speed_up
from app.pipeline.visuals import VisualFinder, concrete_query, credits_text

Progress = Callable[[float, str], None]


def slugify(text: str, max_len: int = 50) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].strip("-") or "video"


def pick_music() -> Optional[Path]:
    tracks = [p for p in settings.path("music").iterdir() if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"}]
    return random.choice(tracks) if tracks else None


def post_text(script: VideoScript, platform: str = "youtube") -> str:
    """Texto pronto para colar. Instagram/TikTok não têm campo de título: a legenda é a descrição."""
    parts = [script.description, " ".join(script.hashtags)]
    if platform in ("youtube", "shorts"):
        parts.insert(0, script.title)
    return "\n\n".join(p for p in parts if p).strip() + "\n"


def run_pipeline(req: VideoRequest, job_dir: Path, progress: Progress) -> Dict[str, str]:
    if not ffmpeg.available():
        raise RuntimeError("ffmpeg/ffprobe não encontrados no PATH.")

    presets = settings.presets()
    cfg = settings.config()
    platform = presets["platforms"][req.platform]
    vertical = platform["orientation"] == "vertical"
    size = tuple(cfg["formats"]["vertical" if vertical else "landscape"])
    work = job_dir / "work"
    work.mkdir(parents=True, exist_ok=True)

    # 1. Roteiro
    progress(2, f"Escrevendo o roteiro com {provider_label()}…")
    script = ScriptGenerator(log=lambda msg: progress(5, msg)).generate(req)
    (job_dir / "script.json").write_text(script.model_dump_json(indent=2), encoding="utf-8")
    progress(15, f"Roteiro pronto: “{script.title}” ({len(script.scenes)} cenas)")

    # 2. Narração
    tts = TTS(req.voice_engine, req.language, req.voice)
    audios = []
    for i, scene in enumerate(script.scenes):
        progress(15 + 20 * i / len(script.scenes), f"Narrando cena {i + 1}/{len(script.scenes)}…")
        audios.append(tts.synthesize(scene.narration, work, i))
    total = sum(a.duration for a in audios)

    # Garantia de duração: se a narração passou do tempo pedido, acelera levemente o áudio
    ncfg = cfg["narration"]
    limit = req.duration_seconds * (1 + float(ncfg.get("duration_tolerance", 0.05)))
    if total > limit:
        factor = min(total / req.duration_seconds, float(ncfg.get("max_speedup", 1.2)))
        progress(34, f"Narração com {total:.0f}s para {req.duration_seconds}s pedidos: acelerando {factor:.2f}×…")
        audios = [speed_up(a, factor, work) for a in audios]
        total = sum(a.duration for a in audios)
    durations = [a.duration for a in audios]
    narration = Renderer.concat_audio([Path(a.path) for a in audios], work / "narration.wav")
    progress(35, f"Narração pronta ({total:.0f}s de {req.duration_seconds}s pedidos)")

    # 3. Visuais
    finder = VisualFinder(platform["orientation"], size)
    progress(35, f"Fontes de mídia: {', '.join(finder.providers)}")
    renderer = Renderer(size)
    clip_target = cfg["video"].get("clip_seconds", {}).get("vertical" if vertical else "landscape")
    plan = plan_segments(durations, [len(s.visual_queries) for s in script.scenes], renderer.fps,
                         float(cfg["video"].get("min_clip_seconds", 2.5)),
                         float(clip_target) if clip_target else None)
    niche_style = presets["niches"].get(req.niche, {}).get("visual_style", "")
    fallback_query = next((s.strip() for s in niche_style.split(",") if concrete_query(s)), "")
    clips: List[Path] = []
    n_segments = sum(len(p) for p in plan)
    done = 0
    for si, (scene, frames_list) in enumerate(zip(script.scenes, plan)):
        for qi, frames in enumerate(frames_list):
            query = scene.visual_queries[qi % len(scene.visual_queries)]
            progress(35 + 40 * done / n_segments, f"Cena {si + 1}: buscando e tratando “{query}”…")
            visual = finder.find(query, frames / renderer.fps, script.visual_subject, fallback_query)
            clips.append(renderer.render_segment(Segment(visual, frames), work / f"clip_{done:04d}.mp4", done))
            done += 1
    visual_track = renderer.concat_video(clips, work / "visual.mp4")

    # 4. Legendas
    captions_list = None
    if req.captions:
        progress(77, "Gerando legendas animadas…")
        words: List[Word] = []
        offset = 0.0
        for a in audios:
            words += [Word(text=w.text, start=w.start + offset, end=w.end + offset) for w in a.words]
            offset += a.duration
        captions_list = CaptionRenderer(size, vertical).build_track(words, total, work / "captions")

    # 5. Mix final
    progress(82, "Renderizando vídeo final (pode levar alguns minutos)…")
    music = pick_music() if req.music else None
    video = renderer.final_mix(visual_track, narration, total, job_dir / "video.mp4", music, captions_list)

    # 6. Thumbnail + metadados
    progress(95, "Criando thumbnail e textos de publicação…")
    thumb = make_thumbnail(visual_track, script.thumbnail_text, job_dir / "thumbnail.jpg", vertical,
                           at=min(1.5, total / 2))
    metadata = {
        "title": script.title,
        "description": script.description,
        "tags": script.tags,
        "hashtags": script.hashtags,
        "platform": req.platform,
        "duration": round(total, 1),
        "music": music.name if music else None,
        "media_sources": sorted({v.provider for v in finder.credits}),
    }
    (job_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (job_dir / "post.txt").write_text(post_text(script, req.platform), encoding="utf-8")
    (job_dir / "credits.txt").write_text(credits_text(finder.credits) + "\n", encoding="utf-8")

    shutil.rmtree(work, ignore_errors=True)
    progress(100, "Vídeo pronto!")
    return {"video": str(video), "thumbnail": str(thumb), "title": script.title}
