"""Publicação no LinkedIn via Posts API (escopo w_member_social, tier gratuito).

Fluxo:
1. initializeUpload na Images API -> recebe uploadUrl + URN da imagem.
2. PUT dos bytes da imagem no uploadUrl.
3. POST /rest/posts referenciando o URN da imagem.

Menção à @Databricks: se config.DATABRICKS_ORG_URN estiver definido, a primeira
ocorrência de "Databricks" no texto vira um link clicável usando a sintaxe de
"little text" do LinkedIn — @[Databricks](urn:li:organization:ID) — e os demais
caracteres reservados são escapados. Sem o URN, mantém só texto + hashtag.
"""
from __future__ import annotations

import re

import requests

from . import config


# Caracteres reservados do "little text" do commentary (escapados com \).
_RESERVED = set("\\|{}@[]()<>*_~")


def _escape_commentary(text: str) -> str:
    """Escapa reservados do little-text. Mantém '#' de hashtag (precedido de espaço),
    mas escapa '#' no meio de palavra/URL (fragmento), que viraria hashtag indevida."""
    out: list[str] = []
    prev = ""
    for ch in text:
        if ch in _RESERVED:
            out.append("\\" + ch)
        elif ch == "#":
            out.append("#" if (prev == "" or prev.isspace()) else "\\#")
        else:
            out.append(ch)
        prev = ch
    return "".join(out)


def format_commentary(text: str, org_urn: str = "") -> str:
    """Prepara o texto do post. Com org_urn, injeta a menção @Databricks e escapa o resto."""
    if not org_urn:
        return text
    escaped = _escape_commentary(text)
    mention = f"@[Databricks]({org_urn})"
    # Primeira ocorrência de "Databricks" que não seja hashtag (#Databricks) nem
    # parte de outra palavra. (count=1 -> só a primeira vira link.)
    pattern = re.compile(r"(?<![#\w])Databricks(?!\w)")
    escaped, _ = pattern.subn(mention, escaped, count=1)
    return escaped



def _rest_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.linkedin_token()}",
        "LinkedIn-Version": config.LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }


def _check(resp, contexto: str):
    """Levanta erro incluindo o CORPO da resposta do LinkedIn (essencial para diagnóstico)."""
    if resp.status_code >= 400:
        raise RuntimeError(
            f"{contexto} falhou: HTTP {resp.status_code}. "
            f"Resposta do LinkedIn: {resp.text[:1000]}"
        )
    return resp


def upload_image(image_bytes: bytes, owner_urn: str) -> str:
    """Sobe a imagem e retorna o URN (urn:li:image:...)."""
    init_resp = requests.post(
        f"{config.LINKEDIN_API_BASE}/rest/images?action=initializeUpload",
        headers=_rest_headers(),
        json={"initializeUploadRequest": {"owner": owner_urn}},
        timeout=config.HTTP_TIMEOUT,
    )
    _check(init_resp, "initializeUpload (LinkedIn-Version=" + config.LINKEDIN_VERSION + ")")
    value = init_resp.json()["value"]
    upload_url = value["uploadUrl"]
    image_urn = value["image"]

    put_resp = requests.put(
        upload_url,
        headers={
            "Authorization": f"Bearer {config.linkedin_token()}",
            "Content-Type": "application/octet-stream",
        },
        data=image_bytes,
        timeout=max(config.HTTP_TIMEOUT, 60),
    )
    _check(put_resp, "upload da imagem (PUT)")
    return image_urn


def create_post(text: str, image_urn: str | None, author_urn: str, alt_text: str = "Card da novidade") -> str:
    """Cria o post e retorna a URL pública do update."""
    body: dict = {
        "author": author_urn,
        "commentary": format_commentary(text, config.DATABRICKS_ORG_URN),
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
    _check(resp, "criação do post (/rest/posts)")
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
