import os
from pathlib import Path
from datetime import datetime
import json

from script_generator import ScriptGenerator
from audio_generator import AudioGenerator
from image_processor import ImageProcessor
from video_editor import VideoEditor
from youtube_uploader import YouTubeUploader
from utils import log_info, log_success, log_error

class TechVideoGenerator:
    def __init__(self, config):
        self.config = config
        self.output_dir = Path("output")
        self.output_dir.mkdir(exist_ok=True)
        
        # Inicializa componentes
        self.script_gen = ScriptGenerator(config)
        self.audio_gen = AudioGenerator(config)
        self.image_proc = ImageProcessor(config)
        self.video_editor = VideoEditor(config)
        self.youtube = None
        
        # Histórico
        self.history_file = Path("data/videos_publicados.json")
        self._load_history()
    
    def _load_history(self):
        if self.history_file.exists():
            with open(self.history_file, 'r', encoding='utf-8') as f:
                self.history = json.load(f)
        else:
            self.history = []
    
    def _save_history(self, video_data):
        self.history.append(video_data)
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, indent=2, ensure_ascii=False)
    


    def gerar_video_completo(
        self,
        tema=None,
        idioma='pt',
        modo='short',
        duracao=None,
        fazer_upload=False
    ):

        try:
            # 1. Gera roteiro
            log_info("📝 Gerando roteiro com IA...")
            roteiro = self.script_gen.gerar_roteiro(
                tema=tema,
                idioma=idioma,
                modo=modo,
                duracao=duracao
            )

            log_success(f"Roteiro gerado: {roteiro['titulo']}")
                        
            # 2. Gera áudios
            log_info("🎤 Gerando narrações...")
            audios = self.audio_gen.gerar_narracao_completa(roteiro, idioma)
            log_success(f"{len(audios)} áudios gerados")
            
            # 3. Processa imagens
            log_info("🖼️  Processando imagens...")
            imagens = self.image_proc.processar_cenas(roteiro['cenas'])
            log_success(f"{len(imagens)} imagens processadas")
            
            # 4. Monta vídeo
            log_info("🎥 Montando vídeo...")
            video_path = self.video_editor.montar_video(
                roteiro, audios, imagens, idioma
            )
            log_success(f"Vídeo criado: {video_path}")
            
            # 5. Upload (se solicitado)
            video_id = None
            if fazer_upload:
                log_info("📤 Fazendo upload para YouTube...")
                video_id = self.youtube.fazer_upload(
                    video_path,
                    roteiro['titulo'],
                    roteiro['descricao'],
                    roteiro['tags'],
                    idioma
                )
                log_success(f"Upload concluído! ID: {video_id}")
            
            # 6. Salva histórico
            self._save_history({
                'timestamp': datetime.now().isoformat(),
                'tema': tema,
                'modo': modo,
                'duracao': duracao,
                'idioma': idioma,
                'titulo': roteiro['titulo'],
                'video_path': str(video_path),
                'video_id': video_id,
                'uploadado': fazer_upload
            })
            
            return video_path, video_id
            
        except Exception as e:
            log_error(f"Erro na geração do vídeo: {e}")
            raise
        