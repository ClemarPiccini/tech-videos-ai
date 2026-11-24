"""Legendas estilo "viral": blocos curtos em caixa alta com a palavra falada destacada.

O ffmpeg local não tem libass, então cada estado da legenda vira um PNG transparente
e o conjunto é sobreposto ao vídeo via concat demuxer (uma única passada de encode).
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont

from app import settings
from app.models import Word

MAX_GAP = 0.45  # pausa (s) que força o início de um novo bloco


def chunk_words(words: List[Word], max_words: int) -> List[List[Word]]:
    chunks: List[List[Word]] = []
    current: List[Word] = []
    for w in words:
        if current and (len(current) >= max_words or w.start - current[-1].end > MAX_GAP):
            chunks.append(current)
            current = []
        current.append(w)
        if w.text.rstrip()[-1:] in ".!?;:":
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


def caption_states(words: List[Word], max_words: int, total: float) -> List[Tuple[float, float, List[str], int]]:
    """Retorna (início, fim, palavras do bloco, índice destacado) cobrindo a timeline sem sobreposição."""
    states = []
    chunks = chunk_words(words, max_words)
    for ci, chunk in enumerate(chunks):
        texts = [w.text for w in chunk]
        chunk_end = chunk[-1].end + 0.15
        if ci + 1 < len(chunks):
            chunk_end = min(chunk_end, chunks[ci + 1][0].start)
        for wi, w in enumerate(chunk):
            end = chunk[wi + 1].start if wi + 1 < len(chunk) else chunk_end
            if end > w.start:
                states.append((w.start, min(end, total), texts, wi))
    return states


class CaptionRenderer:
    def __init__(self, size: Tuple[int, int], vertical: bool) -> None:
        cfg = settings.config()["captions"]
        self.width, self.height = size
        self.vertical = vertical
        self.max_words = cfg["words_per_chunk"]["vertical" if vertical else "landscape"]
        font_size = int(self.width * (0.08 if vertical else 0.048))
        self.font = self._load_font(cfg.get("font"), font_size)
        self.stroke = max(3, font_size // 12)
        self.color = cfg.get("color", "#FFFFFF")
        self.highlight = cfg.get("highlight", "#FFD60A")
        self.stroke_color = cfg.get("stroke_color", "#000000")

    @staticmethod
    def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
        for candidate in [path, "/System/Library/Fonts/Supplemental/Impact.ttf", "DejaVuSans-Bold.ttf"]:
            if not candidate:
                continue
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
        return ImageFont.load_default(size=size)

    def render(self, texts: List[str], active: int, out: Path) -> None:
        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        words = [t.upper() for t in texts]
        space = draw.textlength(" ", font=self.font)
        # Área segura do Reels/TikTok: botões ocupam ~16% à direita e a legenda do post o rodapé.
        # No vertical o texto fica entre 6% e 84% da largura; no horizontal, centralizado em 86%.
        left, right = (0.06, 0.84) if self.vertical else (0.07, 0.93)
        max_line = self.width * (right - left)
        center_x = self.width * (left + right) / 2

        # Quebra em linhas pela largura
        lines: List[List[int]] = [[]]
        line_w = 0.0
        for i, w in enumerate(words):
            ww = draw.textlength(w, font=self.font)
            if lines[-1] and line_w + space + ww > max_line:
                lines.append([])
                line_w = 0.0
            line_w += (space if lines[-1] else 0) + ww
            lines[-1].append(i)

        ascent, descent = self.font.getmetrics()
        line_h = int((ascent + descent) * 1.1)
        block_h = line_h * len(lines)
        # Vertical: um pouco abaixo do centro, bem acima da legenda do post (que cobre os ~25% de baixo)
        center_y = self.height * (0.58 if self.vertical else 0.84)
        y = int(center_y - block_h / 2)

        for line in lines:
            widths = [draw.textlength(words[i], font=self.font) for i in line]
            x = center_x - (sum(widths) + space * (len(line) - 1)) / 2
            for i, w in zip(line, widths):
                draw.text(
                    (x, y),
                    words[i],
                    font=self.font,
                    fill=self.highlight if i == active else self.color,
                    stroke_width=self.stroke,
                    stroke_fill=self.stroke_color,
                )
                x += w + space
            y += line_h
        img.save(out, optimize=True)

    def build_track(self, words: List[Word], total: float, out_dir: Path) -> Path:
        """Gera os PNGs e o arquivo de lista do concat demuxer. Retorna o caminho da lista."""
        out_dir.mkdir(parents=True, exist_ok=True)
        blank = out_dir / "blank.png"
        Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0)).save(blank)

        entries: List[Tuple[Path, float]] = []
        t = 0.0
        for n, (start, end, texts, active) in enumerate(caption_states(words, self.max_words, total)):
            if start - t > 0.01:
                entries.append((blank, start - t))
            png = out_dir / f"cap_{n:05d}.png"
            self.render(texts, active, png)
            entries.append((png, end - start))
            t = end
        if total - t > 0.01:
            entries.append((blank, total - t))

        lines = ["ffconcat version 1.0"]
        for p, d in entries:
            lines.append(f"file '{p.resolve().as_posix()}'")
            lines.append(f"duration {d:.3f}")
        # O demuxer ignora a duração do último item; repetir garante que ele apareça.
        lines.append(f"file '{entries[-1][0].resolve().as_posix()}'")
        list_file = out_dir / "captions.txt"
        list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return list_file
