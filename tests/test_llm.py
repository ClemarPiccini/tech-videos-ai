"""Seleção de motor de IA, modelo local em partes e fallback — sem rede."""
import pytest

from app import settings
from app.models import Scene, VideoRequest, VideoScript
from app.pipeline import ollama, script


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "LLM_PROVIDER", "OLLAMA_MODEL"):
        monkeypatch.delenv(k, raising=False)


def scene(text):
    return {"narration": text, "visual_queries": ["dark forest"]}


def test_resolve_provider(monkeypatch):
    assert script.resolve_provider() == "ollama"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert script.resolve_provider() == "anthropic"
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert script.resolve_provider() == "ollama"
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")
    assert script.provider_label() == "Local (llama3.1:8b)"


def test_set_env_preserves_comments(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# comentário\nA=1\nB=2\n")
    monkeypatch.delenv("A", raising=False)
    monkeypatch.delenv("C", raising=False)
    settings.set_env({"A": "novo", "C": "3"}, f)
    assert f.read_text() == "# comentário\nA=novo\nB=2\nC=3\n"
    assert settings.env("A") == "novo"


def test_inline_schema_resolves_refs():
    schema = ollama.inline_schema(VideoScript.model_json_schema())
    assert "$defs" not in str(schema) and "$ref" not in str(schema)
    assert schema["properties"]["scenes"]["items"]["properties"]["narration"]["type"] == "string"
    # Regressão: o campo "title" não pode ser confundido com o metadado "title" do Pydantic
    assert schema["properties"]["title"] == {"type": "string"}
    assert set(schema["required"]) == set(schema["properties"])
    assert "title" not in schema  # metadado removido
    plan = ollama.inline_schema(script._Plan.model_json_schema())
    assert "title" in plan["properties"] and "title" in plan["required"]


def test_has_model():
    assert ollama.has_model(["qwen2.5:7b", "mistral:latest"], "qwen2.5:7b")
    assert ollama.has_model(["mistral:latest"], "mistral")
    assert not ollama.has_model(["qwen2.5:14b"], "qwen2.5:7b")


def _fake_local(monkeypatch, responder):
    monkeypatch.setattr(ollama, "list_models", lambda: ["qwen2.5:7b"])
    calls = []

    def fake_chat(system, user, schema, model=None):
        calls.append({"user": user, "schema": schema})
        return responder(user, schema)

    monkeypatch.setattr(ollama, "chat_json", fake_chat)
    return calls


META = {"title": "T", "visual_subject": "old ship", "description": "D", "tags": ["a"], "hashtags": ["#x"], "thumbnail_text": "NÃO"}


def words(n, prefix="palavra"):
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_local_single_pass_for_short_videos(monkeypatch):
    calls = _fake_local(monkeypatch, lambda u, s: {**META, "scenes": [scene(words(70, "a")), scene(words(70, "b"))]})
    out = script.ScriptGenerator().generate(VideoRequest(platform="shorts", duration_seconds=60))
    assert len(calls) == 1  # 140 palavras >= 75% de 144: sem expansão
    assert len(out.scenes) == 2


def test_local_expands_short_script(monkeypatch):
    def responder(user, schema):
        if "Reescreva" in user:
            assert "1. curto demais" in user
            return {"scenes": [scene(words(60, "a")), scene(words(60, "b"))]}
        return {**META, "scenes": [scene("curto demais 🤔"), scene("também 📝")]}

    calls = _fake_local(monkeypatch, responder)
    logs = []
    out = script.ScriptGenerator(log=logs.append).generate(VideoRequest(platform="shorts", duration_seconds=60))
    assert len(calls) == 2
    assert script.count_words(out.scenes) == 120
    assert any("expandindo" in m for m in logs)


def test_expansion_stops_when_model_does_not_improve(monkeypatch):
    calls = _fake_local(monkeypatch, lambda u, s: {**META, "scenes": [scene("curto")]} if "Reescreva" not in u
                        else {"scenes": [scene("ainda curto")]})
    out = script.ScriptGenerator().generate(VideoRequest(platform="shorts", duration_seconds=60))
    assert len(calls) == 3  # original + até 2 expansões
    assert out.scenes[0].narration == "ainda curto"


def test_expansion_schema_locks_scene_count_and_rejects_padding(monkeypatch):
    def responder(user, schema):
        if "Reescreva" in user:
            assert schema["properties"]["scenes"]["minItems"] == 2 == schema["properties"]["scenes"]["maxItems"]
            # modelo tenta "inflar" repetindo a mesma cena
            return {"scenes": [scene(words(60)), scene(words(60))]}
        assert schema["properties"]["scenes"]["minItems"] == 10  # scene_count(60, vertical)
        return {**META, "scenes": [scene("curto"), scene("outro")]}

    calls = _fake_local(monkeypatch, responder)
    out = script.ScriptGenerator().generate(VideoRequest(platform="shorts", duration_seconds=60))
    # As duas cenas expandidas são idênticas -> deduplicadas para 1 < 2 -> expansão rejeitada
    assert len(calls) == 2
    assert [s.narration for s in out.scenes] == ["curto", "outro"]


def test_dedupe_scenes():
    s = [Scene(narration=t, visual_queries=["x"]) for t in ["Inscreva-se!", "Algo", "inscreva-se", "Algo."]]
    assert [x.narration for x in script.dedupe_scenes(s)] == ["Inscreva-se!", "Algo"]


def test_strip_emoji_everywhere():
    s = VideoScript(title="Mistério 🔥 total", visual_subject="ship", description="d", tags=[], hashtags=[], thumbnail_text="NÃO 👀",
                    scenes=[Scene(narration="Onde estão todos? 🤔  Ninguém sabe. 📝", visual_queries=["sea"])])
    out = script.clean_script(s, VideoRequest())
    assert out.title == "Mistério total"
    assert out.thumbnail_text == "NÃO"
    assert out.scenes[0].narration == "Onde estão todos? Ninguém sabe."


def test_local_long_video_written_in_parts(monkeypatch):
    def responder(user, schema):
        if "parts" in schema["properties"]:
            return {**META, "parts": [{"summary": f"p{i}"} for i in range(10)]}
        part = user.split("AGORA escreva apenas a parte ")[1].split(":")[0]
        return {"scenes": [scene(f"parte {part} a " + words(80, "x")), scene(f"parte {part} b " + words(80, "y"))]}

    calls = _fake_local(monkeypatch, responder)
    logs = []
    out = script.ScriptGenerator(log=logs.append).generate(VideoRequest(platform="youtube", duration_seconds=480))
    n_parts = 6  # ceil(480 / 90)
    assert len(calls) == 1 + n_parts  # esboço + uma chamada por parte (esboço extra é descartado)
    assert out.title == "T"
    assert out.scenes[0].narration.startswith("parte 1 a")
    assert out.scenes[-1].narration.startswith(f"parte {n_parts} b")
    assert "PRIMEIRA parte" in calls[1]["user"]
    assert "ÚLTIMA parte" in calls[-1]["user"]
    assert "NÃO conclua" in calls[2]["user"]
    assert "parte 1 b" in calls[2]["user"]  # contexto da parte anterior
    assert any("6 partes" in m for m in logs)


def test_auto_falls_back_to_local_when_claude_has_no_credit(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    def no_credit(self, req):
        raise script.ProviderUnavailable("Conta da Anthropic sem créditos.")

    monkeypatch.setattr(script.AnthropicWriter, "write", no_credit)
    _fake_local(monkeypatch, lambda u, s: {**META, "scenes": [scene("local")]})
    logs = []
    out = script.ScriptGenerator(log=logs.append).generate(VideoRequest(platform="shorts", duration_seconds=30))
    assert out.scenes[0].narration == "local"
    assert "sem créditos" in logs[0]


def test_explicit_claude_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(script.AnthropicWriter, "write",
                        lambda self, req: (_ for _ in ()).throw(script.ProviderUnavailable("sem créditos")))
    _fake_local(monkeypatch, lambda u, s: {**META, "scenes": [scene("local")]})
    with pytest.raises(script.ProviderUnavailable):
        script.ScriptGenerator().generate(VideoRequest(platform="shorts", duration_seconds=30))


def test_no_ai_available_message(monkeypatch):
    monkeypatch.setattr(ollama, "list_models", lambda: None)
    with pytest.raises(RuntimeError, match="ollama.com/download"):
        script.ScriptGenerator().generate(VideoRequest(platform="shorts", duration_seconds=30))
