"""Geração do roteiro: Claude (com chave) ou modelo local via Ollama (grátis), ambos com saída estruturada."""
from __future__ import annotations

import math
import re
from typing import Callable, List, Optional

import anthropic
from pydantic import BaseModel, Field

from app import settings
from app.models import Brief, Scene, VideoRequest, VideoScript
from app.pipeline import ollama
from app.pipeline.brief import (as_sentence, enforce_hook_and_ending, fact_covered, guided_slots,
                                insert_missing_facts, min_words, missing_facts, parse_brief)
from app.pipeline.visuals import core_phrase

LANG_NAMES = {"pt": "português do Brasil", "es": "espanhol latino-americano", "en": "inglês americano"}

SYSTEM_PROMPT = """\
Você é roteirista-chefe de perfis "dark" (faceless) de alta retenção em Reels, TikTok, Shorts e YouTube.
Seu roteiro vira narração em voz sintética sobre vídeos de banco de imagens, com legendas na tela.

Como você escreve:
- A primeira frase é o gancho: uma afirmação ou pergunta que cria um loop aberto e obriga a continuar assistindo. Nada de "olá", "bem-vindos" ou apresentar o perfil.
- Revele a informação aos poucos. Abra perguntas e só responda mais adiante. Em vídeos longos, crie um mini-cliffhanger a cada 45-60 segundos.
- Frases curtas e faladas, fáceis de narrar. Sem emojis, sem markdown, sem listas, sem indicações de cena dentro da narração.
- Escreva números e anos com algarismos (ex.: 10, 1872): a voz lê corretamente.
- Termine com um desfecho que recompense quem assistiu até o fim.
- Respeite o número de palavras pedido: a narração vira áudio e o vídeo precisa ter a duração escolhida.

Integridade (obrigatório):
- Fatos reais devem ser fiéis ao que é documentado publicamente. Quando algo for teoria, lenda ou especulação, diga isso na narração.
- Não invente citações, datas, números ou nomes apresentados como verdadeiros. Na dúvida, não cite a data/nome.
- Não incentive violência, autolesão ou atividades ilegais; trate vítimas reais com respeito.

Busca visual:
- visual_subject: o assunto principal que aparece na tela, em inglês, 2 a 3 palavras concretas e SEM nomes próprios
  (ex.: num vídeo sobre um farol: "old lighthouse"; sobre uma mina: "abandoned mine tunnel").
- visual_queries: em inglês, 2 a 4 palavras que descrevem algo FÍSICO e FILMÁVEL, que um cinegrafista conseguiria gravar
  (ex.: "wooden door closeup", "rain on window", "police lights night", "candle in the dark").
- PROIBIDO em visual_queries: conceitos e ideias ("mystery", "theory", "investigation", "evidence", "curse", "incident", "enemy", "fear"),
  anos ou números, nomes de pessoas/navios/marcas, e chamadas como "subscribe" ou "follow".
- Pelo menos uma busca de cada cena deve conter o objeto/lugar principal do vídeo. Na cena do CTA, use o visual_subject.

Metadados (siga as REGRAS DA PLATAFORMA enviadas na mensagem):
- title: até 70 caracteres, desperta curiosidade sem prometer o que o vídeo não entrega.
- tags: 10 a 15 termos de busca, sem "#".
- hashtags: cada uma começando com "#", relevantes ao tema (não genéricas como #viral).
- thumbnail_text: 2 a 5 palavras em caixa alta, no idioma do vídeo, com ortografia correta.
"""

