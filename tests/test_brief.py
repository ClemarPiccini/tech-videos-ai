"""Roteiro guiado, com o briefing real do Mary Celeste."""
import pytest

from app.models import Brief, Scene, VideoRequest
from app.pipeline import ollama, script
from app.pipeline.brief import (enforce_hook_and_ending, fact_covered, missing_facts, parse_brief,
                                recommended_seconds)

MARY_CELESTE = """TEMA: O navio Mary Celeste, encontrado à deriva no Atlântico em dezembro de 1872.
GANCHO: "Em 1872, um navio foi encontrado navegando sozinho no meio do oceano. Não havia ninguém a bordo."
FATOS OBRIGATÓRIOS:
- 10 pessoas a bordo, incluindo o capitão, a esposa e a filha de 2 anos
- Comida e água para 6 meses intactas
- A carga de álcool estava quase toda lá; só 9 barris estavam vazios
- O único bote salva-vidas tinha sumido
VIRADA: Não havia sinal de luta, roubo ou tempestade. Os pertences pessoais continuavam lá.
FINAL: Terminar com a pergunta: "O que faria 10 pessoas abandonarem um navio perfeitamente seguro?"
"""


def test_parse_real_brief():
    b = parse_brief(MARY_CELESTE)
    assert b.topic.startswith("O navio Mary Celeste")
    assert b.hook == "Em 1872, um navio foi encontrado navegando sozinho no meio do oceano. Não havia ninguém a bordo."
    assert len(b.facts) == 4 and b.facts[3] == "O único bote salva-vidas tinha sumido"
    assert b.twist.startswith("Não havia sinal de luta")
    assert b.ending == "O que faria 10 pessoas abandonarem um navio perfeitamente seguro?"  # só o trecho entre aspas


def test_parse_ignores_plain_ideas():
    assert parse_brief("O navio encontrado à deriva sem nenhum tripulante") is None


def test_recommended_duration_for_real_brief():
    # ~84 palavras * 1,3 / 2,05 + 7 pausas -> não cabe em 30 s
    assert recommended_seconds(parse_brief(MARY_CELESTE)) in (55, 60)


@pytest.mark.parametrize("narration,expected", [
    ("Havia 10 pessoas no navio: o capitão, sua esposa e a filha de apenas 2 anos.", True),
    ("Havia dez pessoas a bordo, entre elas o capitão, a esposa e a filha de dois anos.", True),  # por extenso
    ("Havia 8 pessoas a bordo, incluindo o capitão, a esposa e a filha de 2 anos.", False),  # número errado
    ("O capitão estava lá.", False),
])
def test_fact_coverage(narration, expected):
    assert fact_covered("10 pessoas a bordo, incluindo o capitão, a esposa e a filha de 2 anos", narration) is expected


def S(t):
    return Scene(narration=t, visual_queries=["old ship"])


def test_enforce_hook_replaces_paraphrase_and_ending_cuts_cta():
    b = parse_brief(MARY_CELESTE)
    scenes = [
        S("Um navio fantasma foi achado em 1872. O convés estava em silêncio."),
        S("O que faria 10 pessoas abandonarem um navio perfeitamente seguro? Siga o perfil para mais!"),
    ]
    out = enforce_hook_and_ending(scenes, b)
    assert out[0].narration == b.hook + " O convés estava em silêncio."
    assert out[-1].narration == b.ending


def test_enforce_appends_missing_ending():
    b = Brief(ending="E você, o que acha?")
    assert enforce_hook_and_ending([S("Ninguém sabe.")], b)[0].narration == "Ninguém sabe. E você, o que acha?"


