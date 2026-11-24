"""Wrappers finos sobre ffmpeg/ffprobe."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Sequence, Union

PathLike = Union[str, Path]


class FFmpegError(RuntimeError):
    pass


def available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def run(args: Sequence[str]) -> None:
    cmd: List[str] = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise FFmpegError(f"ffmpeg falhou ({proc.returncode}):\n{tail}")


def duration(path: PathLike) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe falhou em {path}: {proc.stderr.strip()}")
    return float(json.loads(proc.stdout)["format"]["duration"])


def concat_list(paths: Sequence[PathLike], list_file: Path) -> Path:
    lines = [f"file '{Path(p).resolve().as_posix()}'" for p in paths]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return list_file