PLATFORM_RULES = {
    "reels": (
        "REGRAS DA PLATAFORMA (Instagram Reels):\n"
        "- description é a LEGENDA do post: primeira linha com um gancho de até 120 caracteres (é o que aparece antes do 'mais'), "
        "depois 2 a 4 linhas curtas com contexto e uma chamada para salvar, compartilhar ou comentar.\n"
        "- hashtags: no máximo 5 (limite do Instagram).\n"
        "- CTA falado: peça para seguir o perfil ou comentar; nunca diga 'inscreva-se' ou 'canal'.\n"
        "- O vídeo volta ao início automaticamente: a última frase pode se conectar com a primeira."
    ),
    "tiktok": (
        "REGRAS DA PLATAFORMA (TikTok):\n"
        "- description: legenda curta (1-2 frases) com gancho.\n- hashtags: 3 a 5.\n"
        "- CTA falado: seguir o perfil / parte 2; nunca 'inscreva-se'."
    ),
    "shorts": (
        "REGRAS DA PLATAFORMA (YouTube Shorts):\n"
        "- description: 1 parágrafo curto com palavras-chave.\n- hashtags: 3 a 5.\n- CTA falado: inscrever-se no canal."
    ),
    "youtube": (
        "REGRAS DA PLATAFORMA (YouTube):\n"
        "- description: 2 a 3 parágrafos otimizados para busca, terminando com convite para se inscrever.\n"
        "- hashtags: 3 a 5.\n- CTA falado: inscrever-se no canal."
    ),
}


def scene_count(duration: int, vertical: bool) -> int:
    seconds_per_scene = 6 if vertical else 10
    return max(4, min(120, round(duration / seconds_per_scene)))


def scenes_for(req: VideoRequest) -> int:
    """Cenas do vídeo; no roteiro guiado, no mínimo gancho + 1 por fato + virada + final."""
    vertical = settings.presets()["platforms"][req.platform]["orientation"] == "vertical"
    n = scene_count(req.duration_seconds, vertical)
    if req.brief and not req.brief.is_empty():
        n = max(n, len(req.brief.facts) + 3)
    return n


def target_words(req: VideoRequest) -> int:
    """Palavras que cabem na duração pedida, descontando as pausas entre cenas."""
    cfg = settings.config()["narration"]
    pauses = scenes_for(req) * float(cfg.get("pause_between_scenes", 0.25))
    words = max(20, round((req.duration_seconds - pauses) * float(cfg["words_per_second"])))
    if req.brief and not req.brief.is_empty():
        # Nunca condensar a ponto de cortar os fatos obrigatórios
        words = max(words, min_words(req.brief))
    return words


def with_brief(req: VideoRequest) -> VideoRequest:
    """Se o usuário colou um briefing no campo de ideia, transforma em roteiro guiado."""
    if req.brief and not req.brief.is_empty():
        return req
    parsed = parse_brief(req.prompt)
    return req.model_copy(update={"brief": parsed}) if parsed else req


def brief_prompt(brief: Brief) -> str:
    lines = ["ROTEIRO GUIADO — siga esta estrutura à risca:"]
    if brief.hook:
        lines.append(f'- Cena 1 COMEÇA exatamente com este gancho, palavra por palavra: "{brief.hook}"')
    if brief.facts:
        lines.append("- Fatos OBRIGATÓRIOS (todos devem aparecer, com os números exatos, de preferência um por cena, "
                     "revelados aos poucos para criar tensão):")
        lines += [f"    • {f}" for f in brief.facts]
    if brief.twist:
        lines.append(f"- VIRADA (perto do fim, antes do final): {brief.twist}")
    if brief.ending:
        lines.append(f'- O vídeo TERMINA exatamente com esta frase, palavra por palavra, sem nada depois: "{brief.ending}"')
    lines.append("- Use SOMENTE os fatos acima. Não acrescente outras datas, números, nomes, causas ou teorias. "
                 "Frases de ligação e clima são bem-vindas; fatos novos não.")
    return "\n".join(lines)