def test_local_guided_uses_fixed_slots_and_repairs_forgotten_fact(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(ollama, "list_models", lambda: ["qwen2.5:7b"])
    b = parse_brief(MARY_CELESTE)
    prompts = []

    def fake_chat(system, user, schema, model=None):
        prompts.append((user, schema))
        # 7 cenas fixas; o modelo "esquece" os barris na cena 4 e acrescenta um CTA no fim
        texts = [
            b.hook + " Ninguém sabia o que tinha acontecido ali, e o silêncio pesava no convés.",
            "Eram 10 pessoas a bordo, incluindo o capitão, a esposa e a filha de 2 anos, e todos tinham sumido.",
            "Na cozinha, comida e água para 6 meses intactas, como se alguém fosse voltar para o jantar.",
            "No porão, a carga parecia em ordem, e o cheiro de madeira molhada tomava conta de tudo.",
            "O único bote salva-vidas tinha sumido, deixando apenas as cordas soltas balançando.",
            "Não havia sinal de luta, roubo ou tempestade. Os pertences pessoais continuavam lá, intocados.",
            "Tudo estava no lugar, menos as pessoas. " + b.ending + " Siga para mais!",
        ]
        words = sum(len(x.split()) for x in texts)
        return {"title": "Mary Celeste", "visual_subject": "old sailing ship", "description": "d", "tags": [],
                "hashtags": [], "thumbnail_text": "NINGUÉM A BORDO",
                "scenes": [{"narration": x, "visual_queries": ["old sailing ship"]} for x in texts]} \
            if "ESCREVA EXATAMENTE" in user else {"scenes": []}

    monkeypatch.setattr(ollama, "chat_json", fake_chat)
    logs = []
    req = VideoRequest(prompt=MARY_CELESTE, platform="reels", duration_seconds=55)
    out = script.ScriptGenerator(log=logs.append).generate(req)

    user, schema = prompts[0]
    assert "ESCREVA EXATAMENTE 7 CENAS" in user
    assert schema["properties"]["scenes"]["minItems"] == 7 == schema["properties"]["scenes"]["maxItems"]
    assert "4. FATO — apresente APENAS este fato" in user and "9 barris" in user
    assert len(out.scenes) == 7
    assert out.scenes[3].narration.startswith("A carga de álcool estava quase toda lá; só 9 barris estavam vazios.")
    assert missing_facts(b, out.scenes) == []
    assert out.scenes[0].narration.startswith(b.hook)
    assert out.scenes[-1].narration.endswith("perfeitamente seguro?")  # CTA depois do final foi cortado


def test_brief_api(monkeypatch):
    from fastapi.testclient import TestClient

    from app.server import app

    c = TestClient(app)
    r = c.post("/api/brief", json={"text": MARY_CELESTE}).json()
    assert len(r["brief"]["facts"]) == 4 and r["recommended_seconds"] >= 45
    assert c.post("/api/brief", json={"text": "só uma ideia"}).json()["brief"] is None


def test_dedupe_drops_scene_that_repeats_previous():
    scenes = [S("Em 1872, um navio foi achado. Não havia ninguém a bordo. Onde estavam as 10 pessoas?"),
              S("Não havia ninguém a bordo. Onde estavam 10 pessoas?"),
              S("A comida estava intacta.")]
    assert [s.narration[:10] for s in script.dedupe_scenes(scenes)] == ["Em 1872, u", "A comida e"]


def test_fix_visual_subject():
    scenes = [Scene(narration="x", visual_queries=["old sailing ship", "empty deck"])]
    assert script.fix_visual_subject("navio Mary Celeste", scenes) == "old sailing ship"
    assert script.fix_visual_subject("navio à deriva", scenes) == "old sailing ship"
    hospital = [Scene(narration="x", visual_queries=["abandoned hospital corridor"])]
    assert script.fix_visual_subject("abandoned hospital", hospital) == "abandoned hospital"
    # em português, mesmo sem acento, não aparece nas buscas (que são em inglês) -> trocado
    assert script.fix_visual_subject("navio desaparecido", scenes) == "old sailing ship"


def test_insert_missing_fact_before_twist():
    from app.pipeline.brief import insert_missing_facts

    b = parse_brief(MARY_CELESTE)
    scenes = [S(b.hook), S("Eram 10 pessoas a bordo, incluindo o capitão, a esposa e a filha de 2 anos."),
              S("Comida e água para 6 meses intactas."), S("O único bote salva-vidas tinha sumido."),
              S("Não havia sinal de luta, roubo ou tempestade."), S(b.ending)]
    out = insert_missing_facts(scenes, b)
    assert out[4].narration == "A carga de álcool estava quase toda lá; só 9 barris estavam vazios."
    assert out[5].narration.startswith("Não havia sinal de luta")
    assert missing_facts(b, out) == []


def test_core_phrase_and_subject():
    from app.pipeline.visuals import core_phrase, head_noun

    assert core_phrase("abandoned ship in the middle of the ocean") == "abandoned ship"
    assert head_noun("abandoned ship in the middle of the ocean") == "ship"
    assert script.fix_visual_subject("abandoned ship in the middle of the ocean", []) == "abandoned ship"


def test_guided_expansion_keeps_facts(monkeypatch):
    b = parse_brief(MARY_CELESTE)
    req = VideoRequest(platform="reels", duration_seconds=55, brief=b)
    short = [S(b.hook)] + [S(f) for f in b.facts] + [S(b.twist), S(b.ending)]

    class W:
        def __init__(self, result):
            self.result, self.calls = result, 0

        def revise(self, scenes, instruction, req, exact=False):
            self.calls += 1
            assert exact
            assert "NÃO acrescente fatos" in instruction
            return self.result

    padded = [S(s.narration + " O silêncio do convés era absoluto, e o vento soprava sem parar.") for s in short]
    w = W(padded)
    out = script.ScriptGenerator()._expand_guided(short, req, w)
    assert out == padded and missing_facts(b, out) == []

    # Expansão que perde um fato obrigatório é rejeitada
    w2 = W([S("Texto longo " * 20)] * 3)
    assert script.ScriptGenerator()._expand_guided(short, req, w2) == short


def test_claude_path_with_brief(monkeypatch):
    """Caminho do Claude (SDK simulado): roteiro livre com o briefing, correção de fato via Claude,
    gancho/final garantidos. Nenhuma chamada de rede."""
    from types import SimpleNamespace

    from app.models import VideoScript

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    b = parse_brief(MARY_CELESTE)
    calls = []

    def scenes(texts):
        return [Scene(narration=t, visual_queries=["old sailing ship"]) for t in texts]

    first = VideoScript(
        title="O navio sem ninguém", visual_subject="old sailing ship", description="Legenda", tags=["navio"],
        hashtags=["#misterio"], thumbnail_text="NINGUÉM A BORDO",
        scenes=scenes([b.hook, "Eram 10 pessoas, incluindo o capitão, a esposa e a filha de 2 anos.",
                       "Comida e água para 6 meses intactas.", "O único bote salva-vidas tinha sumido.",
                       b.twist, b.ending]),  # esqueceu os 9 barris
    )
    fixed = first.scenes[:3] + scenes(["A carga de álcool estava quase toda lá; só 9 barris estavam vazios."]) \
        + first.scenes[3:]

    def fake_parse(**kw):
        calls.append(kw)
        assert kw["model"] == "claude-sonnet-5-5" and kw["fallbacks"] == "default"
        if kw["output_format"] is VideoScript:
            assert "ROTEIRO GUIADO" in kw["messages"][0]["content"]
            return SimpleNamespace(stop_reason="end_turn", parsed_output=first)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=SimpleNamespace(scenes=fixed))

    fake_client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=fake_parse)))
    monkeypatch.setattr(script.anthropic, "Anthropic", lambda **kw: fake_client)

    logs = []
    out = script.ScriptGenerator(log=logs.append).generate(
        VideoRequest(prompt=MARY_CELESTE, platform="reels", duration_seconds=55))
    assert missing_facts(b, out.scenes) == []
    assert out.scenes[0].narration.startswith(b.hook) and out.scenes[-1].narration.endswith("seguro?")
    assert any("1 fato(s) faltando" in m for m in logs)
    assert len(calls) >= 2  # roteiro + correção (+ possível expansão), tudo pelo Claude
