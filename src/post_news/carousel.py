"""Renderização do carrossel (documento PDF) para o LinkedIn.

O carrossel é o formato de maior dwell time em 2026. Em vez de desenhar com
Pillow, montamos HTML/CSS e renderizamos com WeasyPrint — isso dá controle
tipográfico real (quebra de linha, hierarquia, espaçamento) com pouco código.

Cada slide é uma página vertical (1080×1350, 4:5) combinada num único PDF. O
número de slides é ADAPTATIVO: vem da lista produzida pelo modelo (ver
generate.generate_carousel_slides), não é fixo.

O PDF é gerado na fase de detecção e versionado em drafts/ (repo público),
exatamente como o card PNG; a publicação apenas carrega os bytes.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from . import config
from .feed import Entry, iso_date

# Mesma paleta do card PNG (tema escuro, acento vermelho estilo Databricks).
BG_TOP = "#0f1420"
BG_BOTTOM = "#1c263c"
ACCENT = "#ff3621"
TEXT = "#f5f7fa"
MUTED = "#96a2b8"


def doc_filename(entry: Entry) -> str:
    raw = entry.key.replace(":", "_").replace("/", "_")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-_")
    return f"{safe}.pdf"


def doc_path(entry: Entry) -> Path:
    return config.DRAFTS_DIR / doc_filename(entry)


def raw_url_for(entry: Entry) -> str:
    """URL raw (pública) do PDF no GitHub (referência/registro na issue)."""
    import os

    repo = os.environ.get("GITHUB_REPOSITORY") or "raavier/post_news"
    branch = os.environ.get("POST_NEWS_IMAGE_BRANCH") or "main"
    return f"https://raw.githubusercontent.com/{repo}/{branch}/drafts/{doc_filename(entry)}"


def _slide_html(slide: dict, *, index: int, total: int, entry: Entry) -> str:
    is_cover = index == 0
    is_last = index == total - 1
    kind = "cover" if is_cover else ("question" if is_last else "point")

    title = html.escape(slide.get("title", "")).replace("\n", "<br>")
    body = html.escape(slide.get("body", "")).replace("\n", "<br>")
    badge = html.escape((entry.tag or entry.brand).upper())
    counter = f"{index + 1}/{total}"

    parts = [f'<section class="slide {kind}">']
    parts.append(f'<div class="brand">{html.escape(entry.brand.upper())}  •  NOVIDADES</div>')
    parts.append(f'<div class="badge">{badge}</div>')
    parts.append('<div class="content">')
    if title:
        parts.append(f'<h1>{title}</h1>')
    if body:
        parts.append(f'<p>{body}</p>')
    parts.append("</div>")
    hint = "deslize →" if is_cover else ("&nbsp;" if is_last else "")
    parts.append(f'<div class="footer"><span>{html.escape(counter)}</span><span>{hint}</span></div>')
    parts.append("</section>")
    return "".join(parts)


def build_html(slides: list[dict], entry: Entry) -> str:
    w, h = config.CAROUSEL_WIDTH, config.CAROUSEL_HEIGHT
    total = len(slides)
    body_html = "".join(_slide_html(s, index=i, total=total, entry=entry) for i, s in enumerate(slides))
    css = f"""
    @page {{ size: {w}px {h}px; margin: 0; }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{ font-family: 'DejaVu Sans', 'Arial', sans-serif; color: {TEXT}; }}
    .slide {{
        position: relative;
        width: {w}px; height: {h}px;
        padding: 90px 80px;
        background: linear-gradient(160deg, {BG_TOP} 0%, {BG_BOTTOM} 100%);
        border-left: 16px solid {ACCENT};
        page-break-after: always;
        display: flex; flex-direction: column;
    }}
    .slide:last-child {{ page-break-after: auto; }}
    .brand {{ color: {ACCENT}; font-weight: bold; font-size: 30px; letter-spacing: 1px; }}
    .badge {{
        position: absolute; top: 80px; right: 80px;
        background: #28344e; color: {TEXT};
        font-size: 26px; font-weight: bold;
        padding: 10px 20px; border-radius: 12px;
    }}
    .content {{ flex: 1; display: flex; flex-direction: column; justify-content: center; }}
    h1 {{ font-size: 78px; line-height: 1.12; font-weight: bold; }}
    p {{ font-size: 46px; line-height: 1.4; margin-top: 36px; color: #dfe6f2; }}
    .cover h1 {{ font-size: 92px; }}
    .point h1 {{ font-size: 64px; color: {ACCENT}; }}
    .question h1 {{ font-size: 64px; }}
    .question p {{ color: {TEXT}; }}
    .footer {{
        display: flex; justify-content: space-between;
        color: {MUTED}; font-size: 28px;
    }}
    """
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body_html}</body></html>"


def render_pdf(slides: list[dict], entry: Entry) -> bytes:
    """Renderiza os slides num único PDF e devolve os bytes."""
    from weasyprint import HTML  # import tardio: só a renderização exige a lib nativa

    return HTML(string=build_html(slides, entry)).write_pdf()


def save_carousel(entry: Entry, slides: list[dict]) -> Path:
    """Renderiza e salva o PDF em drafts/, retornando o caminho."""
    config.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    path = doc_path(entry)
    path.write_bytes(render_pdf(slides, entry))
    return path


def load_doc_bytes(filename: str) -> bytes:
    """Lê os bytes de um PDF já salvo (usado na publicação)."""
    return (config.DRAFTS_DIR / filename).read_bytes()


def _main() -> None:
    """Diagnóstico local: gera um PDF de teste com slides fixos (sem chamar o modelo).

    Uso: python -m post_news.carousel "<título>"
    """
    import sys

    title = sys.argv[1] if len(sys.argv) > 1 else "Databricks Genie no Microsoft Teams (Beta)"
    entry = Entry(
        key="2026-06-10:test-carousel", title=title, summary="", link="",
        published="2026-06-10", brand="Databricks", tag="Azure",
    )
    slides = [
        {"title": title, "body": "O que muda na prática para quem usa o produto."},
        {"title": "O que é", "body": "Um recurso novo que resolve um problema concreto do dia a dia."},
        {"title": "Por que importa", "body": "Menos atrito, mais tempo no que interessa. Exemplo real de uso."},
        {"title": "E você?", "body": "Como isso encaixa no seu fluxo hoje?"},
    ]
    path = save_carousel(entry, slides)
    print(f"PDF salvo: {path} ({path.stat().st_size} bytes, {len(slides)} slides)")
    print(f"Raw URL (quando versionado): {raw_url_for(entry)}")


if __name__ == "__main__":
    _main()