def build_user_prompt(req: VideoRequest) -> str:
    p = settings.presets()
    niche = p["niches"].get(req.niche) or next(iter(p["niches"].values()))
    platform = p["platforms"][req.platform]
    vertical = platform["orientation"] == "vertical"
    tone_key = req.tone or niche.get("default_tone", "suspense")
    tone = p["tones"].get(tone_key, tone_key)

    words = target_words(req)
    scenes = scenes_for(req)
    minutes, seconds = divmod(req.duration_seconds, 60)
    dur_txt = f"{minutes} min {seconds:02d} s" if minutes else f"{seconds} s"

    brief = req.brief if req.brief and not req.brief.is_empty() else None
    topic = (brief.topic if brief and brief.topic else "") or req.prompt.strip() or (
        "Escolha você um tema inédito e com alto potencial viral dentro do nicho. "
        f"Exemplos do estilo: {'; '.join(niche.get('ideas', []))}"
    )

    lines = [
        f"TEMA: {topic}",
        f"NICHO: {niche['label']} — {niche['guidance']}",
        f"ESTILO VISUAL DO NICHO: {niche.get('visual_style', '')}",
        f"PLATAFORMA: {platform['label']} ({'vertical 9:16' if vertical else 'horizontal 16:9'})",
        f"DURAÇÃO: exatamente {dur_txt} de narração = {words} palavras no TOTAL (entre {round(words * 0.9)} e "
        f"{round(words * 1.1)}). Mais que isso deixa o vídeo longo demais.",
        f"NÚMERO DE CENAS: {scenes}, cada uma com cerca de {max(5, round(words / scenes))} palavras "
        "(frases completas e encadeadas, não fragmentos soltos).",
        f"TOM: {tone}",
        f"IDIOMA da narração, título, descrição, tags e thumbnail: {LANG_NAMES[req.language]}.",
        PLATFORM_RULES.get(req.platform, ""),
    ]
    if vertical:
        lines.append("Formato curto: ritmo acelerado, gancho nos primeiros 2 segundos.")
    if brief:
        lines.append(brief_prompt(brief))
    if brief and brief.ending:
        lines.append("Não acrescente CTA depois da frase final.")
    elif req.cta:
        lines.append("A última cena termina com um CTA natural e curto, ligado ao tema, seguindo as regras da plataforma.")
    else:
        lines.append("Não inclua pedidos para seguir/inscrever-se/curtir na narração.")
    if req.extra_instructions.strip():
        lines.append(f"INSTRUÇÕES ADICIONAIS DO USUÁRIO: {req.extra_instructions.strip()}")
    return "\n".join(lines)


class ProviderUnavailable(RuntimeError):
    """Falha de conta/conexão que justifica cair para o modelo local no modo automático."""


def configured_provider() -> str:
    return (settings.env("LLM_PROVIDER") or settings.config()["llm"].get("provider", "auto")).lower()


def resolve_provider() -> str:
    """Motor efetivo: 'anthropic' ou 'ollama'."""
    p = configured_provider()
    if p in ("anthropic", "ollama"):
        return p
    return "anthropic" if settings.env("ANTHROPIC_API_KEY") else "ollama"


def provider_label() -> str:
    cfg = settings.config()["llm"]
    if resolve_provider() == "anthropic":
        return f"Claude ({cfg['anthropic_model']})"
    return f"Local ({ollama.current_model()})"


