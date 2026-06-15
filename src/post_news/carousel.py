"""Renderização do carrossel (documento PDF) para o LinkedIn.

O carrossel é o formato de maior dwell time em 2026. Montamos HTML/CSS e
renderizamos com WeasyPrint — controle tipográfico real com pouco código.

Identidade visual (tema claro + acento coral + código com syntax highlighting)
vem de render.py, compartilhada com o card único. O número de slides é
ADAPTATIVO: vem da lista do modelo (generate.generate_carousel_slides).

Cada slide pode ter: title (com destaques [[...]]), body, e opcionalmente
code+lang (vira um card de código estilo notebook). Slide 0 = capa/gancho;
último = pergunta/fecho; meio = pontos concretos.

O PDF é gerado na detecção e versionado em drafts/ (repo público), como o card.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import config, render
from .feed import Entry


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
    kind = "cover" if is_cover else ("closing" if is_last else "point")

    title = render.highlight_markup(slide.get("title", ""))
    body = render.highlight_markup(slide.get("body", ""))
    code = (slide.get("code") or "").strip()
    badge = render.highlight_markup((entry.tag or entry.brand).upper())
    counter = f"{index + 1}/{total}"

    parts = [f'<section class="surface slide {kind}">']
    parts.append('<div class="blob tl"></div><div class="blob br"></div>')
    parts.append('<div class="content">')
    parts.append(f'<div class="top"><span class="badge">{badge}</span></div>')
    parts.append('<div class="middle">')
    parts.append(f'<div class="kicker">{render.highlight_markup(entry.brand.upper())} • NOVIDADES</div>')
    if title:
        parts.append(f'<div class="title">{title}</div>')
    if code:
        parts.append(render.code_html(code, slide.get("lang", "")))
    if body:
        parts.append(f'<div class="body">{body}</div>')
    parts.append("</div>")
    hint = "deslize →" if is_cover else ("" if is_last else "")
    parts.append(
        f'<div class="foot"><span class="brandmark">{render.highlight_markup(entry.brand.lower())}</span>'
        f'<span class="meta">{hint}&nbsp;&nbsp;{counter}</span></div>'
    )
    parts.append("</div></section>")
    return "".join(parts)


def build_html(slides: list[dict], entry: Entry) -> str:
    w, h = config.CAROUSEL_WIDTH, config.CAROUSEL_HEIGHT
    total = len(slides)
    body_html = "".join(_slide_html(s, index=i, total=total, entry=entry) for i, s in enumerate(slides))
    css = render.theme_css() + f"""
    @page {{ size: {w}px {h}px; margin: 0; }}
    .slide {{ width: {w}px; height: {h}px; page-break-after: always; }}
    .slide:last-child {{ page-break-after: auto; }}
    .content {{ padding: 86px 80px; }}
    .blob.tl {{ width: 440px; height: 440px; top: -300px; left: -160px; }}
    .blob.br {{ width: 480px; height: 480px; bottom: -320px; right: -150px; }}
    .top {{ display: flex; justify-content: flex-end; align-items: center; min-height: 56px; }}
    .badge {{ background: {render.INK}; color: {render.WHITE}; font-size: 24px;
              font-weight: bold; padding: 8px 18px; border-radius: 12px; }}
    .middle {{ flex: 1; display: flex; flex-direction: column; justify-content: center; }}
    .kicker {{ color: {render.CORAL}; font-weight: bold; letter-spacing: 1px;
               font-size: 28px; margin-bottom: 22px; }}
    .title {{ font-size: 60px; }}
    .cover .title {{ font-size: 88px; }}
    .closing .title {{ font-size: 64px; }}
    .body {{ font-size: 42px; margin-top: 30px; }}
    .code-card {{ margin-top: 36px; }}
    .codehl {{ font-size: 30px; line-height: 1.45; }}
    .code-head {{ font-size: 22px; }}
    .foot {{ display: flex; justify-content: space-between; align-items: center;
             font-size: 28px; }}
    .foot .brandmark {{ font-size: 34px; }}
    .foot .meta {{ color: {render.BODY}; }}
    """
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body_html}</body></html>"


def render_pdf(slides: list[dict], entry: Entry) -> bytes:
    """Renderiza os slides num único PDF e devolve os bytes."""
    return render.html_to_pdf(build_html(slides, entry))


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

    title = sys.argv[1] if len(sys.argv) > 1 else "Databricks lançou [[Auto Time-to-live]]"
    entry = Entry(
        key="2026-06-10:test-carousel", title=title, summary="", link="",
        published="2026-06-10", brand="Databricks", tag="Azure",
    )
    slides = [
        {"title": title, "body": "Para tabelas [[Delta e Iceberg]] gerenciadas no Unity Catalog."},
        {"title": "Como ativar",
         "code": "ALTER TABLE demo.events\nDELETE ROWS 30 DAYS AFTER event_time;", "lang": "sql",
         "body": "Uma propriedade na tabela e pronto."},
        {"title": "O que muda", "body": "Sem [[deletes]] manuais. Sem [[vacuum]] manual."},
        {"title": "E você?", "body": "Onde isso economizaria trabalho no seu pipeline?"},
    ]
    path = save_carousel(entry, slides)
    print(f"PDF salvo: {path} ({path.stat().st_size} bytes, {len(slides)} slides)")
    print(f"Raw URL (quando versionado): {raw_url_for(entry)}")


if __name__ == "__main__":
    _main()
