"""Geração do card de imagem via Pollinations.ai (gratuito, sem chave).

A imagem é servida em uma URL pública e determinística (usamos um `seed`
derivado da chave da novidade), então:
- a mesma URL é embutida na issue do GitHub para você pré-visualizar;
- no momento de publicar, baixamos os bytes da MESMA URL para enviar ao LinkedIn,
  garantindo que a imagem aprovada é exatamente a publicada.
"""
from __future__ import annotations

import zlib
from urllib.parse import quote

import requests

from . import config
from .feed import Entry


def _seed_from_key(key: str) -> int:
    # Determinístico e estável entre execuções (não depende do hash do Python).
    return zlib.crc32(key.encode("utf-8")) % 1_000_000


def build_image_prompt(entry: Entry) -> str:
    """Monta o prompt visual do card a partir da manchete."""
    return (
        f"Clean modern professional tech announcement card about Databricks. "
        f"Headline: '{entry.title}'. "
        "Minimalist corporate style, data and AI theme, abstract lakehouse and "
        "data flow graphics, red and dark-blue accents, lots of negative space, "
        "high quality, flat vector illustration, no text watermark, no logos of other companies."
    )


def build_image_url(entry: Entry) -> str:
    """URL pública e determinística da imagem (embutível em markdown)."""
    prompt = build_image_prompt(entry)
    seed = _seed_from_key(entry.key)
    encoded = quote(prompt, safe="")
    return (
        f"{config.POLLINATIONS_BASE}/{encoded}"
        f"?width={config.IMAGE_WIDTH}&height={config.IMAGE_HEIGHT}"
        f"&seed={seed}&nologo=true&model=flux"
    )


def download_image(url: str) -> bytes:
    """Baixa os bytes da imagem (usado na hora de publicar no LinkedIn)."""
    resp = requests.get(
        url,
        headers={"User-Agent": config.HTTP_USER_AGENT},
        timeout=max(config.HTTP_TIMEOUT, 60),  # geração pode demorar alguns segundos
    )
    resp.raise_for_status()
    return resp.content


def _main() -> None:
    """Diagnóstico local: gera a URL e salva o PNG para uma manchete de teste."""
    import sys

    title = sys.argv[1] if len(sys.argv) > 1 else "Databricks lança nova integração com Genie"
    entry = Entry(
        key="test:" + title, title=title, summary="", link="", published="", platform="AWS"
    )
    url = build_image_url(entry)
    print("URL da imagem:\n", url, "\n")
    data = download_image(url)
    config.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    out = config.DRAFTS_DIR / "test_card.png"
    out.write_bytes(data)
    print(f"Salvo: {out} ({len(data)} bytes)")


if __name__ == "__main__":
    _main()