class ScriptGenerator:
    def __init__(self, log: Optional[Callable[[str], None]] = None) -> None:
        self.log = log or (lambda msg: None)

    MAX_FACT_FIXES = 2

    def generate(self, req: VideoRequest) -> VideoScript:
        req = with_brief(req)
        writer = None
        if resolve_provider() == "anthropic":
            try:
                writer = AnthropicWriter()
                script = writer.write(req)
            except ProviderUnavailable as e:
                local = ollama.list_models()
                if configured_provider() != "auto" or not local or not ollama.has_model(local, ollama.current_model()):
                    raise
                self.log(f"{e} Usando o modelo local {ollama.current_model()}.")
                writer = None
        if writer is None:
            writer = OllamaWriter(self.log)
            script = writer.write(req)
        if req.brief and not req.brief.is_empty():
            script = self._apply_brief(script, req, writer)
        return clean_script(script, req)

    def _expand_guided(self, scenes: List[Scene], req: VideoRequest, writer) -> List[Scene]:
        """Roteiro guiado curto demais: acrescenta clima e contexto sem fatos novos, sem perder os obrigatórios."""
        target = target_words(req)
        for _ in range(2):
            current = count_words(scenes)
            if current >= target * 0.85:
                break
            self.log(f"Roteiro guiado: {current}/{target} palavras, desenvolvendo a narração…")
            instruction = (
                f"A narração está curta ({current} palavras) para a duração do vídeo. Desenvolva cada cena com clima, "
                "detalhes sensoriais da cena (o mar, o convés, o silêncio), perguntas que criam tensão e frases de "
                "ligação. NÃO acrescente fatos, números, datas, nomes ou teorias novos. Mantenha todos os fatos e "
                "números atuais exatamente como estão, o gancho no início e a frase final no fim. "
                "Cada cena continua falando SÓ do seu próprio assunto: não repita fatos de outras cenas.\n\n"
                + brief_prompt(req.brief)
            )
            longer = writer.revise(scenes, instruction, req, exact=True)
            lost = len(missing_facts(req.brief, longer)) > len(missing_facts(req.brief, scenes))
            # Rejeita se o modelo fundiu/repetiu cenas (a deduplicação removeu alguma)
            if lost or len(longer) < len(scenes) or count_words(longer) <= current:
                break
            scenes = longer
        return scenes

    def _apply_brief(self, script: VideoScript, req: VideoRequest, writer) -> VideoScript:
        brief = req.brief
        scenes = list(script.scenes)
        for _ in range(self.MAX_FACT_FIXES):
            missing = missing_facts(brief, scenes)
            if not missing:
                break
            self.log(f"Roteiro guiado: {len(missing)} fato(s) faltando, corrigindo…")
            instruction = (
                "Os seguintes fatos OBRIGATÓRIOS não aparecem na narração. Reescreva as cenas incluindo TODOS eles, "
                "com os números exatos, sem acrescentar nenhum outro fato:\n"
                + "\n".join(f"- {f}" for f in missing)
                + "\n\n" + brief_prompt(brief)
            )
            fixed = writer.revise(scenes, instruction, req)
            if len(missing_facts(brief, fixed)) < len(missing):
                scenes = fixed
            else:
                break
        scenes = self._expand_guided(scenes, req, writer)
        still = missing_facts(brief, scenes)
        if still:
            self.log("A IA não incluiu: " + "; ".join(still) + ". Inserido com as suas palavras.")
            scenes = insert_missing_facts(scenes, brief)
        scenes = enforce_hook_and_ending(scenes, brief)
        update = {"scenes": scenes}
        if brief.topic and not script.visual_subject:
            update["visual_subject"] = brief.topic
        return script.model_copy(update=update)


# ---------------- Claude ----------------


class AnthropicWriter:
    def __init__(self) -> None:
        if not settings.env("ANTHROPIC_API_KEY"):
            raise ProviderUnavailable("ANTHROPIC_API_KEY não configurada.")
        self.client = anthropic.Anthropic(api_key=settings.env("ANTHROPIC_API_KEY"))
        cfg = settings.config()["llm"]
        self.model = cfg["anthropic_model"]
        self.max_tokens = int(cfg.get("max_tokens", 16000))

    def write(self, req: VideoRequest) -> VideoScript:
        try:
            return self._write(req)
        except anthropic.AuthenticationError:
            raise ProviderUnavailable("Chave da Anthropic inválida.") from None
        except anthropic.BadRequestError as e:
            if "credit balance" in str(e).lower():
                raise ProviderUnavailable(
                    "Conta da Anthropic sem créditos (console.anthropic.com → Settings → Billing)."
                ) from None
            raise
        except anthropic.RateLimitError:
            raise RuntimeError("Limite de requisições da Anthropic atingido. Aguarde um minuto e tente de novo.") from None
        except anthropic.APIConnectionError:
            raise ProviderUnavailable("Sem conexão com a API da Anthropic.") from None

    def _write(self, req: VideoRequest) -> VideoScript:
        response = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_prompt(req)}],
            output_format=VideoScript,
            # Se o classificador de segurança recusar, a API tenta outro modelo automaticamente.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            reason = getattr(details, "explanation", None) or "sem detalhes"
            raise RuntimeError(f"O Claude recusou este tema ({reason}). Tente reformular.")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("Roteiro cortado por limite de tokens. Aumente llm.max_tokens no config.yaml.")
        script = response.parsed_output
        if script is None or not script.scenes:
            raise RuntimeError("O Claude não retornou um roteiro válido.")
        return script

    def revise(self, scenes: List[Scene], instruction: str, req: VideoRequest, exact: bool = False) -> List[Scene]:
        """Reescreve as cenas seguindo uma instrução (usado para incluir fatos que faltaram)."""
        response = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": revise_prompt(scenes, instruction, req)}],
            output_format=_Scenes,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        out = response.parsed_output
        return dedupe_scenes(out.scenes) if out and out.scenes else scenes


