import os
import json
import random
import requests
import re

class ScriptGenerator:
    def __init__(self, config):
        self.config = config

        self.api_key = os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("❌ OPENROUTER_API_KEY não encontrada no .env")

        self.temas_tech = self._carregar_temas()

    def _carregar_temas(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base_dir, "..", "data", "temas_tech.json")

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            raise RuntimeError(f"❌ Erro ao carregar temas_tech.json: {e}")
        
    def extrair_json(self, texto):
      # Remove possíveis ```json ``` ou ```
      texto = re.sub(r"```.*?```", "", texto, flags=re.S)

      match = re.search(r"\{.*\}", texto, re.S)
      if not match:
          raise ValueError("JSON não encontrado na resposta da IA")

      try:
          return json.loads(match.group())
      except json.JSONDecodeError as e:
          print("❌ JSON inválido retornado pela IA:")
          print(match.group())
          raise e

    
    def gerar_roteiro(
        self,
        tema=None,
        idioma="pt",
        modo="short",
        duracao=None
    ):

        if idioma not in self.temas_tech:

            print(
                f"⚠️ Idioma '{idioma}' "
                f"não encontrado. Usando 'pt'."
            )

            idioma = "pt"

        if not tema:
            tema = random.choice(
                self.temas_tech[idioma]
            )

        tema = str(tema).strip() or "Tecnologia"

        prompt = self._criar_prompt(
            tema,
            idioma,
            modo,
            duracao
        )

        print(
            f"🤖 Gerando roteiro "
            f"[{modo.upper()}] "
            f"com IA..."
        )

        content = self._gerar_com_ia(
            prompt
        )

        roteiro = self.extrair_json(
            content
        )

        roteiro["cenas"] = self._normalizar_cenas(
            roteiro.get("cenas", []),
            tema,
            idioma
        )

        roteiro["tema"] = tema
        roteiro["idioma"] = idioma
        roteiro["modo"] = modo
        roteiro["duracao"] = duracao
        roteiro["titulo"] = self._criar_titulo(tema, idioma)
        roteiro["descricao"] = self._criar_descricao(tema, idioma, modo)
        roteiro["tags"] = self._criar_tags(tema, idioma)
        roteiro["cenas"] = self._sanitizar_cenas_finais(
            roteiro["cenas"],
            tema,
            idioma,
            roteiro["titulo"],
            roteiro["descricao"]
        )

        print("✅ Roteiro gerado com IA")

        return roteiro

    def _normalizar_cenas(self, cenas, tema, idioma):
        cenas_norm = []

        for idx, cena in enumerate(cenas or []):
            if not isinstance(cena, dict):
                continue

            ordem = int(cena.get("ordem", idx + 1) or (idx + 1))
            texto = (cena.get("texto_narrador") or "").strip()
            visual = (cena.get("descricao_visual") or "").strip()

            if not texto:
                texto = self._gerar_texto_cena(tema, ordem, idioma)
            elif self._eh_repetido(cenas_norm, texto):
                texto = self._gerar_texto_cena(tema, ordem, idioma)

            if not visual:
                visual = self._gerar_visual_cena(tema, ordem)
            elif self._eh_repetido_visual(cenas_norm, visual):
                visual = self._gerar_visual_cena(tema, ordem)

            cena["ordem"] = ordem
            cena["texto_narrador"] = self._adaptar_texto_para_tema(texto, tema, idioma, ordem)
            cena["descricao_visual"] = self._adaptar_visual_para_tema(visual, tema, ordem)
            cenas_norm.append(cena)

        cenas_norm.sort(key=lambda cena: int(cena.get("ordem", 0)))
        for idx, cena in enumerate(cenas_norm, start=1):
            cena["ordem"] = idx

        return cenas_norm

    def _eh_repetido(self, cenas, texto):
        return any((c.get("texto_narrador") or "").strip() == texto for c in cenas)

    def _eh_repetido_visual(self, cenas, visual):
        return any((c.get("descricao_visual") or "").strip() == visual for c in cenas)

    def _sanitizar_cenas_finais(self, cenas, tema, idioma, titulo, descricao):
        if not cenas:
            return cenas

        titulo_norm = (titulo or "").strip().lower()
        descricao_norm = (descricao or "").strip().lower()
        tema_limpo = str(tema).strip() or "Tecnologia"

        for cena in cenas:
            texto = (cena.get("texto_narrador") or "").strip()
            if not texto:
                continue

            texto_lower = texto.lower()
            if titulo_norm and titulo_norm in texto_lower:
                texto = self._criar_cta_final(tema, idioma)
            elif descricao_norm and descricao_norm in texto_lower:
                texto = self._criar_cta_final(tema, idioma)
            elif "descubra" in texto_lower and tema_limpo.lower() in texto_lower:
                texto = self._criar_cta_final(tema, idioma)

            cena["texto_narrador"] = texto

        ultima = cenas[-1]
        ultima["texto_narrador"] = self._criar_cta_final(tema, idioma)
        return cenas

    def _criar_cta_final(self, tema, idioma):
        tema_limpo = str(tema).strip() or "Tecnologia"
        if idioma == "en":
            return f"Follow for more {tema_limpo} insights and the next big shift in innovation."
        if idioma == "es":
            return f"Sigue para más ideas sobre {tema_limpo} y el futuro en movimiento."
        return f"Siga para mais ideias sobre {tema_limpo} e o futuro em movimento."

    def _gerar_texto_cena(self, tema, ordem, idioma):
        tema_limpo = str(tema).strip() or "Tecnologia"
        if idioma == "en":
            return f"Scene {ordem}: {tema_limpo} is reshaping the future with bold ideas and fast-moving innovation."
        if idioma == "es":
            return f"Escena {ordem}: {tema_limpo} está transformando el futuro con ideas audaces e innovación acelerada."
        return f"Cena {ordem}: {tema_limpo} está transformando o futuro com ideias ousadas e inovação acelerada."

    def _gerar_visual_cena(self, tema, ordem):
        tema_limpo = str(tema).strip() or "Tecnologia"
        return f"{tema_limpo} cinematic scene {ordem}, ultra detailed, modern design, futuristic atmosphere, premium lighting, realistic product visualization, high contrast, 8k"

    def _criar_titulo(self, tema, idioma):
        tema_limpo = str(tema).strip() or "Tecnologia"
        if idioma == "en":
            return f"{tema_limpo}: The Future in Motion"
        if idioma == "es":
            return f"{tema_limpo}: El Futuro en Movimiento"
        return f"{tema_limpo}: O Futuro em Movimento"

    def _criar_descricao(self, tema, idioma, modo):
        tema_limpo = str(tema).strip() or "Tecnologia"
        if idioma == "en":
            return f"Explore {tema_limpo} in a cinematic and high-impact video about the future, innovation, and the technology shaping tomorrow."
        if idioma == "es":
            return f"Explora {tema_limpo} en un video cinematográfico y de alto impacto sobre el futuro, la innovación y la tecnología que está moldeando el mañana."
        return f"Descubra {tema_limpo} em um vídeo cinematográfico e de alto impacto sobre o futuro, a inovação e a tecnologia que moldam o amanhã."

    def _criar_tags(self, tema, idioma):
        base = [
            str(tema).strip(),
            str(tema).strip().lower(),
            "tecnologia",
            "inovacao",
            "ia",
            "futuro",
            "cinematica",
        ]
        if idioma == "en":
            base = [
                str(tema).strip(),
                str(tema).strip().lower(),
                "technology",
                "ai",
                "innovation",
                "future",
                "cinematic",
            ]
        elif idioma == "es":
            base = [
                str(tema).strip(),
                str(tema).strip().lower(),
                "tecnologia",
                "ia",
                "innovacion",
                "futuro",
                "cinematica",
            ]

        tags = []
        for item in base:
            clean = re.sub(r"[^a-zA-Z0-9À-ÿ\s\-_]", "", item).strip()
            if clean:
                tags.append(clean)
        return tags[:10]

    def _adaptar_texto_para_tema(self, texto, tema, idioma, ordem=1):
        texto = (texto or "").strip()
        if not texto:
            tema_limpo = str(tema).strip() or "Tecnologia"
            if idioma == "en":
                return f"Scene {ordem}: {tema_limpo} is moving fast and shaping the future."
            if idioma == "es":
                return f"Escena {ordem}: {tema_limpo} está avanzando y transformando el futuro."
            return f"Cena {ordem}: {tema_limpo} está em movimento e transformando o futuro."
        return texto

    def _adaptar_visual_para_tema(self, descricao_visual, tema, ordem=1):
        tema_limpo = str(tema).strip() or "Tecnologia"
        base = (descricao_visual or "").strip()
        variações = [
            "close-up action",
            "high-tech workflow",
            "team collaboration",
            "real-time decision",
            "future environment",
            "immersive detail",
            "dynamic perspective",
            "impact moment",
            "precision execution",
            "innovation showcase"
        ]
        variante = variações[(ordem - 1) % len(variações)]

        if base:
            return f"{base}, {tema_limpo} {variante}, cinematic lighting, realistic details, futuristic mood, premium production, 8k"

        return f"{tema_limpo} {variante}, cinematic scene, ultra detailed, modern design, futuristic atmosphere, premium lighting, realistic visualization, high contrast, 8k"


  
    # -----------------------------
    # CHAMADA OPENROUTER
    # -----------------------------
    def _gerar_com_ia(self, prompt):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",  # exigido pelo OpenRouter
            "X-Title": "Tech Video AI Generator"
        }

        data = {

            "model": "openai/gpt-4o-mini",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.6,
            "max_tokens": 3000,
            "response_format": { "type": "json_object" }
        }

        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=90
        )

        if r.status_code != 200:
            raise RuntimeError(f"OpenRouter error {r.status_code}: {r.text}")

        return r.json()["choices"][0]["message"]["content"]


    def _criar_prompt(
        self,
        tema,
        idioma,
        modo="short",
        duracao=None
    ):

        idioma_map = {
            "pt": "português brasileiro",
            "es": "español latinoamericano",
            "en": "english",
        }

        idioma_txt = idioma_map.get(
            idioma,
            "português brasileiro"
        )

        # -----------------------------------
        # CONFIG SHORTS
        # -----------------------------------

        if duracao is not None:
            duracao_total = f"{duracao} segundos"
        elif modo == "short":
            duracao_total = "35–50 segundos"
        else:
            duracao_total = "6–9 minutos"

        if modo == "short":

            total_cenas = 8 if duracao is None else max(6, min(10, round(duracao / 6)))
            duracao_cena = "5–8 segundos"

            estrutura = """
    - Hook extremamente forte nos primeiros 3 segundos
    - Ritmo rápido
    - Frases curtas
    - Final com CTA curto
    """

        # -----------------------------------
        # CONFIG LONGOS
        # -----------------------------------

        else:

            total_cenas = 35 if duracao is None else max(12, min(40, round(duracao / 10)))
            duracao_cena = "8–15 segundos"

            estrutura = """
    - Introdução extremamente impactante
    - Construir suspense continuamente
    - Criar curiosidade entre blocos
    - Fazer o espectador querer ver a próxima cena
    - Meio do vídeo deve aumentar tensão
    - Final cinematográfico
    - CTA forte para inscrição
    """

        return f"""
    Você é um roteirista profissional especialista em vídeos de tecnologia e inovação para YouTube.

Crie um roteiro cinematográfico, emocionante e envolvente baseado no tema solicitado pelo usuário. O roteiro deve refletir diretamente o tema, o contexto e a narrativa escolhidos no prompt.

    TEMA:
    {tema}

    ESTILO:
    - Cinematográfico
    - Épico
    - Emocionante
    - Inspirador
    - Tecnológico
    - Marcante
    - Visual extremamente detalhado

    DURAÇÃO TOTAL:
    {duracao_total}

    ESTRUTURA:
    {estrutura}

    REGRAS ABSOLUTAS:
    - Responda APENAS JSON válido
    - Não use markdown
    - Não escreva explicações
    - Não escreva comentários
    - Não coloque texto antes do JSON
    - Não coloque texto depois do JSON

    FORMATO OBRIGATÓRIO:

    {{
      "titulo": "string",
      "descricao": "string SEO longa",
      "tags": [
        "tag1",
        "tag2",
        "tag3",
        "tag4",
        "tag5",
        "tag6",
        "tag7",
        "tag8",
        "tag9",
        "tag10"
      ],

      "trilha_sonora": {{   
        "estilo": "epic orchestral",
        "humor": "inspirador e espiritual",
        "bpm_aproximado": 80
        }},

      "cenas": [
        {{
          "ordem": 1,

          "texto_narrador":
          "texto EXATO da narração",

          "descricao_visual":
          "Ultra realistic biblical cinematic scene in English, ancient Jerusalem, historical clothing, dramatic sunlight, epic atmosphere, highly detailed, realistic characters, movie quality, 8k",

          "efeito_sonoro":
            "epic impact",

          "musica_fundo":
            "cinematic biblical orchestra",

          "duracao_estimada":
          10,

          "tipo_transicao":
          "fade"
        }}
      ]
    }}

    REGRAS DE CONTEÚDO:

    - Total de {total_cenas} cenas
    - Cada cena entre {duracao_cena}
    - Cena 1 deve ter um HOOK extremamente forte
    - Não repetir ideias
    - Linguagem simples e viral
    - Alta retenção
    - Estilo narrativo parecido com documentários cinematográficos de tecnologia e inovação
    - Última cena deve ter CTA
    - O tema principal deve estar presente em todas as cenas

    IMPORTANTE:
    - descricao_visual deve refletir o tema central e o visual tecnológico/cinematográfico
    - narração no idioma solicitado
    - JSON 100% válido
    - Não deixar campos faltando
    """.strip()

