"""Geração do texto do post (PT-BR) via Google Gemini (tier gratuito).

Usa a API REST do Gemini para não depender de SDK pesado.
"""
from __future__ import annotations

import requests

from . import config
from .feed import Entry


def _load_template() -> str:
    return config.PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")


def build_prompt(entry: Entry) -> str:
    template = _load_template()
    return template.format(
        platform=entry.platform,
        title=entry.title,
        summary=entry.summary or "(sem resumo no feed)",
        published=entry.published or "(não informada)",
        link=entry.link or "(sem link)",
    )


def generate_post_text(entry: Entry) -> str:
    """Chama o Gemini e devolve o texto do post pronto para o LinkedIn."""
    prompt = build_prompt(entry)
    url = f"{config.GEMINI_API_BASE}/models/{config.GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        # Folga generosa: os modelos Gemini 2.5 consomem "thinking tokens" do
        # orçamento de saída; 1024 poderia retornar MAX_TOKENS com texto vazio.
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
    }
    resp = requests.post(
        url,
        params={"key": config.gemini_api_key()},
        json=payload,
        timeout=config.HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        candidate = data["candidates"][0]
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError) as exc:  # pragma: no cover - resposta inesperada
        raise RuntimeError(f"Resposta inesperada do Gemini: {data}") from exc
    if not text:
        reason = candidate.get("finishReason", "?")
        raise RuntimeError(f"Gemini retornou texto vazio (finishReason={reason}): {data}")
    return text
