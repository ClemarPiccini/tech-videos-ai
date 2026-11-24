"""Roteiro guiado: leitura do briefing colado, checagem de fatos e garantia de gancho/final."""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Dict, List, Optional

from app import settings
from app.models import Brief, Scene

# Rótulos aceitos no texto colado (sem acento, maiúsculas ou minúsculas)
LABELS: Dict[str, str] = {
    "tema": "topic",
    "assunto": "topic",
    "gancho": "hook",
    "hook": "hook",
    "fatos obrigatorios": "facts",
    "fatos": "facts",
    "virada": "twist",
    "reviravolta": "twist",
    "final": "ending",
    "fim": "ending",
    "encerramento": "ending",
}
_LABEL_RE = re.compile(
    r"^\s*(" + "|".join(sorted(LABELS, key=len, reverse=True)) + r")\s*:\s*(.*)$", re.IGNORECASE
)


def _strip_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _quoted(text: str) -> str:
    """Se houver uma frase entre aspas, usa só ela (ex.: 'Terminar com a pergunta: "…"')."""
    m = re.search(r"[\"“”«](.+?)[\"“”»]", text)
    return (m.group(1) if m else text).strip().strip("\"“”«» ")


def parse_brief(text: str) -> Optional[Brief]:
    """Lê um briefing no formato 'TEMA: …  GANCHO: …  FATOS OBRIGATÓRIOS: - … VIRADA: … FINAL: …'."""
    fields: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _LABEL_RE.match(_strip_accents(line))
        if m:
            current = LABELS[m.group(1).lower()]
            # Recupera o conteúdo do texto original (com acentos), após o primeiro ":"
            rest = line.split(":", 1)[1].strip()
            fields.setdefault(current, [])
            if rest:
                fields[current].append(rest)
        elif current:
            fields[current].append(line)
    if not fields:
        return None

    def joined(key: str) -> str:
        return " ".join(fields.get(key, [])).strip()

    facts = [re.sub(r"^(\s*[-•*–]|\s*\d+[.)])\s*", "", f).strip() for f in fields.get("facts", [])]
    brief = Brief(
        topic=joined("topic"),
        hook=_quoted(joined("hook")),
        facts=[f for f in facts if f],
        twist=joined("twist"),
        ending=_quoted(joined("ending")),
    )
    return None if brief.is_empty() else brief


# ---------------- tamanho ----------------


def brief_words(brief: Brief) -> int:
    parts = [brief.hook, brief.twist, brief.ending, *brief.facts]
    return sum(len(p.split()) for p in parts)


def min_words(brief: Brief) -> int:
    """Palavras mínimas para contar tudo com naturalidade (frases de ligação somam ~30%)."""
    return math.ceil(brief_words(brief) * 1.3)


def recommended_seconds(brief: Brief) -> int:
    cfg = settings.config()["narration"]
    seconds = min_words(brief) / float(cfg["words_per_second"])
    scenes = len(brief.facts) + 3
    seconds += scenes * float(cfg.get("pause_between_scenes", 0.25))
    return int(math.ceil(seconds / 5.0) * 5)  # arredonda para múltiplos de 5 s


# ---------------- checagem de fatos ----------------

_NUMBER_WORDS = {
    "um": "1", "uma": "1", "dois": "2", "duas": "2", "tres": "3", "quatro": "4", "cinco": "5", "seis": "6",
    "sete": "7", "oito": "8", "nove": "9", "dez": "10", "onze": "11", "doze": "12", "treze": "13",
    "quatorze": "14", "catorze": "14", "quinze": "15", "vinte": "20", "trinta": "30", "cem": "100",
    "mil": "1000",
}
_PT_STOP = {
    "para", "pela", "pelo", "como", "mais", "muito", "estava", "estavam", "tinha", "tinham", "havia", "quase",
    "toda", "todo", "todos", "todas", "esse", "essa", "este", "esta", "isso", "isto", "sobre", "entre",
    "apenas", "ainda", "onde", "quando", "incluindo", "continuavam", "continuava",
}


