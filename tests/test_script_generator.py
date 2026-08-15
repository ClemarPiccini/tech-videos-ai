import os

from src.audio_generator import AudioGenerator
from src.image_processor import ImageProcessor
from src.script_generator import ScriptGenerator


def test_criar_prompt_usa_duracao_fornecida(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    generator = ScriptGenerator({})

    prompt = generator._criar_prompt("IA", "pt", modo="short", duracao=45)

    assert "DURAÇÃO TOTAL:" in prompt
    assert "45 segundos" in prompt
    assert "35-50 segundos" not in prompt


def test_gerar_roteiro_aceita_duracao(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    generator = ScriptGenerator({})

    json_response = '''{
      "titulo": "Teste de IA",
      "descricao": "Descrição do vídeo",
      "tags": ["ia", "tecnologia"],
      "trilha_sonora": {
        "estilo": "cinematic",
        "humor": "dinâmico",
        "bpm_aproximado": 90
      },
      "cenas": [
        {
          "ordem": 1,
          "texto_narrador": "Introdução ao teste.",
          "descricao_visual": "Cena de tecnologia.",
          "efeito_sonoro": "impact",
          "musica_fundo": "cinematic",
          "duracao_estimada": 10,
          "tipo_transicao": "fade"
        }
      ]
    }'''

    monkeypatch.setattr(generator, "_gerar_com_ia", lambda prompt: json_response)

    roteiro = generator.gerar_roteiro(tema="IA", idioma="pt", modo="short", duracao=45)

    assert roteiro["tema"] == "IA"
    assert roteiro["duracao"] == 45


def test_audio_generator_usa_ordem_da_cena(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    generator = AudioGenerator({})

    class FakeAudioSegment:
        def __len__(self):
            return 5000

        def normalize(self):
            return self

        def export(self, *args, **kwargs):
            return None

    monkeypatch.setattr(
        generator,
        "client",
        type(
            "Client",
            (),
            {
                "text_to_speech": type(
                    "TextToSpeech",
                    (),
                    {"convert": staticmethod(lambda **kwargs: [b"audio-bytes"])},
                )()
            },
        )(),
    )
    monkeypatch.setattr("src.audio_generator.AudioSegment.from_mp3", lambda *args, **kwargs: FakeAudioSegment())

    roteiro = {
        "cenas": [
            {"ordem": 1, "texto_narrador": "Primeira cena"},
            {"ordem": 2, "texto_narrador": "Segunda cena"},
        ]
    }

    audios = generator.gerar_narracao_completa(roteiro, idioma="pt")

    assert [audio["ordem"] for audio in audios] == [1, 2]


def test_script_generator_nao_repete_titulo_ou_descricao_na_ultima_cena(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    generator = ScriptGenerator({})

    cenas = [
        {"ordem": 1, "texto_narrador": "IA está transformando o mundo."},
        {"ordem": 2, "texto_narrador": "Descubra IA em um vídeo cinematográfico e de alto impacto sobre o futuro."},
    ]

    resultado = generator._sanitizar_cenas_finais(cenas, "IA", "pt", "IA: O Futuro em Movimento", "Descubra IA em um vídeo cinematográfico e de alto impacto sobre o futuro, a inovação e a tecnologia que moldam o amanhã.")

    assert "O Futuro em Movimento" not in resultado[-1]["texto_narrador"]
    assert "Descubra" not in resultado[-1]["texto_narrador"]
    assert "Siga para mais ideias" in resultado[-1]["texto_narrador"]


def test_image_processor_usa_ordem_da_cena(monkeypatch):
    processor = ImageProcessor({})

    monkeypatch.setattr(processor, "_buscar_imagem", lambda query, index: f"/tmp/{index}.png")
    monkeypatch.setattr(processor, "_aplicar_efeitos_tech", lambda img_path: img_path)

    cenas = [
        {"ordem": 1, "texto_narrador": "Primeira cena", "descricao_visual": "Visão tech 1"},
        {"ordem": 2, "texto_narrador": "Segunda cena", "descricao_visual": "Visão tech 2"},
    ]

    imagens = processor.processar_cenas(cenas)

    assert [imagem["ordem"] for imagem in imagens] == [1, 2]
