"""Fila de geração em background (um vídeo por vez) com estado persistido em disco."""
from __future__ import annotations

import json
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app import settings
from app.models import VideoRequest


class Job(BaseModel):
    id: str
    created_at: str
    request: VideoRequest
    status: str = "queued"  # queued | running | done | error
    progress: float = 0
    step: str = "Na fila"
    log: List[str] = Field(default_factory=list)
    title: Optional[str] = None
    error: Optional[str] = None
    dir: str = ""
    youtube_id: Optional[str] = None
    upload_status: Optional[str] = None


class JobManager:
    def __init__(self) -> None:
        self.root = settings.path("output")
        self.jobs: Dict[str, Job] = {}
        self.lock = threading.Lock()
        self.render_pool = ThreadPoolExecutor(max_workers=1)
        self.upload_pool = ThreadPoolExecutor(max_workers=1)
        self._load()

    # ------------- persistência -------------

    def _load(self) -> None:
        for f in sorted(self.root.glob("*/job.json")):
            try:
                job = Job.model_validate_json(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if job.status in ("queued", "running"):
                job.status, job.error = "error", "Interrompido (servidor reiniciado)"
            self.jobs[job.id] = job

    def _save(self, job: Job) -> None:
        Path(job.dir, "job.json").write_text(job.model_dump_json(indent=2), encoding="utf-8")

    def _update(self, job: Job, **fields) -> None:
        with self.lock:
            for k, v in fields.items():
                setattr(job, k, v)
            self._save(job)

    # ------------- API -------------

    def list(self) -> List[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

    def get(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def submit(self, req: VideoRequest) -> Job:
        job_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        job_dir = self.root / job_id
        job_dir.mkdir(parents=True)
        job = Job(id=job_id, created_at=datetime.now().isoformat(timespec="seconds"), request=req, dir=str(job_dir))
        self.jobs[job_id] = job
        self._save(job)
        self.render_pool.submit(self._run, job)
        return job

    def _run(self, job: Job) -> None:
        from app.pipeline.runner import run_pipeline

        def progress(pct: float, step: str) -> None:
            with self.lock:
                job.progress = round(pct, 1)
                job.step = step
                job.log.append(f"[{datetime.now():%H:%M:%S}] {step}")
                self._save(job)

        self._update(job, status="running", step="Iniciando…")
        try:
            result = run_pipeline(job.request, Path(job.dir), progress)
            self._update(job, status="done", title=result["title"])
        except Exception as e:  # noqa: BLE001 — erro exibido na interface
            traceback.print_exc()
            self._update(job, status="error", error=str(e), step="Falhou")

    def upload_youtube(self, job: Job, privacy: str) -> None:
        from app.publish import youtube

        def run() -> None:
            try:
                self._update(job, upload_status="Enviando 0%")
                vid = youtube.upload(Path(job.dir), privacy, job.request.language,
                                     progress=lambda p: self._update(job, upload_status=f"Enviando {p}%"))
                self._update(job, youtube_id=vid, upload_status="Publicado")
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self._update(job, upload_status=f"Erro: {e}")

        self.upload_pool.submit(run)


def read_metadata(job: Job) -> dict:
    f = Path(job.dir) / "metadata.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
