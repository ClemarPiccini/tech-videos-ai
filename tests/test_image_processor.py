from src.image_processor import ImageProcessor


def test_construir_query_cena_usa_contexto_geral():
    processor = ImageProcessor({"visual": {"biblical_mode": False}})
    cenas = [
        {
            "descricao_visual": "Futuristic dashboard with holograms",
            "texto_narrador": "A inteligência artificial alerta sobre o futuro da automação.",
            "ordem": 1,
        },
        {
            "descricao_visual": "Data center with glowing server racks",
            "texto_narrador": "As redes começam a se conectar em tempo real.",
            "ordem": 2,
        },
    ]

    query = processor._construir_query_cena(cenas, 1)

    assert "futuristic" in query.lower()
    assert "dashboard" in query.lower()
    assert "technology" in query.lower()
    assert "cyberpunk" in query.lower()
