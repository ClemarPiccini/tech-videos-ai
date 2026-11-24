"""Carrega config.yaml, presets.yaml e variáveis de ambiente."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _load_yaml(name: str) -> Dict[str, Any]:
    with open(BASE_DIR / name, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def config() -> Dict[str, Any]:
    return _load_yaml("config.yaml")


def presets() -> Dict[str, Any]:
    # Sem cache: permite editar presets.yaml sem reiniciar o servidor.
    return _load_yaml("presets.yaml")


def path(key: str) -> Path:
    p = Path(config()["paths"][key])
    if not p.is_absolute():
        p = BASE_DIR / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def env(name: str) -> str:
    return (os.getenv(name) or "").strip()


ENV_FILE = BASE_DIR / ".env"


def set_env(updates: Dict[str, str], env_file: Optional[Path] = None) -> None:
    """Grava/atualiza variáveis no .env (preservando comentários) e aplica no processo atual."""
    env_file = env_file or ENV_FILE
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    pending = dict(updates)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if not line.lstrip().startswith("#") and "=" in line and key in pending:
            out.append(f"{key}={pending.pop(key)}")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in pending.items()]
    env_file.write_text("\n".join(out) + "\n", encoding="utf-8")
    try:
        env_file.chmod(0o600)
    except OSError:
        pass
    for k, v in updates.items():
        os.environ[k] = v
