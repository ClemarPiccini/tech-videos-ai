"""Busca e download de mídia stock com vários provedores e fallback para fundo gerado.

Ordem de tentativa para cada busca:
  1. vídeos: Pexels (PEXELS_API_KEY) -> Pixabay (PIXABAY_API_KEY)
  2. fotos:  Pexels -> Pixabay -> Openverse (sem chave, só domínio público CC0/PDM)
  3. fundo escuro gerado localmente
"""
from __future__ import annotations

import hashlib
import io
import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

import requests
from PIL import Image, ImageDraw, ImageFilter

from app import settings

SEARCH_CACHE_TTL = 24 * 3600  # Pixabay exige cache das buscas por 24h
USER_AGENT = "DarkVideoStudio/1.0 (+local)"

# ---------------- relevância ----------------

STOPWORDS = {
    "the", "and", "with", "from", "into", "onto", "over", "under", "for", "of", "in", "on", "at", "to", "by",
    "an", "a", "its", "his", "her", "their", "this", "that", "very", "view", "shot", "scene", "background",
    "closeup", "close", "up", "dark", "night", "light", "cinematic", "footage", "video", "stock", "4k", "hd",
}
# Termos que não são filmáveis: buscas com eles retornam imagens aleatórias
ABSTRACT = {
    "mystery", "mysterious", "mysteries", "theory", "theories", "investigation", "investigate", "evidence",
    "curse", "cursed", "incident", "enemy", "fear", "myth", "reality", "unexplained", "unresolved", "unknown",
    "disappearance", "disappearances", "disappear", "missing", "subscribe", "follow", "join", "community",
    "story", "stories", "truth", "secret", "secrets", "growing", "continuing", "true", "concept", "idea",
    "more", "now", "spooky", "creepy", "scary", "horror", "legend", "conspiracy", "question", "answer",
    "explanation", "hypothesis", "case", "event", "history", "fact", "facts", "info", "information",
}


def _tokens(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2]