# ---------------- Modelo local (Ollama) ----------------


class _Part(BaseModel):
    summary: str = Field(description="O que acontece/é revelado nesta parte (1-2 frases).")


class _Plan(BaseModel):
    title: str
    visual_subject: str
    description: str
    tags: List[str]
    hashtags: List[str]
    thumbnail_text: str
    parts: List[_Part]


class _Scenes(BaseModel):
    scenes: List[Scene]


def schema_with_scene_count(model: type, n_min: int, n_max: int) -> dict:
    """Schema para o Ollama com o número de cenas travado na gramática (o modelo não pode fugir dele)."""
    schema = ollama.inline_schema(model.model_json_schema())
    schema["properties"]["scenes"].update({"minItems": n_min, "maxItems": n_max})
    return schema


LOCAL_JSON_RULES = (
    "\nResponda somente com o JSON pedido. Os campos de texto (narration, title, description, tags, "
    "thumbnail_text) devem estar no idioma do vídeo; apenas visual_queries fica em inglês."
)


class OllamaWriter:
    """Modelos locais são menores: vídeos longos são escritos em partes para atingir a duração."""

    def __init__(self, log: Callable[[str], None]) -> None:
        self.log = log
        cfg = settings.config()["llm"]
        self.single_max = int(cfg.get("ollama_single_pass_max_seconds", 150))
        self.seconds_per_part = int(cfg.get("ollama_seconds_per_part", 90))
        models = ollama.list_models()
        if models is None:
            raise RuntimeError(
                "Nenhuma IA disponível: o Ollama não está rodando e não há chave da Anthropic. "
                "Instale o Ollama (ollama.com/download) ou cole sua chave em Configurações."
            )
        if not ollama.has_model(models, ollama.current_model()):
            raise RuntimeError(f"O modelo local '{ollama.current_model()}' não está baixado. Baixe-o em Configurações.")

    def write(self, req: VideoRequest) -> VideoScript:
        if req.brief and not req.brief.is_empty():
            return self._write_guided(req)
        if req.duration_seconds <= self.single_max:
            n = scenes_for(req)
            data = ollama.chat_json(SYSTEM_PROMPT + LOCAL_JSON_RULES, build_user_prompt(req),
                                    schema_with_scene_count(VideoScript, n, n + 2))
            script = VideoScript.model_validate(data)
            scenes = self._fit_length(dedupe_scenes(script.scenes), target_words(req), req)
            return script.model_copy(update={"scenes": scenes})
        return self._write_in_parts(req)

    def revise(self, scenes: List[Scene], instruction: str, req: VideoRequest, exact: bool = False) -> List[Scene]:
        n = len(scenes)
        data = ollama.chat_json(SYSTEM_PROMPT + LOCAL_JSON_RULES, revise_prompt(scenes, instruction, req),
                                schema_with_scene_count(_Scenes, n, n if exact else n + 2))
        out = dedupe_scenes(_Scenes.model_validate(data).scenes)
        return out or scenes

    def _write_guided(self, req: VideoRequest) -> VideoScript:
        """Roteiro guiado com modelo local: a estrutura é fixa (abertura, 1 cena por fato, virada, final)
        e o modelo só escreve o texto de cada cena. Evita que um modelo pequeno repita ou embaralhe os fatos."""
        brief = req.brief
        slots = guided_slots(brief)
        n = len(slots)
        fixed = len(brief.hook.split()) + len(brief.ending.split())
        per = max(8, round((target_words(req) - fixed) / n))
        self.log(f"Roteiro guiado: {n} cenas fixas, ~{per} palavras cada…")

        lines = []
        for i, (kind, content) in enumerate(slots, 1):
            if kind == "hook":
                start = f'COMEÇA exatamente com "{content}" e continua' if content else "gancho forte que"
                lines.append(f"{i}. ABERTURA — {start} com ~{per} palavras que aumentam a curiosidade, "
                             "sem revelar os fatos das próximas cenas.")
            elif kind == "fact":
                lines.append(f"{i}. FATO — apresente APENAS este fato, com os números exatos, em ~{per} palavras "
                             f"com tensão e clima: {content}")
            elif kind == "twist":
                lines.append(f"{i}. VIRADA — em ~{per} palavras, revele: {content}")
            else:
                end = f'e TERMINE exatamente com: "{content}"' if content else "e entregue o desfecho"
                lines.append(f"{i}. FINAL — ~{max(6, per // 2)} palavras que preparam o encerramento {end}")
        prompt = (
            build_user_prompt(req)
            + f"\n\nESCREVA EXATAMENTE {n} CENAS, nesta ordem. Cada cena fala SÓ do seu item; "
            "não repita fatos de outras cenas:\n" + "\n".join(lines)
        )
        data = ollama.chat_json(SYSTEM_PROMPT + LOCAL_JSON_RULES, prompt,
                                schema_with_scene_count(VideoScript, n, n))
        script = VideoScript.model_validate(data)

        scenes = []
        for (kind, content), scene in zip(slots, script.scenes):
            # Cena que não trouxe o seu fato recebe o fato com as palavras do usuário
            if kind in ("fact", "twist") and content and not fact_covered(content, scene.narration):
                scene = scene.model_copy(update={"narration": f"{as_sentence(content)} {scene.narration}".strip()})
            scenes.append(scene)
        return script.model_copy(update={"scenes": scenes})

    LENGTH_TOLERANCE = 0.2  # aceita de 80% a 120% do alvo sem reescrever
    MAX_REWRITES = 2

    def _fit_length(self, scenes: List[Scene], target: int, req: VideoRequest) -> List[Scene]:
        """Modelos pequenos erram muito o tamanho: reescreve (expandindo ou condensando) até caber no alvo."""
        for _ in range(self.MAX_REWRITES):
            current = count_words(scenes)
            if not scenes or abs(current - target) <= target * self.LENGTH_TOLERANCE:
                break
            expand = current < target
            self.log(f"Modelo local: roteiro {'curto' if expand else 'longo'} ({current}/{target} palavras), "
                     f"{'expandindo' if expand else 'condensando'}…")
            per_scene = max(5, round(target / len(scenes)))
            numbered = "\n".join(f"{i + 1}. {s.narration}" for i, s in enumerate(scenes))
            how = ("Acrescente detalhes concretos, contexto e tensão" if expand
                   else "Corte repetições e detalhes secundários, mantendo o essencial e a tensão")
            prompt = (
                f"Reescreva a narração destas {len(scenes)} cenas em {LANG_NAMES[req.language]}, mantendo a ordem, "
                f"o sentido e exatamente {len(scenes)} cenas. Cada cena deve ter cerca de {per_scene} palavras. "
                f"O TOTAL deve ficar entre {round(target * 0.9)} e {round(target * 1.1)} palavras — nem mais, nem menos. "
                f"{how}; frases completas e encadeadas; sem emojis. Mantenha a primeira frase como gancho"
                + (" e o CTA na última cena." if req.cta else ".")
                + "\nAs visual_queries continuam em inglês, concretas e filmáveis."
                + f"\n\nCENAS ATUAIS:\n{numbered}"
            )
            data = ollama.chat_json(SYSTEM_PROMPT + LOCAL_JSON_RULES, prompt,
                                    schema_with_scene_count(_Scenes, len(scenes), len(scenes)))
            rewritten = dedupe_scenes(_Scenes.model_validate(data).scenes)[:len(scenes)]
            # Só aceita se manteve as cenas e ficou mais perto do alvo
            if len(rewritten) < len(scenes) or abs(count_words(rewritten) - target) >= abs(current - target):
                break
            scenes = rewritten
        return scenes

    def _write_in_parts(self, req: VideoRequest) -> VideoScript:
        vertical = settings.presets()["platforms"][req.platform]["orientation"] == "vertical"
        n_parts = max(2, math.ceil(req.duration_seconds / self.seconds_per_part))
        total_words = target_words(req)
        total_scenes = scenes_for(req)

        self.log(f"Modelo local: planejando o roteiro em {n_parts} partes…")
        plan_prompt = (
            build_user_prompt(req)
            + f"\n\nNESTA ETAPA não escreva a narração. Gere os metadados e um esboço com exatamente {n_parts} "
            "partes em sequência (gancho → desenvolvimento com revelações crescentes → clímax → desfecho)."
        )
        plan = _Plan.model_validate(ollama.chat_json(SYSTEM_PROMPT + LOCAL_JSON_RULES, plan_prompt,
                                                     ollama.inline_schema(_Plan.model_json_schema())))
        parts = plan.parts[:n_parts] or [_Part(summary=plan.title)]
        outline = "\n".join(f"{i + 1}. {p.summary}" for i, p in enumerate(parts))

        scenes: List[Scene] = []
        for i, part in enumerate(parts):
            self.log(f"Modelo local: escrevendo parte {i + 1}/{len(parts)}…")
            words = round(total_words / len(parts))
            n_scenes = max(2, round(total_scenes / len(parts)))
            previous = " ".join(s.narration for s in scenes[-2:]) or "(início do vídeo)"
            position = (
                "Esta é a PRIMEIRA parte: comece com o gancho mais forte do vídeo, sem saudações."
                if i == 0 else
                ("Esta é a ÚLTIMA parte: entregue o desfecho" + (" e termine com um CTA curto." if req.cta else "."))
                if i == len(parts) - 1 else
                "Parte do meio: NÃO conclua a história; termine com uma frase que puxe para a próxima parte."
            )
            prompt = "\n".join([
                build_user_prompt(req),
                "",
                f"TÍTULO DEFINIDO: {plan.title}",
                f"ESBOÇO COMPLETO:\n{outline}",
                "",
                f"AGORA escreva apenas a parte {i + 1}: {part.summary}",
                position,
                f"Tamanho desta parte: cerca de {words} palavras de narração, divididas em {n_scenes} cenas.",
                f"Final da narração anterior (continue a partir daqui, sem repetir): {previous}",
            ])
            chunk = _Scenes.model_validate(ollama.chat_json(SYSTEM_PROMPT + LOCAL_JSON_RULES, prompt,
                                                            schema_with_scene_count(_Scenes, n_scenes, n_scenes + 1)))
            scenes += self._fit_length(dedupe_scenes(chunk.scenes), words, req)

        if not scenes:
            raise RuntimeError("O modelo local não gerou nenhuma cena.")
        return VideoScript(title=plan.title, visual_subject=plan.visual_subject,
                           description=plan.description, tags=plan.tags,
                           hashtags=plan.hashtags, thumbnail_text=plan.thumbnail_text, scenes=scenes)


