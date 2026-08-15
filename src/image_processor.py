import os
import re
import requests
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw
import numpy as np

class ImageProcessor:
   
    def __init__(self, config):
        self.config = config
        self.config = config or {}

        self.temp_dir = Path("output/temp/images")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.unsplash_key = os.getenv("UNSPLASH_API_KEY")
        self.pexels_key = os.getenv("PEXELS_API_KEY")

        self.visual_config = self.config.get("visual", {})
        self.biblical_mode = False

    def processar_cenas(self, cenas):
        imagens = []
        contexto_roteiro = self._extrair_contexto_roteiro(cenas)

        for i, cena in enumerate(cenas):
            ordem = int(cena.get("ordem", i + 1) or (i + 1))
            query = self._construir_query_cena(cenas, i, contexto_roteiro)

            print(f"🖼️ Buscando imagem para cena {ordem}: {query}")

            img_path = self._buscar_imagem(query, i)

            if not img_path:
                continue

            if self.biblical_mode:
                img_processada = self._aplicar_efeitos_biblicos(img_path)
            else:
                img_processada = self._aplicar_efeitos_tech(img_path)

            imagens.append({
                "path": img_processada,
                "ordem": ordem,
                "descricao": query
            })

        return imagens

    def _extrair_contexto_roteiro(self, cenas):
        textos = []
        for cena in cenas:
            textos.append(cena.get("texto_narrador", ""))
            textos.append(cena.get("descricao_visual", ""))

        texto_total = " ".join(filter(None, textos))
        palavras = [p for p in re.findall(r"[A-Za-zÀ-ÿ0-9]+", texto_total.lower()) if len(p) > 3]

        palavras_mais_relevantes = []
        for palavra in palavras:
            if palavra not in {"para", "como", "quando", "muito", "sobre", "entre", "ainda", "porque", "primeiro", "desta"}:
                palavras_mais_relevantes.append(palavra)

        return " ".join(palavras_mais_relevantes[:20])

    def _construir_query_cena(self, cenas, indice, contexto_roteiro=None):
        cena = cenas[indice] if indice < len(cenas) else {}
        descricao = (cena.get("descricao_visual", "") or "").strip()
        narracao = (cena.get("texto_narrador", "") or "").strip()

        base = descricao or narracao or "technology concept scene"
        base = base.replace("\n", " ")
        base = " ".join(base.split())

        if contexto_roteiro:
            contexto = contexto_roteiro.strip()
        else:
            contexto = "technology futuristic"

        cena_variacao = [
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
        variante = cena_variacao[indice % len(cena_variacao)]

        tokens = [
            base,
            variante,
            "technology",
            "cinematic",
            "cyberpunk",
            "dark",
            "futuristic",
            contexto
        ]

        return ", ".join(dict.fromkeys(tokens))

    def _buscar_imagem(self, query, index):

        if self.unsplash_key:
            img_url = self._buscar_unsplash(query)

            if img_url:
                return self._download_imagem(
                    img_url,
                    index
                )

        if self.pexels_key:
            img_url = self._buscar_pexels(query)

            if img_url:
                return self._download_imagem(
                    img_url,
                    index
                )

        return self._criar_placeholder(index)

    def _buscar_unsplash(self, query):

        url = "https://api.unsplash.com/search/photos"

        headers = {
            "Authorization":
            f"Client-ID {self.unsplash_key}"
        }

        search_query = f"{query} technology dark"

        params = {
            "query": search_query,
            "orientation": "landscape",
            "per_page": 1
        }

        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=20
            )

            data = response.json()

            if data.get("results"):
                return (
                    data["results"][0]
                    ["urls"]["regular"]
                )

        except Exception as e:
            print(
                f"Erro Unsplash: {e}"
            )

        return None

    def _buscar_pexels(self, query):

        url = "https://api.pexels.com/v1/search"

        headers = {
            "Authorization":
            self.pexels_key
        }

        search_query = f"{query} technology"

        params = {
            "query": search_query,
            "orientation": "landscape",
            "per_page": 1
        }

        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=20
            )

            data = response.json()

            if data.get("photos"):
                return (
                    data["photos"][0]
                    ["src"]["large"]
                )

        except Exception as e:
            print(
                f"Erro Pexels: {e}"
            )

        return None

    def _download_imagem(
        self,
        url,
        index
    ):

        img_path = (
            self.temp_dir /
            f"img_{index:02d}.jpg"
        )

        response = requests.get(
            url,
            timeout=30
        )

        with open(img_path, "wb") as f:
            f.write(response.content)

        return img_path

    def _criar_placeholder(
        self,
        index
    ):

        img_path = (
            self.temp_dir /
            f"img_{index:02d}_placeholder.jpg"
        )

        if self.biblical_mode:

            img = Image.new(
                "RGB",
                (1920, 1080),
                color="#d7c4a3"
            )

        else:

            img = Image.new(
                "RGB",
                (1920, 1080),
                color="#0a0a0a"
            )

            draw = ImageDraw.Draw(img)

            for x in range(
                0,
                1920,
                100
            ):
                draw.line(
                    [(x, 0), (x, 1080)],
                    fill="#1a1a1a",
                    width=1
                )

            for y in range(
                0,
                1080,
                100
            ):
                draw.line(
                    [(0, y), (1920, y)],
                    fill="#1a1a1a",
                    width=1
                )

        img.save(img_path)

        return img_path

    def _aplicar_efeitos_tech(
        self,
        img_path
    ):
        img = Image.open(img_path).convert("RGB")

        img = img.resize(
            (1920, 1080),
            Image.Resampling.LANCZOS
        )
        brightness = (
            self.visual_config
            .get("brightness", 0.7)
        )

        contrast = (
            self.visual_config
            .get("contrast", 1.4)
        )

        saturation = (
            self.visual_config
            .get("saturation", 0.9)
        )

        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(brightness)

        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(contrast)

        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(saturation)

        img = self._aplicar_vinheta(img)

        img = self._adicionar_scanlines(img)

        output_path = str(
            img_path
        ).replace(
            ".jpg",
            "_processed.jpg"
        )

        img.save(
            output_path,
            quality=95
        )

        return output_path

    def _aplicar_efeitos_biblicos(
        self,
        img_path
    ):

        img = Image.open(img_path).convert("RGB")

        img = img.resize(
            (1920, 1080),
            Image.Resampling.LANCZOS
        )

        brightness = (
            self.visual_config
            .get("brightness", 1.1)
        )

        contrast = (
            self.visual_config
            .get("contrast", 1.05)
        )

        saturation = (
            self.visual_config
            .get("saturation", 1.15)
        )

        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(brightness)

        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(contrast)

        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(saturation)

        output_path = str(
            img_path
        ).replace(
            ".jpg",
            "_processed.jpg"
        )

        img.save(
            output_path,
            quality=95
        )

        return output_path

    def _aplicar_vinheta(
        self,
        img
    ):

        width, height = img.size

        vignette = Image.new(
            "L",
            (width, height)
        )

        strength = (
            self.visual_config
            .get(
                "vignette_strength",
                0.3
            )
        )

        for y in range(height):
            for x in range(width):

                dist = (
                    (
                        (x - width / 2) ** 2
                        +
                        (y - height / 2) ** 2
                    )
                    ** 0.5
                )

                max_dist = (
                    (
                        (width / 2) ** 2
                        +
                        (height / 2) ** 2
                    )
                    ** 0.5
                )

                darkness = int(
                    255 *
                    (
                        1 -
                        (
                            dist /
                            max_dist
                        ) *
                        strength
                    )
                )

                darkness = max(
                    0,
                    min(
                        255,
                        darkness
                    )
                )

                vignette.putpixel(
                    (x, y),
                    darkness
                )

        return Image.composite(
            img,
            Image.new(
                "RGB",
                img.size,
                "black"
            ),
            vignette
        )

    def _adicionar_scanlines(
        self,
        img
    ):

        pixels = np.array(img)

        for y in range(
            0,
            img.height,
            4
        ):
            pixels[y] = (
                pixels[y] * 0.95
            ).astype(np.uint8)

        return Image.fromarray(pixels)