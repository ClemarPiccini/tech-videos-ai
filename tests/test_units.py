from app.models import Scene, VideoRequest, VideoScript, Word
from app.pipeline.captions import caption_states, chunk_words
from app.pipeline.render import plan_segments
from app.pipeline.runner import slugify
from app.pipeline.script import build_user_prompt, clean_script, scene_count
from app.pipeline.tts import estimate_words, words_from_chars


def test_plan_segments_has_no_drift():
    durations = [3.37, 7.91, 12.05, 2.2]
    plan = plan_segments(durations, [3, 3, 2, 1], fps=30, min_clip=2.5)
    assert sum(sum(p) for p in plan) == round(sum(durations) * 30)
    assert len(plan[0]) == 1  # 3.37s não comporta 2 clipes de 2.5s
    assert len(plan[1]) == 3
    assert all(f > 0 for p in plan for f in p)


def test_words_from_chars_groups_on_spaces():
    chars = list("Oi mundo")
    starts = [i * 0.1 for i in range(len(chars))]
    ends = [s + 0.1 for s in starts]
    words = words_from_chars(chars, starts, ends)
    assert [w.text for w in words] == ["Oi", "mundo"]
    assert words[1].start == starts[3]
    assert abs(words[1].end - ends[-1]) < 1e-9


def test_estimate_words_covers_total():
    words = estimate_words("um dois três quatro", 4.0)
    assert len(words) == 4
    assert words[0].start == 0
    assert abs(words[-1].end - 4.0) < 1e-6


def _words(texts, step=0.3):
    return [Word(text=t, start=i * step, end=i * step + step * 0.9) for i, t in enumerate(texts)]


def test_chunk_words_breaks_on_size_punctuation_and_gap():
    words = _words(["a", "b.", "c", "d", "e", "f"])
    words.append(Word(text="g", start=5.0, end=5.2))  # pausa longa
    chunks = chunk_words(words, max_words=3)
    assert [[w.text for w in c] for c in chunks] == [["a", "b."], ["c", "d", "e"], ["f"], ["g"]]


def test_caption_states_do_not_overlap():
    words = _words("isso nunca deveria ter acontecido naquela noite".split())
    states = caption_states(words, 3, total=10.0)
    assert len(states) == len(words)
    for (s1, e1, *_), (s2, *_) in zip(states, states[1:]):
        assert s1 < e1 <= s2 + 1e-9


def test_scene_count_bounds():
    assert scene_count(30, vertical=True) == 5
    assert scene_count(600, vertical=False) == 60
    assert scene_count(5, vertical=True) == 4
    assert scene_count(1800, vertical=True) == 120


def test_build_user_prompt_contains_targets():
    req = VideoRequest(prompt="O navio fantasma", niche="misterios", platform="shorts",
                       duration_seconds=60, language="en", cta=False)
    text = build_user_prompt(req)
    assert "O navio fantasma" in text
    assert "= 118 palavras" in text  # (60s - 10 pausas de 0,25s) * 2,05
    assert "inglês" in text
    assert "vertical 9:16" in text
    assert "Não inclua pedidos" in text


def test_build_user_prompt_without_topic_uses_niche_ideas():
    text = build_user_prompt(VideoRequest(prompt="", niche="espaco"))
    assert "Escolha você um tema" in text
    assert "buraco negro" in text


def test_clean_script_normalizes():
    script = VideoScript(
        title="  Título  ",
        visual_subject="old ship",
        description="d",
        tags=["#tag1", " tag2 "],
        hashtags=["misterio", "#dark web"],
        thumbnail_text="NÃO ABRA",
        scenes=[
            Scene(narration="  texto \n com  espaços ", visual_queries=["a", " ", "b", "c", "d"]),
            Scene(narration="   ", visual_queries=["x"]),
            Scene(narration="ok", visual_queries=[]),
        ],
    )
    out = clean_script(script, VideoRequest(platform="shorts"))
    assert out.title == "Título"
    assert len(out.scenes) == 2
    assert out.scenes[0].narration == "texto com espaços"
    assert out.scenes[0].visual_queries == ["a", "b", "c"]
    assert out.scenes[1].visual_queries == ["dark cinematic night"]
    assert out.hashtags[0] == "#Shorts"
    assert "#darkweb" in out.hashtags
    assert out.tags == ["tag1", "tag2"]


def test_slugify():
    assert slugify("Ação & Mistério: o Navio!") == "acao-misterio-o-navio"
    assert slugify("!!!") == "video"