def _stem(word: str) -> str:
    for suffix in ("ies", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def content_words(text: str) -> Set[str]:
    return {_stem(w) for w in _tokens(text) if w not in STOPWORDS and w not in ABSTRACT}


def concrete_query(query: str) -> str:
    """Remove palavras abstratas, números e nomes próprios demais; '' se nada filmável sobrar."""
    kept = [w for w in _tokens(query) if w not in ABSTRACT]
    return " ".join(kept) if content_words(" ".join(kept)) else ""


PREPOSITIONS = {"in", "of", "on", "at", "with", "near", "under", "over", "from", "into", "inside", "during", "by"}


def core_phrase(query: str) -> str:
    """Parte antes da primeira preposição: "abandoned ship in the middle of the ocean" -> "abandoned ship"."""
    words = query.split()
    for i, w in enumerate(words):
        if i > 0 and w.lower() in PREPOSITIONS:
            return " ".join(words[:i])
    return query


def head_noun(query: str) -> str:
    """Em inglês o substantivo principal costuma ser a última palavra do núcleo ("empty ship deck" -> "deck")."""
    words = [w for w in _tokens(core_phrase(query)) if w not in STOPWORDS and w not in ABSTRACT]
    return _stem(words[-1]) if words else ""


def relevance(query: str, text: str) -> int:
    """Palavras em comum; 0 se só bater adjetivo (ex.: "empty decks" x foto de cachorro com tag "empty")."""
    text_words = content_words(text)
    common = content_words(query) & text_words
    if not common:
        return 0
    if head_noun(query) not in text_words and len(common) < 2:
        return 0
    return len(common)


_brightness_cache: Dict[str, float] = {}


def brightness_of(session: requests.Session, url: str) -> float:
    """Luminância média (0 = preto, 1 = branco) de uma miniatura; 0.5 se não der para baixar."""
    if url in _brightness_cache:
        return _brightness_cache[url]
    value = 0.5
    try:
        r = session.get(url, timeout=10)
        if r.status_code == 200:
            with Image.open(io.BytesIO(r.content)) as im:
                gray = im.convert("L").resize((48, 48))
                value = sum(gray.getdata()) / (48 * 48 * 255)
    except Exception:  # noqa: BLE001 — miniatura é só um sinal auxiliar
        pass
    _brightness_cache[url] = value
    return value


def rank(items: List[dict], query: str, text_of: Callable[[dict], str],
         duration_of: Optional[Callable[[dict], float]] = None, min_duration: float = 0) -> List[dict]:
    """Mantém só resultados que compartilham alguma palavra com a busca; mais relevantes (e longos o bastante) primeiro."""
    scored = [(relevance(query, text_of(it)), it) for it in items]
    scored = [(s, it) for s, it in scored if s > 0]
    scored.sort(key=lambda x: (-x[0], bool(duration_of) and duration_of(x[1]) < min_duration))
    return [it for _, it in scored]


@dataclass
class Visual:
    path: Path
    kind: str  # "video" | "image"
    duration: float = 0.0
    source_url: str = ""
    provider: str = ""
    author: str = ""


class VisualFinder:
    def __init__(self, orientation: str, size: tuple) -> None:
        self.vertical = orientation == "vertical"
        self.width, self.height = size
        self.cache = settings.path("cache") / "media"
        self.search_cache = settings.path("cache") / "search"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.search_cache.mkdir(parents=True, exist_ok=True)
        self.used: Set[str] = set()
        self.credits: List[Visual] = []
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.pexels_key = settings.env("PEXELS_API_KEY")
        self.pixabay_key = settings.env("PIXABAY_API_KEY")
        # Filtro de clima: descarta mídia clara demais (pela miniatura) num perfil "dark"
        self.max_brightness = float(settings.config()["video"].get("max_source_brightness", 1.0))
        self.strict = True

    @property
    def providers(self) -> List[str]:
        names = [n for n, k in (("Pexels", self.pexels_key), ("Pixabay", self.pixabay_key)) if k]
        return names + ["Openverse"]

    def find(self, query: str, min_duration: float, subject: str = "", fallback_query: str = "") -> Visual:
        """Ordem: cena + assunto do vídeo -> cena -> assunto -> estilo do nicho.

        Primeiro com o filtro de clima (só mídia escura); se nada passar, repete aceitando qualquer
        resultado relevante, para não cair no fundo gerado.
        """
        q, s, f = concrete_query(query), concrete_query(core_phrase(subject)), concrete_query(fallback_query)
        attempts = []
        if q and s and not (content_words(q) & content_words(s)):
            # "dimly lit room" num vídeo sobre hospital vira "dimly lit room hospital"
            attempts.append(f"{q} {head_noun(s)}")
        attempts += [q, s, f]
        attempts = list(dict.fromkeys(a for a in attempts if a))
        for strict in (True, False):
            if not strict and self.max_brightness >= 1.0:
                break
            self.strict = strict
            for a in attempts:
                v = self._find_one(a, min_duration)
                if v:
                    self.strict = True
                    return self._credit(v)
        self.strict = True
        return self._placeholder(query)

    def _mood_ok(self, thumb_url: str) -> bool:
        if not self.strict or self.max_brightness >= 1.0 or not thumb_url:
            return True
        return brightness_of(self.session, thumb_url) <= self.max_brightness

    def _find_one(self, query: str, min_duration: float) -> Optional[Visual]:
        video_sources: List[Callable[[str, float], Optional[Visual]]] = []
        photo_sources: List[Callable[[str], Optional[Visual]]] = []
        if self.pexels_key:
            video_sources.append(self._pexels_video)
            photo_sources.append(self._pexels_photo)
        if self.pixabay_key:
            video_sources.append(self._pixabay_video)
            photo_sources.append(self._pixabay_photo)
        photo_sources.append(self._openverse_photo)

        for src in video_sources:
            v = src(query, min_duration)
            if v:
                return v
        for src in photo_sources:
            v = src(query)
            if v:
                return v
        return None

    def _credit(self, v: Visual) -> Visual:
        self.credits.append(v)
        return v

    # ---------------- HTTP + cache ----------------

    def _search(self, provider: str, url: str, params: dict, headers: Optional[dict] = None) -> Optional[dict]:
        public = {k: v for k, v in params.items() if k != "key"}
        digest = hashlib.sha1(json.dumps([provider, url, public], sort_keys=True).encode()).hexdigest()
        cached = self.search_cache / f"{provider}_{digest}.json"
        if cached.exists() and time.time() - cached.stat().st_mtime < SEARCH_CACHE_TTL:
            try:
                return json.loads(cached.read_text(encoding="utf-8"))
            except ValueError:
                pass
        try:
            r = self.session.get(url, params=params, headers=headers or {}, timeout=20)
        except requests.RequestException:
            return None
        if r.status_code != 200:
            return None
        try:
            data = r.json()
        except ValueError:
            return None
        cached.write_text(json.dumps(data), encoding="utf-8")
        return data

    def _download(self, url: str, name: str) -> Optional[Path]:
        dest = self.cache / name
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with self.session.get(url, stream=True, timeout=60) as r:
                if r.status_code != 200:
                    return None
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        f.write(chunk)
            tmp.rename(dest)
            return dest
        except requests.RequestException:
            tmp.unlink(missing_ok=True)
            return None

    def _take(self, uid: str) -> bool:
        if uid in self.used:
            return False
        self.used.add(uid)
        return True

    # ---------------- Pexels ----------------

    def _pexels_params(self, query: str) -> dict:
        return {"query": query, "orientation": "portrait" if self.vertical else "landscape", "per_page": 15}

    def _pexels_video(self, query: str, min_duration: float) -> Optional[Visual]:
        data = self._search("pexels", "https://api.pexels.com/videos/search", self._pexels_params(query),
                            {"Authorization": self.pexels_key})
        videos = [v for v in (data or {}).get("videos", []) if f"pexels-v{v['id']}" not in self.used]
        # A URL do Pexels descreve o vídeo (ex.: /video/old-ship-at-sea-123/)
        videos = rank(videos, query, lambda v: v.get("url", ""), lambda v: v.get("duration", 0), min_duration)
        for video in videos[:6]:
            f = self._pick_file(
                [(x["link"], x["width"], x["height"]) for x in video.get("video_files", [])
                 if x.get("file_type") == "video/mp4" and x.get("width") and x.get("height")],
                same_orientation=True,
            )
            if not f or not self._mood_ok(video.get("image", "")):
                continue
            path = self._download(f[0], f"pexels_v{video['id']}_{f[1]}.mp4")
            if path and self._take(f"pexels-v{video['id']}"):
                return Visual(path, "video", float(video.get("duration", 0)), video.get("url", ""), "Pexels",
                              (video.get("user") or {}).get("name", ""))
        return None

    def _pexels_photo(self, query: str) -> Optional[Visual]:
        data = self._search("pexels", "https://api.pexels.com/v1/search", self._pexels_params(query),
                            {"Authorization": self.pexels_key})
        photos = rank((data or {}).get("photos", []), query, lambda p: f"{p.get('alt', '')} {p.get('url', '')}")
        for photo in photos:
            uid = f"pexels-p{photo['id']}"
            src = photo.get("src", {})
            url = src.get("portrait" if self.vertical else "large2x") or src.get("original")
            if uid in self.used or not url or not self._mood_ok(src.get("tiny", "")):
                continue
            path = self._download(url, f"pexels_p{photo['id']}.jpg")
            if path and self._take(uid):
                return Visual(path, "image", 0, photo.get("url", ""), "Pexels", photo.get("photographer", ""))
        return None

    # ---------------- Pixabay ----------------

    def _pixabay_video(self, query: str, min_duration: float) -> Optional[Visual]:
        data = self._search("pixabay", "https://pixabay.com/api/videos/", {
            "key": self.pixabay_key, "q": query[:100], "video_type": "film", "safesearch": "true", "per_page": 20,
        })
        hits = [h for h in (data or {}).get("hits", []) if f"pixabay-v{h['id']}" not in self.used]
        hits = rank(hits, query, lambda h: h.get("tags", ""), lambda h: h.get("duration", 0), min_duration)
        for hit in hits[:6]:
            sizes = hit.get("videos", {})
            files = [(s["url"], s["width"], s["height"]) for s in sizes.values()
                     if s.get("url") and s.get("width") and s.get("height")]
            # Pixabay não filtra orientação de vídeo: no vertical recortamos o centro de um horizontal
            f = self._pick_file(files, same_orientation=False)
            thumb = (sizes.get("tiny") or sizes.get("small") or {}).get("thumbnail", "")
            if not f or not self._mood_ok(thumb):
                continue
            path = self._download(f[0], f"pixabay_v{hit['id']}_{f[1]}.mp4")
            if path and self._take(f"pixabay-v{hit['id']}"):
                return Visual(path, "video", float(hit.get("duration", 0)), hit.get("pageURL", ""), "Pixabay",
                              hit.get("user", ""))
        return None

    def _pixabay_photo(self, query: str) -> Optional[Visual]:
        data = self._search("pixabay", "https://pixabay.com/api/", {
            "key": self.pixabay_key, "q": query[:100], "image_type": "photo", "safesearch": "true", "per_page": 20,
            "orientation": "vertical" if self.vertical else "horizontal",
        })
        for hit in rank((data or {}).get("hits", []), query, lambda h: h.get("tags", "")):
            uid = f"pixabay-p{hit['id']}"
            url = hit.get("fullHDURL") or hit.get("largeImageURL")
            if uid in self.used or not url or not self._mood_ok(hit.get("previewURL", "")):
                continue
            path = self._download(url, f"pixabay_p{hit['id']}.jpg")
            if path and self._take(uid):
                return Visual(path, "image", 0, hit.get("pageURL", ""), "Pixabay", hit.get("user", ""))
        return None

    # ---------------- Openverse (sem chave) ----------------

    OPENVERSE_MAX_BYTES = 15 * 1024 * 1024
    OPENVERSE_MAX_UPSCALE = 2.2  # acima disso a imagem fica borrada demais no quadro final

    def _openverse_photo(self, query: str) -> Optional[Visual]:
        # O acervo de domínio público é menor: se a busca exata falhar, tenta versões mais curtas
        words = query.split()
        variants = [query]
        if len(words) > 2:
            variants += [" ".join(words[-2:]), " ".join(words[:2])]
        for q in dict.fromkeys(variants):
            v = self._openverse_search(q)
            if v:
                return v
        return None

    def _openverse_search(self, query: str) -> Optional[Visual]:
        data = self._search("openverse", "https://api.openverse.org/v1/images/", {
            "q": query, "license": "cc0,pdm", "mature": "false", "page_size": 20,
        })
        candidates = []
        results = rank((data or {}).get("results", []), query,
                       lambda r: " ".join([r.get("title") or ""] + [t.get("name", "") for t in r.get("tags") or []]))
        for r in results:
            w, h = r.get("width") or 0, r.get("height") or 0
            ftype = (r.get("filetype") or "jpg").lower()
            if not (w and h and r.get("url")) or f"openverse-{r['id']}" in self.used:
                continue
            if ftype not in ("jpg", "jpeg", "png") or (r.get("filesize") or 0) > self.OPENVERSE_MAX_BYTES:
                continue
            upscale = max(self.width / w, self.height / h)
            if upscale <= self.OPENVERSE_MAX_UPSCALE:
                same_orientation = (h >= w) == self.vertical
                candidates.append((not same_orientation, upscale, r))
        # rank() já ordenou por relevância; sort estável mantém essa ordem como critério principal
        candidates.sort(key=lambda c: c[0])
        for _, _, r in candidates[:5]:
            if not self._mood_ok(r.get("thumbnail") or ""):
                continue
            ext = "png" if (r.get("filetype") or "").lower() == "png" else "jpg"
            path = self._download(r["url"], f"openverse_{r['id']}.{ext}")
            if path and self._valid_image(path) and self._take(f"openverse-{r['id']}"):
                return Visual(path, "image", 0, r.get("foreign_landing_url", ""), "Openverse", r.get("creator") or "")
        return None

    @staticmethod
    def _valid_image(path: Path) -> bool:
        try:
            with Image.open(path) as im:
                im.verify()
            return True
        except Exception:
            path.unlink(missing_ok=True)
            return False

    # ---------------- utilitários ----------------

    def _pick_file(self, files: List[tuple], same_orientation: bool) -> Optional[tuple]:
        """Escolhe (url, w, h): o menor arquivo que ainda cobre o quadro final após o recorte."""
        if same_orientation:
            files = [f for f in files if (f[2] >= f[1]) == self.vertical]
        if not files:
            return None

        def coverage(f: tuple) -> float:
            return max(self.width / f[1], self.height / f[2])  # fator de ampliação necessário

        sharp = [f for f in files if coverage(f) <= 1.0]
        if sharp:
            return min(sharp, key=lambda f: f[1] * f[2])
        return min(files, key=coverage)

    def _placeholder(self, query: str) -> Visual:
        seed = int(hashlib.md5(query.encode()).hexdigest()[:8], 16)
        dest = self.cache / f"placeholder_{self.width}x{self.height}_{seed}.png"
        if not dest.exists():
            rng = random.Random(seed)
            img = Image.new("RGB", (self.width, self.height), (8, 8, 12))
            draw = ImageDraw.Draw(img)
            for _ in range(6):
                r = rng.randint(self.width // 6, self.width // 2)
                x, y = rng.randint(0, self.width), rng.randint(0, self.height)
                c = rng.choice([(40, 10, 60), (10, 30, 60), (60, 10, 10), (20, 40, 40)])
                draw.ellipse([x - r, y - r, x + r, y + r], fill=c)
            img = img.filter(ImageFilter.GaussianBlur(self.width // 10))
            img.save(dest)
        return Visual(path=dest, kind="image", provider="gerado")


def credits_text(visuals: List[Visual]) -> str:
    seen, lines = set(), []
    for v in visuals:
        if v.source_url and v.source_url not in seen:
            seen.add(v.source_url)
            by = f" — {v.author}" if v.author else ""
            lines.append(f"{v.provider}{by}: {v.source_url}")
    return "\n".join(lines)
