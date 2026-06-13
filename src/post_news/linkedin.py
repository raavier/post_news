"""Publicação no LinkedIn via Posts API (escopo w_member_social, tier gratuito).

Fluxo:
1. initializeUpload na Images API -> recebe uploadUrl + URN da imagem.
2. PUT dos bytes da imagem no uploadUrl.
3. POST /rest/posts referenciando o URN da imagem.

Observação sobre marcar a Databricks: a menção real (@Databricks como entidade)
exige o URN da organização e anotações específicas na API. Por padrão marcamos a
empresa por texto + hashtag #Databricks (como no exemplo aprovado). A menção por
entidade pode ser adicionada depois informando o URN da organização.
"""
from __future__ import annotations

import requests

from . import config


def _rest_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.linkedin_token()}",
        "LinkedIn-Version": config.LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }


def upload_image(image_bytes: bytes, owner_urn: str) -> str:
    """Sobe a imagem e retorna o URN (urn:li:image:...)."""
    init_resp = requests.post(
        f"{config.LINKEDIN_API_BASE}/rest/images?action=initializeUpload",
        headers=_rest_headers(),
        json={"initializeUploadRequest": {"owner": owner_urn}},
        timeout=config.HTTP_TIMEOUT,
    )
    init_resp.raise_for_status()
    value = init_resp.json()["value"]
    upload_url = value["uploadUrl"]
    image_urn = value["image"]

    put_resp = requests.put(
        upload_url,
        headers={"Authorization": f"Bearer {config.linkedin_token()}"},
        data=image_bytes,
        timeout=max(config.HTTP_TIMEOUT, 60),
    )
    put_resp.raise_for_status()
    return image_urn


def create_post(text: str, image_urn: str | None, author_urn: str, alt_text: str = "Card da novidade") -> str:
    """Cria o post e retorna a URL pública do update."""
    body: dict = {
        "author": author_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if image_urn:
        body["content"] = {"media": {"id": image_urn, "altText": alt_text}}

    resp = requests.post(
        f"{config.LINKEDIN_API_BASE}/rest/posts",
        headers=_rest_headers(),
        json=body,
        timeout=config.HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    # O URN do post volta no header (x-restli-id / x-linkedin-id).
    post_urn = resp.headers.get("x-restli-id") or resp.headers.get("x-linkedin-id") or ""
    return post_url(post_urn)


def post_url(post_urn: str) -> str:
    if not post_urn:
        return ""
    return f"https://www.linkedin.com/feed/update/{post_urn}/"


def publish(text: str, image_bytes: bytes | None) -> str:
    """Helper de alto nível: sobe a imagem (se houver) e publica o post."""
    author = config.linkedin_author_urn()
    image_urn = upload_image(image_bytes, author) if image_bytes else None
    return create_post(text, image_urn, author)
