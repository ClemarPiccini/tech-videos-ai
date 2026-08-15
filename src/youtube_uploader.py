import os
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

class YouTubeUploader:
    def __init__(self, config):
        self.config = config
        self.credentials_path = Path("credentials/youtube_credentials.json")
        self.token_path = Path("credentials/token.json")
        self.youtube = self._authenticate()
    
    def _authenticate(self):
        SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
        
        creds = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)
            
            # Salva credenciais
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())
        
        return build('youtube', 'v3', credentials=creds)
    
    def fazer_upload(self, video_path, titulo, descricao, tags, idioma):
        # Prepara metadata
        body = {
            'snippet': {
                'title': titulo,
                'description': descricao,
                'tags': tags,
                'categoryId': self.config['upload']['category_id'],
                'defaultLanguage': idioma,
                'defaultAudioLanguage': idioma
            },
            'status': {
                'privacyStatus': self.config['upload']['default_privacy'],
                'selfDeclaredMadeForKids': False
            }
        }
        
        # Upload
        media = MediaFileUpload(
            video_path,
            chunksize=-1,
            resumable=True,
            mimetype='video/mp4'
        )
        
        request = self.youtube.videos().insert(
            part='snippet,status',
            body=body,
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                print(f"Upload {progress}% completo")
        
        video_id = response['id']
        return video_id