def _norm_tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", _strip_accents(text.lower()))


def _numbers(text: str) -> set:
    toks = _norm_tokens(text)
    return {t for t in toks if t.isdigit()} | {_NUMBER_WORDS[t] for t in toks if t in _NUMBER_WORDS}


def _keywords(text: str) -> set:
    # Prefixo de 5 letras como "radical" barato: "salva-vidas"/"salvar", "intactas"/"intacta"
    return {t[:5] for t in _norm_tokens(text) if len(t) >= 5 and not t.isdigit() and t not in _PT_STOP}


def fact_covered(fact: str, narration: str) -> bool:
    """Heurística: todos os números do fato aparecem e pelo menos metade das palavras-chave."""
    nums = _numbers(fact)
    if nums and not nums <= _numbers(narration):
        return False
    keys = _keywords(fact)
    if not keys:
        return True
    return len(keys & _keywords(narration)) >= math.ceil(len(keys) / 2)


def missing_facts(brief: Brief, scenes: List[Scene]) -> List[str]:
    text = " ".join(s.narration for s in scenes)
    return [f for f in brief.facts if not fact_covered(f, text)]


# ---------------- gancho e final ----------------


def _norm(text: str) -> str:
    return " ".join(_norm_tokens(text))


def enforce_hook_and_ending(scenes: List[Scene], brief: Brief) -> List[Scene]:
    """Garante, sem depender do modelo, que o vídeo abre com o gancho e fecha com o final exatos."""
    if not scenes:
        return scenes
    scenes = list(scenes)

    if brief.hook:
        first = scenes[0]
        if not _norm(first.narration).startswith(_norm(brief.hook)):
            rest = first.narration
            # Se o modelo parafraseou o gancho na 1ª frase, troca a frase em vez de duplicar a ideia
            sentences = re.split(r"(?<=[.!?…])\s+", rest, maxsplit=1)
            if len(sentences) == 2 and len(sentences[0].split()) <= len(brief.hook.split()) + 6:
                rest = sentences[1]
            scenes[0] = first.model_copy(update={"narration": f"{brief.hook} {rest}".strip()})

    if brief.ending:
        last = scenes[-1]
        text = last.narration
        n_text, n_end = _norm(text), _norm(brief.ending)
        if n_end in n_text:
            # Corta qualquer coisa que venha depois do final (ex.: um CTA acrescentado pelo modelo)
            idx = text.lower().find(brief.ending.lower()[:20])
            if idx >= 0:
                text = text[:idx] + brief.ending
        else:
            text = f"{text.rstrip()} {brief.ending}".strip()
        scenes[-1] = last.model_copy(update={"narration": text})
    return scenes


def guided_slots(brief: Brief) -> List[tuple]:
    """Estrutura fixa do roteiro guiado: (tipo, conteúdo)."""
    slots = [("hook", brief.hook)]
    slots += [("fact", f) for f in brief.facts]
    if brief.twist:
        slots.append(("twist", brief.twist))
    slots.append(("ending", brief.ending))
    return slots


def as_sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?…" else text + "."


def insert_missing_facts(scenes: List[Scene], brief: Brief) -> List[Scene]:
    """Último recurso: fatos obrigatórios que a IA não incluiu entram com as palavras do próprio usuário,
    numa cena nova antes da virada (ou antes da cena final)."""
    missing = missing_facts(brief, scenes)
    if not missing or not scenes:
        return scenes
    scenes = list(scenes)
    pos = len(scenes) - 1
    if brief.twist:
        for i, s in enumerate(scenes):
            if i > 0 and fact_covered(brief.twist, s.narration):
                pos = i
                break
    neighbor = scenes[max(0, pos - 1)]
    for fact in missing:
        scenes.insert(pos, Scene(narration=as_sentence(fact), visual_queries=list(neighbor.visual_queries)))
        pos += 1
    return scenes
