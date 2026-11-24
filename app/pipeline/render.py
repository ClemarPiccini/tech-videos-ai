"""Montagem do vídeo com ffmpeg: clipes normalizados -> timeline -> mix de áudio + legendas."""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from app import settings
from app.pipeline import ffmpeg
from app.pipeline.visuals import Visual


@dataclass
class Segment:
    visual: Visual
    frames: int


class Renderer:
    def __init__(self, size: Tuple[int, int]) -> None:
        cfg = settings.config()["video"]
        self.width, self.height = size
        self.fps = int(cfg["fps"])
        self.crf = str(cfg["crf"])
        self.preset = cfg["preset"]
        g = cfg["grade"]
        grade = (f"eq=brightness={g['brightness']}:contrast={g['contrast']}:saturation={g['saturation']}"
                 f":gamma={g.get('gamma', 1.0)}")
        self.look = grade + (",vignette=PI/5" if cfg.get("vignette", True) else "")

    # ---------------- clipes ----------------

    def render_segment(self, seg: Segment, out: Path, index: int) -> Path:
        W, H, fps = self.width, self.height, self.fps
        seconds = seg.frames / fps
        common = ["-an", "-r", str(fps), "-frames:v", str(seg.frames), "-c:v", "libx264", "-preset", "veryfast",
                  "-crf", "18", "-pix_fmt", "yuv420p", out]
        if seg.visual.kind == "video":
            src_dur = seg.visual.duration or ffmpeg.duration(seg.visual.path)
            spare = src_dur - seconds
            # Começa em um ponto aleatório quando o clipe é mais longo que o necessário
            start = random.Random(index).uniform(0, spare * 0.6) if spare > 1 else 0
            loop = ["-stream_loop", "-1"] if spare < 0 else []
            vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                  f"fps={fps},{self.look},format=yuv420p")
            ffmpeg.run([*loop, "-ss", f"{start:.2f}", "-i", seg.visual.path, "-vf", vf, *common])
        else:
            # Ken Burns: zoom lento alternando o sentido entre cenas
            zoom_in = index % 2 == 0
            z = "min(zoom+0.0006,1.18)" if zoom_in else "if(eq(on,0),1.18,max(zoom-0.0006,1.0))"
            vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
                  f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={seg.frames}:s={W}x{H}:fps={fps},"
                  f"{self.look},format=yuv420p")
            ffmpeg.run(["-loop", "1", "-t", f"{seconds + 1:.2f}", "-i", seg.visual.path, "-vf", vf, *common])
        return out

    def concat_video(self, clips: List[Path], out: Path) -> Path:
        lst = ffmpeg.concat_list(clips, out.with_suffix(".txt"))
        ffmpeg.run(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])
        return out

    @staticmethod
    def concat_audio(wavs: List[Path], out: Path) -> Path:
        lst = ffmpeg.concat_list(wavs, out.with_suffix(".txt"))
        ffmpeg.run(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])
        return out

    # ---------------- final ----------------

    def final_mix(
        self,
        video: Path,
        narration: Path,
        total: float,
        out: Path,
        music: Optional[Path] = None,
        captions_list: Optional[Path] = None,
    ) -> Path:
        acfg = settings.config()["audio"]
        inputs: List[str] = ["-i", str(video), "-i", str(narration)]
        filters: List[str] = []
        idx = 2

        fade_out = max(0.0, total - 0.8)
        vchain = f"[0:v]fade=t=in:st=0:d=0.6,fade=t=out:st={fade_out:.2f}:d=0.8"
        if captions_list:
            inputs += ["-f", "concat", "-safe", "0", "-i", str(captions_list)]
            filters.append(f"[{idx}:v]format=rgba,fps={self.fps}[cap]")
            filters.append(f"{vchain}[base]")
            filters.append("[base][cap]overlay=0:0:format=auto:shortest=0,format=yuv420p[v]")
            idx += 1
        else:
            filters.append(f"{vchain},format=yuv420p[v]")

        lufs = acfg.get("loudness_lufs", -14)
        if music:
            inputs += ["-stream_loop", "-1", "-i", str(music)]
            vol = acfg.get("music_volume", 0.14)
            filters.append(
                f"[{idx}:a]aresample=44100,aformat=channel_layouts=stereo,volume={vol},"
                f"afade=t=in:st=0:d=1.5,afade=t=out:st={max(0.0, total - 3):.2f}:d=3[m]"
            )
            filters.append("[1:a]aresample=44100,aformat=channel_layouts=stereo,asplit=2[n1][n2]")
            if acfg.get("ducking", True):
                filters.append("[m][n2]sidechaincompress=threshold=0.04:ratio=6:attack=30:release=500[md]")
            else:
                filters.append("[m]anull[md];[n2]anullsink")
            filters.append(f"[n1][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I={lufs}:TP=-1.5:LRA=11[a]")
        else:
            filters.append(f"[1:a]aresample=44100,aformat=channel_layouts=stereo,loudnorm=I={lufs}:TP=-1.5:LRA=11[a]")

        ffmpeg.run([
            *inputs,
            "-filter_complex", ";".join(filters),
            "-map", "[v]", "-map", "[a]",
            "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", self.preset, "-crf", self.crf, "-pix_fmt", "yuv420p",
            "-r", str(self.fps),
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
            "-movflags", "+faststart",
            out,
        ])
        return out


def plan_segments(scene_durations: List[float], queries_per_scene: List[int], fps: int, min_clip: float,
                  target_clip: Optional[float] = None) -> List[List[int]]:
    """Divide a timeline em segmentos (em frames) sem acumular erro de arredondamento.

    Um clipe por busca da cena; com target_clip, cenas longas ganham mais cortes (as buscas se repetem
    e cada repetição traz um clipe diferente). Retorna, por cena, os frames de cada clipe.
    """
    plan: List[List[int]] = []
    t = 0.0
    for dur, nq in zip(scene_durations, queries_per_scene):
        wanted = max(nq, round(dur / target_clip)) if target_clip else nq
        n = max(1, min(wanted, int(dur // min_clip) or 1))
        frames = []
        for i in range(n):
            a = round((t + dur * i / n) * fps)
            b = round((t + dur * (i + 1) / n) * fps)
            frames.append(max(1, b - a))
        plan.append(frames)
        t += dur
    return plan
