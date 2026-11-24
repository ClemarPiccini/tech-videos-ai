"""Linha de comando.

    python -m app.cli serve                 # abre a interface web em http://localhost:8000
    python -m app.cli generate --prompt "..." --platform shorts --duration 60
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def serve(args: argparse.Namespace) -> None:
    import uvicorn

    print(f"\n  Dark Video Studio → http://{args.host}:{args.port}\n")
    uvicorn.run("app.server:app", host=args.host, port=args.port, reload=False)


def generate(args: argparse.Namespace) -> None:
    from app import settings
    from app.jobs import JobManager
    from app.models import VideoRequest

    req = VideoRequest(
        prompt=args.prompt or "",
        niche=args.niche,
        platform=args.platform,
        duration_seconds=args.duration or settings.presets()["platforms"][args.platform]["default_duration"],
        language=args.language,
        voice_engine=args.voice_engine,
        captions=not args.no_captions,
        music=not args.no_music,
    )
    mgr = JobManager()
    job = mgr.submit(req)
    mgr.render_pool.shutdown(wait=True)
    if job.status != "done":
        print(f"\n❌ {job.error}", file=sys.stderr)
        sys.exit(1)
    print(f"\n✅ {job.title}\n   {Path(job.dir) / 'video.mp4'}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="dark-video-studio")
    sub = parser.add_subparsers(dest="cmd")

    s = sub.add_parser("serve", help="Abre a interface web")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(func=serve)

    g = sub.add_parser("generate", help="Gera um vídeo direto pelo terminal")
    g.add_argument("--prompt", default="")
    g.add_argument("--niche", default="misterios")
    g.add_argument("--platform", default="reels", choices=["youtube", "shorts", "tiktok", "reels"])
    g.add_argument("--duration", type=int)
    g.add_argument("--language", default="pt", choices=["pt", "es", "en"])
    g.add_argument("--voice-engine", default="edge", choices=["edge", "elevenlabs"])
    g.add_argument("--no-captions", action="store_true")
    g.add_argument("--no-music", action="store_true")
    g.set_defaults(func=generate)

    args = parser.parse_args()
    if not args.cmd:
        args = parser.parse_args(["serve"])
    args.func(args)


if __name__ == "__main__":
    main()
