"""Autentica o YouTube uma vez e salva credentials/token.json.

    python -m scripts.authenticate_youtube
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.publish import youtube  # noqa: E402

if __name__ == "__main__":
    if not youtube.is_configured():
        print("❌ credentials/youtube_credentials.json não encontrado.\n")
        print("1. https://console.cloud.google.com → crie um projeto")
        print("2. Habilite a YouTube Data API v3")
        print("3. Crie credenciais OAuth 2.0 do tipo 'App para computador'")
        print("4. Baixe o JSON e salve em credentials/youtube_credentials.json")
        sys.exit(1)
    youtube.get_service()
    print("✅ Autenticado. Token salvo em credentials/token.json")
