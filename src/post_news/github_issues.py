"""Interação com GitHub Issues (gerência, aprovação e notificação).

O corpo da issue é estruturado com marcadores para que o passo de publicação
consiga extrair o texto final (que você pode ter editado) e a URL da imagem,
de forma robusta:

    <!-- post-news:meta {json} -->
    ## texto ...
    <!-- POST:START -->
    ...texto do post...
    <!-- POST:END -->
    ## imagem ...
    ![card](url)
"""
from __future__ import annotations

import json
import re

import requests

from . import config
from .feed import Entry

META_RE = re.compile(r"<!--\s*post-news:meta\s*(\{.*?\})\s*-->", re.DOTALL)
POST_RE = re.compile(r"<!--\s*POST:START\s*-->(.*?)<!--\s*POST:END\s*-->", re.DOTALL)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.github_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "post-news-bot",
    }


def _repo_url(path: str) -> str:
    return f"{config.GITHUB_API}/repos/{config.github_repo()}{path}"


# --- Montagem / parse do corpo ---------------------------------------------

def build_issue_body(entry: Entry, post_text: str, image_url: str, image_file: str = "") -> str:
    meta = json.dumps(
        {
            "key": entry.key,
            "platform": entry.platform,
            "source": entry.link,
            "image": image_url,
            "image_file": image_file,
        },
        ensure_ascii=False,
    )
    return (
        f"<!-- post-news:meta {meta} -->\n\n"
        f"> 🤖 Rascunho gerado automaticamente a partir das release notes da Databricks ({entry.platform}).\n"
        f"> Edite o texto livremente entre os marcadores abaixo. Para **publicar**, adicione a label "
        f"`{config.LABEL_APPROVED}`. Para descartar, **feche** a issue.\n\n"
        f"## 📝 Texto do post (editável)\n\n"
        f"<!-- POST:START -->\n{post_text}\n<!-- POST:END -->\n\n"
        f"## 🖼️ Imagem do card\n\n"
        f"![card]({image_url})\n\n"
        f"## 🔗 Fonte\n\n"
        f"{entry.link}\n"
    )


def parse_issue_body(body: str) -> dict:
    """Extrai metadados, texto do post e URL da imagem do corpo da issue."""
    meta_match = META_RE.search(body or "")
    if not meta_match:
        raise ValueError("Issue sem bloco de metadados post-news:meta — não é um rascunho válido.")
    meta = json.loads(meta_match.group(1))

    post_match = POST_RE.search(body or "")
    if not post_match:
        raise ValueError("Issue sem marcadores POST:START/POST:END — não foi possível extrair o texto.")
    post_text = post_match.group(1).strip()

    return {
        "key": meta.get("key"),
        "platform": meta.get("platform"),
        "source": meta.get("source"),
        "image_url": meta.get("image"),
        "image_file": meta.get("image_file", ""),
        "post_text": post_text,
    }


# --- Operações de API -------------------------------------------------------

def ensure_label(name: str, color: str, description: str = "") -> None:
    """Cria a label se ainda não existir (ignora se já existe)."""
    resp = requests.post(
        _repo_url("/labels"),
        headers=_headers(),
        json={"name": name, "color": color, "description": description},
        timeout=config.HTTP_TIMEOUT,
    )
    if resp.status_code not in (201, 422):  # 422 = já existe
        resp.raise_for_status()


def ensure_labels() -> None:
    ensure_label(config.LABEL_PENDING, "fbca04", "Rascunho aguardando aprovação")
    ensure_label(config.LABEL_APPROVED, "0e8a16", "Aprovado para publicar no LinkedIn")
    ensure_label(config.LABEL_REJECTED, "b60205", "Descartado")
    ensure_label(config.LABEL_PUBLISHED, "5319e7", "Publicado no LinkedIn")


def create_issue(title: str, body: str, labels: list[str]) -> dict:
    resp = requests.post(
        _repo_url("/issues"),
        headers=_headers(),
        json={"title": title, "body": body, "labels": labels},
        timeout=config.HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_issue(number: int) -> dict:
    resp = requests.get(_repo_url(f"/issues/{number}"), headers=_headers(), timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def add_comment(number: int, body: str) -> None:
    resp = requests.post(
        _repo_url(f"/issues/{number}/comments"),
        headers=_headers(),
        json={"body": body},
        timeout=config.HTTP_TIMEOUT,
    )
    resp.raise_for_status()


def add_labels(number: int, labels: list[str]) -> None:
    resp = requests.post(
        _repo_url(f"/issues/{number}/labels"),
        headers=_headers(),
        json={"labels": labels},
        timeout=config.HTTP_TIMEOUT,
    )
    resp.raise_for_status()


def remove_label(number: int, label: str) -> None:
    resp = requests.delete(
        _repo_url(f"/issues/{number}/labels/{label}"),
        headers=_headers(),
        timeout=config.HTTP_TIMEOUT,
    )
    if resp.status_code not in (200, 404):
        resp.raise_for_status()


def update_issue_body(number: int, body: str) -> None:
    resp = requests.patch(
        _repo_url(f"/issues/{number}"),
        headers=_headers(),
        json={"body": body},
        timeout=config.HTTP_TIMEOUT,
    )
    resp.raise_for_status()


def close_issue(number: int, state_reason: str = "completed") -> None:
    resp = requests.patch(
        _repo_url(f"/issues/{number}"),
        headers=_headers(),
        json={"state": "closed", "state_reason": state_reason},
        timeout=config.HTTP_TIMEOUT,
    )
    resp.raise_for_status()
