import yaml
import logging
from pathlib import Path
from datetime import datetime
from colorama import Fore, Style

BASE_DIR = Path(__file__).resolve().parent.parent

def load_config():
    config_path = BASE_DIR / "config.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"config.yaml não encontrado em: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def setup_logging():
    log_dir = BASE_DIR / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"app_{datetime.now().strftime('%Y%m%d')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    return logging.getLogger(__name__)

def log_info(msg):
    print(f"{Fore.CYAN}ℹ️  {msg}{Style.RESET_ALL}")
    logging.info(msg)

def log_success(msg):
    print(f"{Fore.GREEN}✅ {msg}{Style.RESET_ALL}")
    logging.info(msg)

def log_error(msg):
    print(f"{Fore.RED}❌ {msg}{Style.RESET_ALL}")
    logging.error(msg)

def log_warning(msg):
    print(f"{Fore.YELLOW}⚠️  {msg}{Style.RESET_ALL}")
    logging.warning(msg)
