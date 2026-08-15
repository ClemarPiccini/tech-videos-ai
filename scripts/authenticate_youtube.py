from google_auth_oauthlib.flow import InstalledAppFlow
from pathlib import Path

def authenticate():
    print("🔐 Autenticação YouTube API\\n")
    
    credentials_path = Path("credentials/youtube_credentials.json")
    
    if not credentials_path.exists():
        print("❌ Erro: credentials/youtube_credentials.json não encontrado!")
        print("\\n📖 Como obter:")
        print("1. Acesse: https://console.cloud.google.com")
        print("2. Crie um projeto")
        print("3. Habilite YouTube Data API v3")
        print("4. Crie credenciais OAuth 2.0")
        print("5. Baixe o JSON e salve em credentials/youtube_credentials.json")
        return
    
    SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
    
    flow = InstalledAppFlow.from_client_secrets_file(
        str(credentials_path),
        SCOPES
    )
    
    creds = flow.run_local_server(port=0)
    
    # Salva token
    token_path = Path("credentials/token.json")
    with open(token_path, 'w') as token:
        token.write(creds.to_json())
    
    print("\\n✅ Autenticação concluída!")
    print(f"Token salvo em: {token_path}")

if __name__ == "__main__":
    authenticate()