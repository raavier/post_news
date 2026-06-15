"""Geração do card de imagem (PNG) LOCALMENTE, sem API externa.

Antes desenhávamos com Pillow; agora montamos HTML/CSS e renderizamos com
WeasyPrint (PDF) + PyMuPDF (rasteriza para PNG). Isso unifica a identidade
visual com o carrossel (ver render.py): tema claro, acento coral, título com
destaques. Continua determinístico, custo 0 e sem rede.

Como o repositório é público, o PNG versionado em drafts/ renderiza inline na
issue via raw.githubusercontent.com.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import config, render
from .feed import Entry, iso_date


def card_filename(entry: Entry) -> str:
    # Sanitiza para um nome de arquivo/URL seguro (sem espaços, vírgulas, etc.).
    raw = entry.key.replace(":", "_").replace("/", "_")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-_")
    return f"{safe}.png"


def card_path(entry: Entry) -> Path:
    return config.DRAFTS_DIR / card_filename(entry)


def raw_url_for(entry: Entry) -> str:
    """URL raw (pública) do card no GitHub, para embutir no markdown da issue."""
    repo = os.environ.get("GITHUB_REPOSITORY") or "raavier/post_news"
    branch = os.environ.get("POST_NEWS_IMAGE_BRANCH") or "main"
    return f"https://raw.githubusercontent.com/{repo}/{branch}/drafts/{card_filename(entry)}"


def build_html(entry: Entry) -> str:
    w, h = config.IMAGE_WIDTH, config.IMAGE_HEIGHT
    title = render.highlight_markup(entry.title)
    eyebrow = render.highlight_markup(entry.brand.upper())
    badge = render.highlight_markup((entry.tag or entry.brand).upper())
    date = iso_date(entry.published) or ""
    brand = render.highlight_markup(entry.brand.lower())
    css = render.theme_css() + f"""
    @page {{ size: {w}px {h}px; margin: 0; }}
    .surface {{ width: {w}px; height: {h}px; }}
    .content {{ padding: 56px 70px; }}
    .blob.tl {{ width: 300px; height: 300px; top: -210px; left: -110px; }}
    .blob.br {{ width: 320px; height: 320px; bottom: -210px; right: -110px; }}
    .top {{ display: flex; justify-content: flex-end; align-items: center; min-height: 44px; }}
    .badge {{ background: {render.INK}; color: {render.WHITE}; font-size: 22px;
              font-weight: bold; padding: 7px 16px; border-radius: 10px; }}
    .middle {{ flex: 1; display: flex; flex-direction: column; justify-content: center; }}
    .kicker {{ color: {render.CORAL}; font-weight: bold; letter-spacing: 1px;
               font-size: 24px; margin-bottom: 16px; }}
    .title {{ font-size: 64px; }}
    .foot {{ display: flex; justify-content: space-between; align-items: center; }}
    .foot .brandmark {{ font-size: 30px; }}
    .foot .meta {{ color: {render.BODY}; font-size: 24px; }}
    """
    body = (
        '<div class="surface"><div class="blob tl"></div><div class="blob br"></div>'
        '<div class="content">'
        f'<div class="top"><span class="badge">{badge}</span></div>'
        f'<div class="middle"><div class="kicker">{eyebrow} • NOVIDADES</div>'
        f'<div class="title">{title}</div></div>'
        f'<div class="foot"><span class="brandmark">{brand}</span>'
        f'<span class="meta">{date}</span></div>'
        "</div></div>"
    )
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"


def render_card(entry: Entry) -> bytes:
    """Renderiza o card e devolve os bytes PNG."""
    return render.render_png_from_html(build_html(entry))


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

    title = sys.argv[1] if len(sys.argv) > 1 else "Databricks Genie app no Microsoft Teams (Beta)"
    entry = Entry(
        key="2026-06-10:test-card", title=title, summary="", link="",
        published="2026-06-10", brand="Databricks", tag="Azure",
    )
    path = save_card(entry)
    print(f"Card salvo: {path} ({path.stat().st_size} bytes)")
    print(f"Raw URL (quando versionado): {raw_url_for(entry)}")


if __name__ == "__main__":
    _main()
