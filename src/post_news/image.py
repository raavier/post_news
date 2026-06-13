"""Geração do card de imagem LOCALMENTE com Pillow (custo 0, sem API externa).

Antes usávamos o Pollinations, mas ele passou a retornar HTTP 402 (Payment
Required) — deixou de ser gratuito de forma confiável. Renderizar o card aqui
elimina dependência de rede, rate limits e custos, e é determinístico.

Como o repositório é público, o PNG versionado em drafts/ renderiza inline na
issue via raw.githubusercontent.com.
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import config
from .feed import Entry

# Cores (tema escuro com acento vermelho estilo Databricks).
BG_TOP = (15, 20, 32)
BG_BOTTOM = (28, 38, 60)
ACCENT = (255, 54, 33)       # vermelho Databricks
TEXT = (245, 247, 250)
MUTED = (150, 162, 184)

_FONT_CANDIDATES = {
    "bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ],
    "regular": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
    ],
}


def _font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES.get(kind, []):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def card_filename(entry: Entry) -> str:
    return entry.key.replace(":", "_").replace("/", "_") + ".png"


def card_path(entry: Entry) -> Path:
    return config.DRAFTS_DIR / card_filename(entry)


def raw_url_for(entry: Entry) -> str:
    """URL raw (pública) do card no GitHub, para embutir no markdown da issue."""
    repo = os.environ.get("GITHUB_REPOSITORY") or "raavier/post_news"
    branch = os.environ.get("POST_NEWS_IMAGE_BRANCH") or "main"
    return f"https://raw.githubusercontent.com/{repo}/{branch}/drafts/{card_filename(entry)}"


def _gradient(w: int, h: int) -> Image.Image:
    base = Image.new("RGB", (w, h), BG_TOP)
    top = Image.new("RGB", (w, h), BG_TOP)
    bottom = Image.new("RGB", (w, h), BG_BOTTOM)
    mask = Image.new("L", (w, h))
    mask_data = [int(255 * (y / h)) for y in range(h) for _ in range(w)]
    mask.putdata(mask_data)
    base = Image.composite(bottom, top, mask)
    return base


def render_card(entry: Entry) -> bytes:
    """Renderiza o card e devolve os bytes PNG."""
    w, h = config.IMAGE_WIDTH, config.IMAGE_HEIGHT
    img = _gradient(w, h)
    draw = ImageDraw.Draw(img)

    margin = 70
    # Barra de acento vertical à esquerda.
    draw.rectangle([0, 0, 12, h], fill=ACCENT)

    # Rótulo superior.
    label_font = _font("bold", 30)
    draw.text((margin, 60), "DATABRICKS  •  NOVIDADES", font=label_font, fill=ACCENT)

    # Badge de plataforma (AWS/Azure) no canto superior direito.
    badge_font = _font("bold", 26)
    badge = entry.platform.upper()
    bbox = draw.textbbox((0, 0), badge, font=badge_font)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    bx0, by0 = w - margin - bw - 32, 56
    draw.rounded_rectangle([bx0, by0, bx0 + bw + 32, by0 + bh + 22], radius=10, fill=(40, 52, 78))
    draw.text((bx0 + 16, by0 + 8), badge, font=badge_font, fill=TEXT)

    # Título (manchete), com quebra de linha e tamanho de fonte adaptativo.
    title = entry.title
    title_size = 70 if len(title) < 60 else (58 if len(title) < 90 else 46)
    title_font = _font("bold", title_size)
    wrap_chars = max(18, int(w * 0.92 / (title_size * 0.56)))
    lines = textwrap.wrap(title, width=wrap_chars)[:5]
    y = 160
    for line in lines:
        draw.text((margin, y), line, font=title_font, fill=TEXT)
        y += int(title_size * 1.18)

    # Rodapé.
    footer_font = _font("regular", 26)
    date = (entry.published or "")[:10]
    footer = f"Saiba mais na documentação  •  {date}".strip(" •")
    draw.text((margin, h - 70), footer, font=footer_font, fill=MUTED)

    from io import BytesIO

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def save_card(entry: Entry) -> Path:
    """Renderiza e salva o card em drafts/, retornando o caminho."""
    config.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    path = card_path(entry)
    path.write_bytes(render_card(entry))
    return path


def load_card_bytes(filename: str) -> bytes:
    """Lê os bytes de um card já salvo (usado na publicação)."""
    return (config.DRAFTS_DIR / filename).read_bytes()


def download_image(url: str) -> bytes:
    """Fallback: baixa os bytes do card pela raw URL (repo público)."""
    import requests

    resp = requests.get(
        url, headers={"User-Agent": config.HTTP_USER_AGENT}, timeout=max(config.HTTP_TIMEOUT, 60)
    )
    resp.raise_for_status()
    return resp.content


def _main() -> None:
    """Diagnóstico local: renderiza um card de teste."""
    import sys

    title = sys.argv[1] if len(sys.argv) > 1 else "Databricks Genie app in Microsoft Teams (Beta)"
    entry = Entry(
        key="2026-06-10:test-card", title=title, summary="", link="",
        published="2026-06-10", platform="Azure",
    )
    path = save_card(entry)
    print(f"Card salvo: {path} ({path.stat().st_size} bytes)")
    print(f"Raw URL (quando versionado): {raw_url_for(entry)}")


if __name__ == "__main__":
    _main()