def revise_prompt(scenes: List[Scene], instruction: str, req: VideoRequest, words: Optional[int] = None) -> str:
    numbered = "\n".join(f"{i + 1}. {s.narration}" for i, s in enumerate(scenes))
    words = words or max(count_words(scenes), target_words(req))
    return (
        f"{instruction}\n\nMantenha o idioma ({LANG_NAMES[req.language]}), o tom e a ordem. O TOTAL deve ficar entre "
        f"{round(words * 0.9)} e {round(words * 1.1)} palavras. As visual_queries continuam em inglês, concretas e filmáveis."
        f"\n\nCENAS ATUAIS:\n{numbered}"
    )


def count_words(scenes: List[Scene]) -> int:
    return sum(len(s.narration.split()) for s in scenes)


# Emojis e pictogramas: a voz sintética lê ou engasga com eles
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002B00-\U00002BFF️‍]+"
)


def strip_emoji(text: str) -> str:
    return re.sub(r"\s+", " ", _EMOJI.sub("", text)).strip()


def strip_emoji_keep_lines(text: str) -> str:
    """Como strip_emoji, mas preserva quebras de linha (legendas do Instagram usam parágrafos)."""
    return "\n".join(re.sub(r"[ \t]+", " ", _EMOJI.sub("", line)).strip() for line in text.splitlines())


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


