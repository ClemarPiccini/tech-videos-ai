"""Cliente mínimo da API HTTP do Ollama (modelos de IA locais e gratuitos)."""
from __future__ import annotations

import json
import threading
from typing import Any, Dict, List, Optional

import requests

from app import settings


def base_url() -> str:
    return settings.config()["llm"].get("ollama_url", "http://localhost:11434").rstrip("/")


def current_model() -> str:
    return settings.env("OLLAMA_MODEL") or settings.config()["llm"]["ollama_model"]


def list_models() -> Optional[List[str]]:
    """Modelos instalados, ou None se o Ollama não estiver rodando."""
    try:
        r = requests.get(f"{base_url()}/api/tags", timeout=3)
        r.raise_for_status()
    except requests.RequestException:
        return None
    return sorted(m["name"] for m in r.json().get("models", []))


def has_model(models: List[str], name: str) -> bool:
    wanted = name if ":" in name else f"{name}:latest"
    return wanted in models or name in models


def chat_json(system: str, user: str, schema: Dict[str, Any], model: Optional[str] = None) -> Dict[str, Any]:
    """Chamada com saída estruturada: o Ollama restringe a geração ao JSON schema enviado em `format`."""
    cfg = settings.config()["llm"]
    payload = {
        "model": model or current_model(),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": schema,
        "stream": False,
        "options": {"temperature": 0.8, "num_ctx": int(cfg.get("ollama_num_ctx", 8192)), "num_predict": 6000},
    }
    try:
        r = requests.post(f"{base_url()}/api/chat", json=payload, timeout=900)
    except requests.ConnectionError:
        raise RuntimeError("O Ollama não está rodando. Abra o app Ollama (ollama.com/download).") from None
    if r.status_code == 404:
        raise RuntimeError(f"Modelo '{payload['model']}' não instalado. Baixe-o em Configurações.")
    if r.status_code != 200:
        raise RuntimeError(f"Ollama respondeu {r.status_code}: {r.text[:300]}")
    content = r.json().get("message", {}).get("content", "")
    try:
        return json.loads(content)
    except ValueError:
        raise RuntimeError("O modelo local retornou um JSON inválido. Tente de novo ou use um modelo maior.") from None


def inline_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve $ref/$defs do schema do Pydantic e remove campos que só atrapalham a gramática."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            out = {}
            for k, v in node.items():
                if k in ("$defs", "title", "default"):  # metadados do Pydantic, não campos
                    continue
                if k == "properties":
                    # Aqui as chaves são NOMES de campos (inclusive um campo chamado "title")
                    out[k] = {name: walk(prop) for name, prop in v.items()}
                else:
                    out[k] = walk(v)
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


# ---------------- download de modelos ----------------


class PullTracker:
    """Acompanha um download de modelo por vez, em background."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state: Dict[str, Any] = {"model": None, "status": "idle", "percent": 0, "error": None}

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return dict(self.state)

    def start(self, model: str) -> bool:
        with self.lock:
            if self.state["status"] == "pulling":
                return False
            self.state = {"model": model, "status": "pulling", "percent": 0, "error": None}
        threading.Thread(target=self._run, args=(model,), daemon=True).start()
        return True

    def _set(self, **kw: Any) -> None:
        with self.lock:
            self.state.update(kw)

    def _run(self, model: str) -> None:
        try:
            with requests.post(f"{base_url()}/api/pull", json={"model": model, "stream": True},
                               stream=True, timeout=(5, 600)) as r:
                if r.status_code != 200:
                    raise RuntimeError(f"Ollama respondeu {r.status_code}: {r.text[:200]}")
                for line in r.iter_lines():
                    if not line:
                        continue
                    msg = json.loads(line)
                    if msg.get("error"):
                        raise RuntimeError(msg["error"])
                    total, done = msg.get("total"), msg.get("completed")
                    if total and done:
                        self._set(percent=round(100 * done / total, 1))
                    if msg.get("status") == "success":
                        self._set(status="done", percent=100)
                        return
            self._set(status="done", percent=100)
        except requests.ConnectionError:
            self._set(status="error", error="O Ollama não está rodando.")
        except Exception as e:  # noqa: BLE001 — exibido na interface
            self._set(status="error", error=str(e))


pull_tracker = PullTracker()
