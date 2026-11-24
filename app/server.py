"""Servidor web local: interface + API de geração."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing_extensions import Literal

from app import settings
from app.jobs import JobManager, read_metadata
from app.models import Brief, VideoRequest
from app.pipeline import ffmpeg, ollama, script
from app.pipeline.brief import min_words, parse_brief, recommended_seconds
from app.publish import youtube

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Dark Video Studio")
manager = JobManager()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/api/presets")
def get_presets() -> dict:
    return settings.presets()


@app.get("/api/health")
def health() -> dict:
    models = ollama.list_models()
    provider = script.resolve_provider()
    llm_ready = bool(settings.env("ANTHROPIC_API_KEY")) if provider == "anthropic" else (
        models is not None and ollama.has_model(models, ollama.current_model())
    )
    return {
        "ffmpeg": ffmpeg.available(),
        "anthropic": bool(settings.env("ANTHROPIC_API_KEY")),
        "pexels": bool(settings.env("PEXELS_API_KEY")),
        "pixabay": bool(settings.env("PIXABAY_API_KEY")),
        "elevenlabs": bool(settings.env("ELEVENLABS_API_KEY")),
        "youtube": youtube.is_configured(),
        "llm": script.provider_label(),
        "llm_ready": llm_ready,
    }


# ---------------- configurações ----------------

SECRET_KEYS = ["ANTHROPIC_API_KEY", "PIXABAY_API_KEY", "PEXELS_API_KEY", "ELEVENLABS_API_KEY"]


def _mask(value: str) -> str:
    return f"••••{value[-4:]}" if len(value) > 8 else ("••••" if value else "")


@app.get("/api/settings")
def get_settings() -> dict:
    models = ollama.list_models()
    return {
        "llm_provider": script.configured_provider(),
        "llm_effective": script.resolve_provider(),
        "ollama_model": ollama.current_model(),
        "ollama_running": models is not None,
        "ollama_models": models or [],
        "recommended_models": RECOMMENDED_MODELS,
        "keys": {k: _mask(settings.env(k)) for k in SECRET_KEYS},
    }


RECOMMENDED_MODELS = [
    {"id": "qwen2.5:7b", "label": "Qwen 2.5 7B — rápido, ~4.7 GB (recomendado)"},
    {"id": "qwen2.5:14b", "label": "Qwen 2.5 14B — melhor texto, ~9 GB (16 GB+ de RAM)"},
    {"id": "llama3.1:8b", "label": "Llama 3.1 8B — ~4.9 GB"},
    {"id": "gemma2:9b", "label": "Gemma 2 9B — ~5.4 GB"},
]


class SettingsBody(BaseModel):
    llm_provider: Optional[Literal["auto", "anthropic", "ollama"]] = None
    ollama_model: Optional[str] = None
    keys: Dict[str, str] = {}
    clear_keys: List[str] = []


@app.post("/api/settings")
def save_settings(body: SettingsBody) -> dict:
    updates: Dict[str, str] = {}
    if body.llm_provider:
        updates["LLM_PROVIDER"] = body.llm_provider
    if body.ollama_model and body.ollama_model.strip():
        updates["OLLAMA_MODEL"] = body.ollama_model.strip()
    for k, v in body.keys.items():
        if k not in SECRET_KEYS:
            raise HTTPException(400, f"Chave desconhecida: {k}")
        if v.strip():
            updates[k] = v.strip()
    for k in body.clear_keys:
        if k in SECRET_KEYS:
            updates[k] = ""
    if updates:
        settings.set_env(updates)
    return get_settings()


class BriefBody(BaseModel):
    text: str = ""
    brief: Optional[Brief] = None


@app.post("/api/brief")
def analyze_brief(body: BriefBody) -> dict:
    """Lê um briefing colado (ou valida o preenchido) e recomenda a duração mínima."""
    brief = body.brief if body.brief and not body.brief.is_empty() else parse_brief(body.text)
    if not brief:
        return {"brief": None, "recommended_seconds": None}
    return {"brief": brief.model_dump(), "recommended_seconds": recommended_seconds(brief),
            "words": min_words(brief)}


class PullBody(BaseModel):
    model: str


@app.post("/api/ollama/pull")
def pull_model(body: PullBody) -> dict:
    if ollama.list_models() is None:
        raise HTTPException(400, "O Ollama não está rodando. Instale/abra em ollama.com/download.")
    if not ollama.pull_tracker.start(body.model.strip()):
        raise HTTPException(409, "Já existe um download em andamento.")
    return ollama.pull_tracker.snapshot()


@app.get("/api/ollama/pull")
def pull_status() -> dict:
    return ollama.pull_tracker.snapshot()


def _job_out(job) -> dict:
    data = job.model_dump()
    data["metadata"] = read_metadata(job) if job.status == "done" else {}
    return data


def _job_or_404(job_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado")
    return job


@app.post("/api/jobs")
def create_job(req: VideoRequest) -> dict:
    platform = settings.presets()["platforms"].get(req.platform, {})
    max_d = platform.get("max_duration")
    if max_d and req.duration_seconds > max_d:
        raise HTTPException(400, f"{platform['label']} aceita no máximo {max_d}s.")
    if req.voice_engine == "elevenlabs" and not settings.env("ELEVENLABS_API_KEY"):
        raise HTTPException(400, "ELEVENLABS_API_KEY não configurada.")
    if script.resolve_provider() == "ollama":
        models = ollama.list_models()
        if models is None:
            raise HTTPException(400, "Nenhuma IA disponível: instale/abra o Ollama (ollama.com/download) "
                                     "ou cole sua chave da Anthropic em Configurações.")
        if not ollama.has_model(models, ollama.current_model()):
            raise HTTPException(400, f"Baixe o modelo '{ollama.current_model()}' em Configurações.")
    return _job_out(manager.submit(req))


@app.get("/api/jobs")
def list_jobs() -> list:
    return [_job_out(j) for j in manager.list()]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return _job_out(_job_or_404(job_id))


@app.get("/api/jobs/{job_id}/{kind}")
def job_file(job_id: str, kind: Literal["video", "thumbnail", "post", "script"], download: bool = False) -> FileResponse:
    job = _job_or_404(job_id)
    name = {"video": "video.mp4", "thumbnail": "thumbnail.jpg", "post": "post.txt", "script": "script.json"}[kind]
    f = Path(job.dir) / name
    if not f.exists():
        raise HTTPException(404, "Arquivo ainda não existe")
    filename = f"{job.id}-{name}" if download else None
    return FileResponse(f, filename=filename)


class UploadBody(BaseModel):
    privacy: Literal["private", "unlisted", "public"] = "private"


@app.post("/api/jobs/{job_id}/youtube")
def upload_job(job_id: str, body: UploadBody) -> dict:
    job = _job_or_404(job_id)
    if job.status != "done":
        raise HTTPException(400, "O vídeo ainda não está pronto.")
    if not youtube.is_configured():
        raise HTTPException(400, "Coloque o OAuth do Google em credentials/youtube_credentials.json")
    manager.upload_youtube(job, body.privacy)
    return {"ok": True}
