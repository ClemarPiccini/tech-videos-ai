from dotenv import load_dotenv
load_dotenv()

import sys
sys.path.append('src')

from video_generator import TechVideoGenerator
from utils import load_config, setup_logging

def test():
    print("🧪 TESTE DE GERAÇÃO DE VÍDEO\\n")
    
    setup_logging()
    config = load_config()
    
    generator = TechVideoGenerator(config)
    
    print("Gerando vídeo de teste...\\n")
    
    video_path, video_id = generator.gerar_video_completo(
        tema="Inteligência Artificial",
        idioma="pt",
        fazer_upload=False  # Não faz upload no teste
    )
    
    print(f"\\n✅ Teste concluído!")
    print(f"Vídeo gerado: {video_path}")

if __name__ == "__main__":
    test()
