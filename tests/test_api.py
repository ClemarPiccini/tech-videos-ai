import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import settings

    cfg = dict(settings.config())
    cfg["paths"] = {**cfg["paths"], "output": str(tmp_path)}
    monkeypatch.setattr(settings, "config", lambda: cfg)
    import importlib

    import app.server as server

    importlib.reload(server)
    return TestClient(server.app), server


def test_index_and_presets(client):
    c, _ = client
    assert "Dark Video Studio" in c.get("/").text
    p = c.get("/api/presets").json()
    assert {"youtube", "shorts", "tiktok", "reels"} <= set(p["platforms"])
    assert c.get("/static/app.js").status_code == 200
    assert "ffmpeg" in c.get("/api/health").json()


def test_rejects_too_long_short(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    r = c.post("/api/jobs", json={"platform": "shorts", "duration_seconds": 600})
    assert r.status_code == 400
    assert "180" in r.json()["detail"]


def test_requires_some_ai(client, monkeypatch):
    c, _ = client
    from app.pipeline import ollama

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr(ollama, "list_models", lambda: None)
    r = c.post("/api/jobs", json={"platform": "youtube", "duration_seconds": 300})
    assert r.status_code == 400
    assert "Ollama" in r.json()["detail"]

    monkeypatch.setattr(ollama, "list_models", lambda: [])
    r = c.post("/api/jobs", json={"platform": "youtube", "duration_seconds": 300})
    assert "Baixe o modelo" in r.json()["detail"]


def test_settings_saves_to_env_file(client, monkeypatch, tmp_path):
    c, _ = client
    from app import settings
    from app.pipeline import ollama

    env_file = tmp_path / ".env"
    monkeypatch.setattr(settings, "ENV_FILE", env_file)
    monkeypatch.setattr(ollama, "list_models", lambda: None)
    for k in ("ANTHROPIC_API_KEY", "PIXABAY_API_KEY", "LLM_PROVIDER", "OLLAMA_MODEL"):
        monkeypatch.setenv(k, "")

    s = c.post("/api/settings", json={
        "llm_provider": "ollama", "ollama_model": "qwen2.5:14b",
        "keys": {"ANTHROPIC_API_KEY": "sk-ant-secret-1234", "PIXABAY_API_KEY": ""},
    }).json()
    assert s["llm_provider"] == "ollama" and s["ollama_model"] == "qwen2.5:14b"
    assert s["keys"]["ANTHROPIC_API_KEY"] == "••••1234"  # nunca devolve a chave inteira
    assert s["keys"]["PIXABAY_API_KEY"] == ""
    text = env_file.read_text()
    assert "ANTHROPIC_API_KEY=sk-ant-secret-1234" in text and "PIXABAY_API_KEY" not in text

    s = c.post("/api/settings", json={"clear_keys": ["ANTHROPIC_API_KEY"]}).json()
    assert s["keys"]["ANTHROPIC_API_KEY"] == ""
    assert c.post("/api/settings", json={"keys": {"HACK": "x"}}).status_code == 400


def test_job_lifecycle_with_fake_pipeline(client, monkeypatch):
    c, server = client
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    def fake_pipeline(req, job_dir, progress):
        progress(50, "metade")
        (job_dir / "video.mp4").write_bytes(b"fake")
        (job_dir / "metadata.json").write_text('{"title": "T", "description": "D", "tags": [], "hashtags": []}')
        return {"title": "T"}

    import app.pipeline.runner as runner

    monkeypatch.setattr(runner, "run_pipeline", fake_pipeline)
    job = c.post("/api/jobs", json={"prompt": "teste", "platform": "tiktok", "duration_seconds": 45}).json()
    server.manager.render_pool.shutdown(wait=True)

    data = c.get(f"/api/jobs/{job['id']}").json()
    assert data["status"] == "done", data
    assert data["metadata"]["title"] == "T"
    assert c.get(f"/api/jobs/{job['id']}/video").content == b"fake"
    assert c.get(f"/api/jobs/{job['id']}/thumbnail").status_code == 404
    assert [j["id"] for j in c.get("/api/jobs").json()] == [job["id"]]
