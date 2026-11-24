"""Duração, relevância das imagens e formato do post para Instagram."""
from pathlib import Path

import pytest

from app.models import Scene, SceneAudio, VideoRequest, VideoScript, Word
from app.pipeline import ffmpeg
from app.pipeline.runner import post_text
from app.pipeline.script import build_user_prompt, clean_script, target_words
from app.pipeline.tts import speed_up
from app.pipeline.visuals import concrete_query, rank, relevance


def test_target_words_discounts_pauses():
    # Reels 30 s: 5 cenas * 0,25 s de pausa -> 28,75 s * 2,05 palavras/s
    assert target_words(VideoRequest(platform="reels", duration_seconds=30)) == 59


def test_concrete_query_drops_abstract_terms():
    assert concrete_query("mysterious incident") == ""
    assert concrete_query("1920") == ""
    assert concrete_query("subscribe now") == ""
    assert concrete_query("growing theories") == ""
    assert concrete_query("abandoned ship mystery") == "abandoned ship"
    assert concrete_query("foggy sea") == "foggy sea"


def test_relevance_and_rank_filter_unrelated_results():
    hits = [
        {"id": 1, "tags": "woman, fashion, hat", "duration": 30},
        {"id": 2, "tags": "sea, waves, ocean", "duration": 5},
        {"id": 3, "tags": "ship, boat, sea", "duration": 30},
    ]
    assert relevance("abandoned ship", "ship, boat") == 1
    assert relevance("ships at sea", "ship, sea") == 2  # plural reduzido
    ranked = rank(hits, "ship at sea", lambda h: h["tags"], lambda h: h["duration"], 10)
    # mulher de chapéu e ondas sem navio descartadas: o núcleo da busca é "ship"
    assert [h["id"] for h in ranked] == [3]


def test_reels_prompt_rules():
    text = build_user_prompt(VideoRequest(platform="reels", duration_seconds=30))
    assert "Instagram Reels" in text
    assert "no máximo 5" in text
    assert "nunca diga 'inscreva-se'" in text


def test_reels_hashtags_capped_at_five():
    s = VideoScript(title="T", visual_subject="ship", description="Legenda", tags=[], thumbnail_text="X",
                    hashtags=["#a", "#b", "#A", "#c", "#d", "#e", "#f"],
                    scenes=[Scene(narration="oi", visual_queries=["ship"])])
    out = clean_script(s, VideoRequest(platform="reels"))
    assert out.hashtags == ["#a", "#b", "#c", "#d", "#e"]


def test_post_text_has_no_title_for_instagram():
    s = VideoScript(title="Título", visual_subject="ship", description="Gancho\nMais texto", tags=[],
                    hashtags=["#a", "#b"], thumbnail_text="X", scenes=[])
    assert post_text(s, "reels") == "Gancho\nMais texto\n\n#a #b\n"
    assert post_text(s, "youtube").startswith("Título\n\n")


@pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg não instalado")
def test_speed_up_shortens_audio_and_rescales_words(tmp_path):
    wav = tmp_path / "a.wav"
    ffmpeg.run(["-f", "lavfi", "-i", "sine=frequency=300:duration=6", "-ar", "44100", "-ac", "1", wav])
    audio = SceneAudio(path=str(wav), duration=6.0, words=[Word(text="x", start=3.0, end=4.2)])
    fast = speed_up(audio, 1.2, tmp_path)
    assert abs(fast.duration - 5.0) < 0.05
    assert abs(fast.words[0].start - 2.5) < 1e-6 and abs(fast.words[0].end - 3.5) < 1e-6
    assert speed_up(audio, 1.0, tmp_path) is audio


def test_adjective_only_match_is_rejected():
    # Caso real: "empty decks" trouxe a foto de um cachorro com a tag "empty"
    assert relevance("empty decks", "dog, empty, sad, animal") == 0
    assert relevance("empty decks", "ship, deck, wood") == 1
    assert relevance("old sailing ship", "old, sailing, boat") == 2  # 2 palavras em comum já basta


def test_hashtags_removed_from_caption_body():
    s = VideoScript(title="T", visual_subject="ship", tags=[], thumbnail_text="X", scenes=[],
                    description="Gancho forte 🔥\n\nTexto do meio.\n\n#misterio #navio",
                    hashtags=["#misterio", "#navio"])
    out = clean_script(s, VideoRequest(platform="reels"))
    assert out.description == "Gancho forte\n\nTexto do meio."
    assert post_text(out, "reels").count("#navio") == 1


def _finder(monkeypatch, tmp_path):
    from app import settings
    from app.pipeline.visuals import VisualFinder

    cfg = dict(settings.config())
    cfg["paths"] = {**cfg["paths"], "cache": str(tmp_path)}
    monkeypatch.setattr(settings, "config", lambda: cfg)
    return VisualFinder("vertical", (1080, 1920))


def test_find_tries_scene_plus_subject_first(monkeypatch, tmp_path):
    from app.pipeline.visuals import Visual

    finder = _finder(monkeypatch, tmp_path)
    tried = []

    def fake_find_one(q, d):
        tried.append((q, finder.strict))
        return Visual(path=tmp_path / "x.mp4", kind="video") if q == "abandoned hospital" else None

    monkeypatch.setattr(finder, "_find_one", fake_find_one)
    v = finder.find("dimly lit room", 3, subject="abandoned hospital", fallback_query="dark corridor")
    assert v.kind == "video"
    assert [q for q, _ in tried] == ["dimly lit room hospital", "dimly lit room", "abandoned hospital"]
    assert all(strict for _, strict in tried)


def test_find_relaxes_mood_filter_before_placeholder(monkeypatch, tmp_path):
    from app.pipeline.visuals import Visual

    finder = _finder(monkeypatch, tmp_path)
    tried = []

    def fake_find_one(q, d):
        tried.append((q, finder.strict))
        return Visual(path=tmp_path / "x.mp4", kind="video") if not finder.strict else None

    monkeypatch.setattr(finder, "_find_one", fake_find_one)
    v = finder.find("ship deck", 3, subject="old ship")
    assert v.kind == "video"
    assert tried == [("ship deck", True), ("old ship", True), ("ship deck", False)]
    assert finder.strict is True  # volta ao modo estrito para a próxima cena


def test_brightness_of(monkeypatch):
    import io as _io

    from PIL import Image as _Image

    from app.pipeline import visuals

    def png(color):
        buf = _io.BytesIO()
        _Image.new("RGB", (10, 10), color).save(buf, "PNG")
        return buf.getvalue()

    class Resp:
        def __init__(self, content):
            self.status_code, self.content = 200, content

    class Sess:
        def get(self, url, timeout):
            return Resp(png((255, 255, 255) if "white" in url else (20, 20, 20)))

    assert visuals.brightness_of(Sess(), "http://x/white.png") > 0.95
    assert visuals.brightness_of(Sess(), "http://x/dark.png") < 0.1