def dedupe_scenes(scenes: List[Scene]) -> List[Scene]:
    """Remove cenas repetidas: iguais a outra, ou quase inteiramente contidas na cena anterior
    (modelos pequenos repetem o CTA ou reescrevem o gancho na cena seguinte)."""
    seen, out = set(), []
    for s in scenes:
        key = _norm(s.narration)
        if not key or key in seen:
            continue
        if out:
            words, prev = key.split(), set(_norm(out[-1].narration).split())
            if len(words) >= 4 and sum(w in prev for w in words) / len(words) >= 0.8:
                continue
        seen.add(key)
        out.append(s)
    return out


def fix_visual_subject(subject: str, scenes: List[Scene]) -> str:
    """O assunto visual precisa ser buscável em inglês: sem nomes próprios nem acentos.
    Se vier fora disso (ex.: "navio Mary Celeste"), usa a 1ª busca da 1ª cena."""
    subject = core_phrase(subject)
    words = subject.split()
    has_name = any(w[:1].isupper() for w in words[1:])
    # Precisa estar em inglês: sinal simples é aparecer em alguma busca visual (que são em inglês)
    query_words = {w.lower() for s in scenes for q in s.visual_queries for w in q.split()}
    in_english = not query_words or any(w.lower() in query_words for w in words)
    if subject and subject.isascii() and not has_name and in_english:
        return subject
    for s in scenes:
        for q in s.visual_queries:
            if q.isascii() and not any(w[:1].isupper() for w in q.split()[1:]):
                return q
    return subject


