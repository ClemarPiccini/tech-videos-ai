"""Modelos de dados compartilhados entre interface, pipeline e API."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field
from typing_extensions import Literal

Platform = Literal["youtube", "shorts", "tiktok", "reels"]
Language = Literal["pt", "es", "en"]
VoiceEngine = Literal["edge", "elevenlabs"]


class Brief(BaseModel):
    """Roteiro guiado: o usuário define a estrutura e os fatos; a IA só escreve a narração."""

    topic: str = ""
    hook: str = ""
    facts: List[str] = Field(default_factory=list)
    twist: str = ""
    ending: str = ""

    def is_empty(self) -> bool:
        return not (self.topic or self.hook or self.facts or self.twist or self.ending)


class VideoRequest(BaseModel):
    """O que o usuário preenche na interface."""

    brief: Optional[Brief] = None

    prompt: str = Field("", description="Ideia/tema do vídeo. Vazio = Claude escolhe dentro do nicho.")
    niche: str = "misterios"
    platform: Platform = "reels"
    duration_seconds: int = Field(30, ge=15, le=1800)
    language: Language = "pt"
    tone: Optional[str] = None
    voice_engine: VoiceEngine = "edge"
    voice: Optional[str] = None
    captions: bool = True
    music: bool = True
    cta: bool = True
    extra_instructions: str = ""


# ---- Saída estruturada do Claude (sem restrições numéricas: o schema é enviado à API) ----


class Scene(BaseModel):
    narration: str = Field(description="Texto exato a ser narrado nesta cena, no idioma do vídeo.")
    visual_queries: List[str] = Field(
        description="1 a 3 buscas curtas EM INGLÊS para banco de vídeos stock (2-4 palavras concretas cada)."
    )


class VideoScript(BaseModel):
    title: str
    visual_subject: str = Field(description="Assunto principal na tela, em inglês, 2-3 palavras concretas.")
    description: str
    tags: List[str]
    hashtags: List[str]
    thumbnail_text: str = Field(description="2 a 5 palavras de impacto para a thumbnail.")
    scenes: List[Scene]


# ---- Artefatos intermediários ----


class Word(BaseModel):
    text: str
    start: float
    end: float


class SceneAudio(BaseModel):
    path: str
    duration: float
    words: List[Word]
