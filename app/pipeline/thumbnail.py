"""Thumbnail: frame do vídeo escurecido + texto grande de impacto."""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from app.pipeline import ffmpeg
from app.pipeline.captions import CaptionRenderer


def make_thumbnail(video: Path, text: str, out: Path, vertical: bool, at: float = 1.5) -> Path:
    size: Tuple[int, int] = (1080, 1920) if vertical else (1280, 720)
    frame = out.with_name("thumb_frame.jpg")
    ffmpeg.run(["-ss", f"{at:.2f}", "-i", video, "-frames:v", "1", "-q:v", "2", frame])

    img = Image.open(frame).convert("RGB")
    img = _cover(img, size)
    img = ImageEnhance.Contrast(img).enhance(1.25)
    img = ImageEnhance.Brightness(img).enhance(0.7)

    # Gradiente escuro onde fica o texto
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    w, h = size
    top = int(h * (0.45 if vertical else 0.35))
    for y in range(top, h):
        alpha = int(220 * (y - top) / (h - top))
        od.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), overlay)

    font_size = int(w * (0.12 if vertical else 0.105))
    font = CaptionRenderer._load_font("/System/Library/Fonts/Supplemental/Impact.ttf", font_size)
    draw = ImageDraw.Draw(img)
    words = text.upper().split()
    lines, line = [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if line and draw.textlength(trial, font=font) > w * 0.9:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)

    ascent, descent = font.getmetrics()
    lh = int((ascent + descent) * 1.05)
    y = int(h * (0.62 if vertical else 0.92)) - lh * len(lines)
    stroke = max(4, font_size // 10)
    for i, ln in enumerate(lines):
        lw = draw.textlength(ln, font=font)
        color = "#FFD60A" if i == len(lines) - 1 else "#FFFFFF"
        # Sombra difusa
        shadow = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).text(((w - lw) / 2 + 6, y + 6), ln, font=font, fill=(0, 0, 0, 200))
        img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(8)))
        draw = ImageDraw.Draw(img)
        draw.text(((w - lw) / 2, y), ln, font=font, fill=color, stroke_width=stroke, stroke_fill="#000000")
        y += lh

    img.convert("RGB").save(out, quality=92)
    frame.unlink(missing_ok=True)
    return out


def _cover(img: Image.Image, size: Tuple[int, int]) -> Image.Image:
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    left = (img.width - tw) // 2
    top = (img.height - th) // 2
    return img.crop((left, top, left + tw, top + th))