def clean_script(script: VideoScript, req: VideoRequest) -> VideoScript:
    scenes = []
    for s in dedupe_scenes(script.scenes):
        narration = strip_emoji(s.narration)
        if not narration:
            continue
        queries = [q.strip() for q in s.visual_queries if q and q.strip()][:3] or ["dark cinematic night"]
        scenes.append(s.model_copy(update={"narration": narration, "visual_queries": queries}))

    hashtags: List[str] = []
    for h in script.hashtags:
        h = re.sub(r"\s+", "", h.strip())
        h = h if h.startswith("#") else f"#{h}"
        if len(h) > 1 and h.lower() not in {x.lower() for x in hashtags}:
            hashtags.append(h)
    if req.platform == "shorts" and "#shorts" not in {h.lower() for h in hashtags}:
        hashtags.insert(0, "#Shorts")
    max_hashtags = int(settings.presets()["platforms"].get(req.platform, {}).get("max_hashtags", 6))
    # Modelos às vezes colocam as hashtags dentro da descrição; elas já vão no fim do post
    description = re.sub(r"(?<!\w)#[\wÀ-ÿ]+", "", strip_emoji_keep_lines(script.description))
    description = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", description)).strip()

    tags = [t.strip().lstrip("#") for t in script.tags if t.strip()][:15]
    return script.model_copy(update={
        "scenes": scenes, "hashtags": hashtags[:max_hashtags], "tags": tags,
        "visual_subject": fix_visual_subject(strip_emoji(script.visual_subject), scenes),
        "description": description,
        "title": strip_emoji(script.title)[:100],
        "thumbnail_text": strip_emoji(script.thumbnail_text),
    })
