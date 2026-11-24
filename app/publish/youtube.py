"""Upload para o YouTube (OAuth local). Requer credentials/youtube_credentials.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from app import settings

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _paths():
    base = settings.BASE_DIR / "credentials"
    return base / "youtube_credentials.json", base / "token.json"


def is_configured() -> bool:
    secrets, _ = _paths()
    return secrets.exists()


def get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    secrets, token = _paths()
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not secrets.exists():
            raise RuntimeError(f"Arquivo OAuth não encontrado: {secrets}")
        creds = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES).run_local_server(port=0)
    token.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def upload(job_dir: Path, privacy: str = "private", language: str = "pt",
           progress: Optional[Callable[[int], None]] = None) -> str:
    from googleapiclient.http import MediaFileUpload

    meta = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
    cfg = settings.config()["youtube"]
    description = meta["description"] + "\n\n" + " ".join(meta.get("hashtags", []))
    body = {
        "snippet": {
            "title": meta["title"][:100],
            "description": description[:5000],
            "tags": meta.get("tags", []),
            "categoryId": cfg.get("category_id", "27"),
            "defaultLanguage": language,
            "defaultAudioLanguage": language,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            # Política do YouTube: conteúdo realista gerado/alterado por IA deve ser declarado
            "containsSyntheticMedia": True,
        },
    }
    yt = get_service()
    media = MediaFileUpload(str(job_dir / "video.mp4"), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and progress:
            progress(int(status.progress() * 100))
    video_id = response["id"]

    thumb = job_dir / "thumbnail.jpg"
    if thumb.exists() and meta.get("platform") == "youtube":
        try:
            yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumb))).execute()
        except Exception:  # canais não verificados não podem enviar thumbnail personalizada
            pass
    return video_id
