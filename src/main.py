import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from colorama import init, Fore, Style

# Inicializa colorama
init(autoreset=True)

# Carrega variáveis de ambiente
load_dotenv()

from moviepy.config import change_settings

change_settings({
    "IMAGEMAGICK_BINARY": "magick"
})

from video_generator import TechVideoGenerator
from utils import setup_logging, load_config


def build_parser():
    parser = argparse.ArgumentParser(description='Gerador Automático de Vídeos Tech Dark')
    parser.add_argument('--tema', type=str, help='Tema do vídeo')
    parser.add_argument('--idioma', type=str, default='pt', choices=['pt', 'es', 'en'], help='Idioma do vídeo (pt/es/en)')
    parser.add_argument('--upload', action='store_true', help='Fazer upload automático para YouTube')
    parser.add_argument('--batch', type=int, help='Gerar múltiplos vídeos (quantidade)')
    parser.add_argument('--test', action='store_true', help='Modo de teste (não faz upload)')
    parser.add_argument('--modo', choices=['short', 'long'], default='short', help='Tipo do vídeo')
    parser.add_argument('--duracao', type=int, help='Duração do vídeo em segundos')
    parser.add_argument('--gui', action='store_true', help='Abre a interface gráfica para inserir tema e duração')
    return parser


def run_generation(args):
    logger = setup_logging()
    config = load_config()

    print(f"{Fore.CYAN}{'='*60}")
    print(f"{Fore.GREEN}🎬 GERADOR DE VÍDEOS TECH DARK")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")

    try:
        generator = TechVideoGenerator(config)

        if args.batch:
            print(f"\n{Fore.YELLOW}📦 Modo batch: {args.batch} vídeos{Style.RESET_ALL}\n")
            for i in range(args.batch):
                print(f"\n{Fore.MAGENTA}[{i+1}/{args.batch}] Gerando vídeo...{Style.RESET_ALL}")
                generator.gerar_video_completo(
                    tema=args.tema,
                    idioma=args.idioma,
                    modo=args.modo,
                    duracao=args.duracao,
                    fazer_upload=args.upload and not args.test
                )
        else:
            generator.gerar_video_completo(
                tema=args.tema,
                idioma=args.idioma,
                modo=args.modo,
                duracao=args.duracao,
                fazer_upload=args.upload and not args.test
            )

        print(f"\n{Fore.GREEN}✅ Processo concluído com sucesso!{Style.RESET_ALL}\n")
        return True

    except Exception as e:
        logger.error(f"Erro no processo: {e}", exc_info=True)
        print(f"\n{Fore.RED}❌ Erro: {e}{Style.RESET_ALL}\n")
        return False


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.gui or len(sys.argv) == 1:
        from interface import launch_interface
        return launch_interface()

    ok = run_generation(args)
    if not ok:
        sys.exit(1)

if __name__ == "__main__":
    main()
