"""Tema visual compartilhado (HTML/CSS) do card e do carrossel.

Identidade inspirada nos posts educativos da Databricks: fundo claro, "blobs"
coral nos cantos, títulos com termos destacados em coral, cards de código com
syntax highlighting e o nome da marca em texto no rodapé.

A renderização usa WeasyPrint (HTML -> PDF). Para o card único (PNG), o PDF de
1 página é rasterizado com PyMuPDF. Os imports dessas libs são TARDIOS para o
módulo continuar importável (ex.: na publicação) sem elas instaladas.
"""
from __future__ import annotations

import html
import re

# Paleta (tema claro + acento coral).
CORAL = "#FF5A47"      # blobs, destaques, marca
INK = "#0B1B2B"        # títulos (navy quase preto)
BODY = "#3A4656"       # texto de apoio
CODE_BG = "#0E1726"    # card de código (navy escuro)
CODE_FG = "#E6EDF6"    # texto do código (fallback)
WHITE = "#FFFFFF"

FONT_STACK = "'DejaVu Sans', 'Arial', sans-serif"
MONO_STACK = "'DejaVu Sans Mono', monospace"

# Marcação de destaque que o modelo insere no texto: [[termo]] -> coral.
_HL_RE = re.compile(r"\[\[(.+?)\]\]", re.DOTALL)


def highlight_markup(text: str) -> str:
    """Escapa o texto e converte [[termo]] em <span class='hl'>termo</span>."""
    escaped = html.escape(text or "")
    escaped = _HL_RE.sub(lambda m: f'<span class="hl">{m.group(1)}</span>', escaped)
    return escaped.replace("\n", "<br>")


def _pygments_css() -> str:
    try:
        from pygments.formatters import HtmlFormatter
    except Exception:  # pragma: no cover - pygments ausente
        return ""
    return HtmlFormatter(style="monokai").get_style_defs(".codehl")


def code_html(code: str, lang: str = "") -> str:
    """Renderiza um card de código com header '%lang' e syntax highlighting."""
    code = (code or "").strip("\n")
    header = f'<div class="code-head">%{html.escape(lang)}</div>' if lang else ""
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import get_lexer_by_name, guess_lexer
        from pygments.util import ClassNotFound

        try:
            lexer = get_lexer_by_name(lang or "text", stripall=False)
        except ClassNotFound:
            try:
                lexer = guess_lexer(code)
            except Exception:
                lexer = get_lexer_by_name("text")
        body = highlight(code, lexer, HtmlFormatter(nowrap=True))
    except Exception:  # pragma: no cover - fallback sem pygments
        body = html.escape(code)
    return f'<div class="code-card">{header}<pre class="codehl">{body}</pre></div>'


def theme_css() -> str:
    """CSS comum (fontes, destaque, blobs, card de código) usado pelas duas telas."""
    return f"""
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{ font-family: {FONT_STACK}; color: {INK}; background: {WHITE}; }}
    .surface {{ position: relative; overflow: hidden; background: {WHITE}; }}
    .blob {{ position: absolute; background: {CORAL}; border-radius: 50%; z-index: 0; }}
    .content {{ position: relative; z-index: 1; height: 100%; display: flex; flex-direction: column; }}
    .hl {{ color: {CORAL}; }}
    .eyebrow {{ color: {CORAL}; font-weight: bold; letter-spacing: 1px; }}
    .brandmark {{ color: {CORAL}; font-weight: bold; }}
    .title {{ color: {INK}; font-weight: bold; line-height: 1.12; }}
    .body {{ color: {BODY}; line-height: 1.4; }}
    .code-card {{
        background: {CODE_BG}; border-radius: 18px; padding: 22px 26px;
        box-shadow: 0 10px 30px rgba(8, 18, 34, 0.18);
    }}
    .code-head {{ color: #7DA0C4; font-family: {MONO_STACK}; font-size: 0.7em; margin-bottom: 8px; }}
    .codehl {{ color: {CODE_FG}; font-family: {MONO_STACK}; white-space: pre-wrap; word-break: break-word; }}
    {_pygments_css()}
    """


def html_to_pdf(html_str: str) -> bytes:
    """Renderiza HTML em PDF (bytes) via WeasyPrint."""
    from weasyprint import HTML  # import tardio: exige libs nativas (Pango/Cairo)

    return HTML(string=html_str).write_pdf()


def pdf_to_png(pdf_bytes: bytes) -> bytes:
    """Rasteriza a 1ª página de um PDF em PNG nas dimensões exatas em px (96 dpi)."""
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(96 / 72, 96 / 72), alpha=False)
    return pix.tobytes("png")


def render_png_from_html(html_str: str) -> bytes:
    """Atalho HTML -> PDF -> PNG para o card único."""
    return pdf_to_png(html_to_pdf(html_str))
