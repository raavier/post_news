"""Geração do texto do post (PT-BR) via Google Gemini (tier gratuito).

Usa a API REST do Gemini para não depender de SDK pesado.
"""
from __future__ import annotations

import json
import re

import requests

from . import config
from .feed import Entry


def _load_template(path=None) -> str:
    return (path or config.PROMPT_TEMPLATE_PATH).read_text(encoding="utf-8")


def build_prompt(entry: Entry) -> str:
    return _load_template().format(
        brand=entry.brand,
        tag=entry.tag or entry.brand,
        title=entry.title,
        summary=entry.summary or "(sem resumo no feed)",
        published=entry.published or "(não informada)",
        link=entry.link or "(sem link)",
    )


def build_revision_prompt(entry: Entry, current_post: str, feedback: str) -> str:
    """Monta o prompt que pede ao Gemini para reescrever o post aplicando o feedback."""
    return _load_template(config.REVISE_TEMPLATE_PATH).format(
        brand=entry.brand,
        tag=entry.tag or entry.brand,
        title=entry.title,
        summary=entry.summary or "(sem resumo no feed)",
        current_post=current_post.strip() or "(vazio)",
        feedback=feedback.strip(),
    )


def build_carousel_prompt(entry: Entry) -> str:
    return _load_template(config.CAROUSEL_TEMPLATE_PATH).format(
        brand=entry.brand,
        tag=entry.tag or entry.brand,
        title=entry.title,
        summary=entry.summary or "(sem resumo no feed)",
        published=entry.published or "(não informada)",
        link=entry.link or "(sem link)",
        min_slides=config.CAROUSEL_MIN_SLIDES,
        max_slides=config.CAROUSEL_MAX_SLIDES,
    )


def _parse_slides(raw: str) -> list[dict]:
    """Extrai a lista de slides do JSON devolvido pelo modelo.

    Tolerante a cercas de código e a texto em volta: pega do primeiro '{' ao
    último '}'. Normaliza cada slide para {'title', 'body'} (strings).
    """
    text = raw.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise RuntimeError(f"Resposta do carrossel não contém JSON: {raw[:300]}")
    data = json.loads(text[start : end + 1])
    raw_slides = data.get("slides") if isinstance(data, dict) else data
    if not isinstance(raw_slides, list) or not raw_slides:
        raise RuntimeError(f"JSON do carrossel sem lista 'slides': {raw[:300]}")
    slides: list[dict] = []
    for s in raw_slides:
        if not isinstance(s, dict):
            continue
        slides.append(
            {"title": str(s.get("title", "")).strip(), "body": str(s.get("body", "")).strip()}
        )
    slides = [s for s in slides if s["title"] or s["body"]]
    if not slides:
        raise RuntimeError(f"JSON do carrossel sem slides úteis: {raw[:300]}")
    return slides[: config.CAROUSEL_MAX_SLIDES]


def generate_carousel_slides(entry: Entry) -> list[dict]:
    """Gera os slides do carrossel (lista de {'title','body'}) via Gemini/Databricks."""
    return _parse_slides(_generate(build_carousel_prompt(entry)))


def _call_gemini(prompt: str) -> str:
    """Chama o Gemini com um prompt e devolve o texto gerado (já validado/strip)."""
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


def _call_databricks(prompt: str) -> str:
    """Fallback: endpoint OpenAI-compatible do Databricks Model Serving."""
    url = f"{config.DATABRICKS_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": config.DATABRICKS_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024,
        "temperature": 0.7,
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {config.databricks_token()}"},
        json=payload,
        timeout=config.HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError) as exc:  # pragma: no cover - resposta inesperada
        raise RuntimeError(f"Resposta inesperada do Databricks: {data}") from exc
    if not text:
        raise RuntimeError(f"Databricks retornou texto vazio: {data}")
    return text


# Contador de chamadas ao fallback nesta execução (controle de custo por run).
_databricks_calls = 0


def _generate(prompt: str) -> str:
    """Gera com o Gemini; se falhar, cai para o Databricks (limitado por execução)."""
    global _databricks_calls
    try:
        return _call_gemini(prompt)
    except Exception as exc:
        if not config.databricks_enabled() or _databricks_calls >= config.DATABRICKS_MAX_CALLS:
            raise
        _databricks_calls += 1
        print(
            f"[fallback] Gemini falhou ({exc}); usando Databricks "
            f"({_databricks_calls}/{config.DATABRICKS_MAX_CALLS})."
        )
        return _call_databricks(prompt)


def generate_post_text(entry: Entry) -> str:
    """Texto do post (Gemini, com fallback para o Databricks)."""
    return _generate(build_prompt(entry))


def revise_post_text(entry: Entry, current_post: str, feedback: str) -> str:
    """Reescreve o post atual aplicando o feedback (Gemini, com fallback Databricks)."""
    return _generate(build_revision_prompt(entry, current_post, feedback))
