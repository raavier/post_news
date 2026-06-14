"""Configuração central do post_news.

Tudo que depende de ambiente/secrets é lido aqui. Funções que precisam de um
secret só falham quando são realmente chamadas (não no import), para permitir
rodar os módulos de feed/imagem localmente sem credenciais.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# Raiz do repositório (este arquivo fica em src/post_news/config.py).
REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = REPO_ROOT / "state" / "seen.json"
DRAFTS_DIR = REPO_ROOT / "drafts"
WORK_DIR = REPO_ROOT / ".work"
PROMPT_TEMPLATE_PATH = REPO_ROOT / "prompts" / "post_template.md"
REVISE_TEMPLATE_PATH = REPO_ROOT / "prompts" / "revise_template.md"
FEEDS_PATH = REPO_ROOT / "feeds.json"

# Prefixo de comando para revisar o texto comentando na issue.
REVISE_COMMAND = "/revisar"

# User-Agent "de navegador" — algumas docs devolvem 403 para clients sem UA.
HTTP_USER_AGENT = os.environ.get(
    "POST_NEWS_USER_AGENT",
    "Mozilla/5.0 (compatible; post-news-bot/0.1; +https://github.com/raavier/post_news)",
)
HTTP_TIMEOUT = int(os.environ.get("POST_NEWS_HTTP_TIMEOUT") or "30")


@dataclass(frozen=True)
class FeedSource:
    """Uma fonte de novidades (definida em feeds.json)."""

    brand: str               # nome do produto (card, título, texto). Ex.: "Databricks"
    tag: str = ""            # badge curto no card. Ex.: "AWS"/"Azure". Default = brand.
    feed_url: str | None = None       # URL direta do feed (quando conhecida)
    page_url: str | None = None       # página p/ auto-descobrir o RSS (<link rel=alternate>)
    feed_candidates: tuple[str, ...] = field(default_factory=tuple)  # URLs candidatas
    hashtags: tuple[str, ...] = field(default_factory=tuple)         # hashtags do post

    @property
    def badge(self) -> str:
        return self.tag or self.brand


# Fontes embutidas (fallback se feeds.json não existir).
_DEFAULT_SOURCES: tuple[FeedSource, ...] = (
    FeedSource(
        brand="Databricks", tag="AWS",
        page_url="https://docs.databricks.com/aws/en/release-notes/",
        feed_candidates=("https://docs.databricks.com/aws/en/release-notes/index.rss",),
        hashtags=("#Databricks", "#DataEngineering", "#AI"),
    ),
    FeedSource(
        brand="Databricks", tag="Azure",
        feed_url="https://learn.microsoft.com/en-us/azure/databricks/feed.xml",
        hashtags=("#Databricks", "#Azure", "#DataIntelligence"),
    ),
)


def load_sources() -> tuple[FeedSource, ...]:
    """Carrega as fontes de feeds.json (editável pela UI do GitHub) ou usa os defaults."""
    if not FEEDS_PATH.exists():
        return _DEFAULT_SOURCES
    data = json.loads(FEEDS_PATH.read_text(encoding="utf-8"))
    sources: list[FeedSource] = []
    for item in data:
        sources.append(
            FeedSource(
                brand=item["brand"],
                tag=item.get("tag", ""),
                feed_url=item.get("feed_url"),
                page_url=item.get("page_url"),
                feed_candidates=tuple(item.get("feed_candidates", [])),
                hashtags=tuple(item.get("hashtags", [])),
            )
        )
    return tuple(sources)


# --- Gemini -----------------------------------------------------------------
# Usamos `or default` (não o 2º arg do .get) porque o GitHub Actions seta a env
# var como string vazia quando `vars.X` não está definido — e "" sobrescreveria
# o default silenciosamente.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
GEMINI_API_BASE = (
    os.environ.get("GEMINI_API_BASE") or "https://generativelanguage.googleapis.com/v1beta"
)
# Pausa entre chamadas ao Gemini para respeitar o limite de req/min do tier gratuito.
GEMINI_DELAY_SECONDS = float(os.environ.get("GEMINI_DELAY_SECONDS") or "7")

# --- Databricks (fallback de geração — só usado se o Gemini falhar) ----------
# Endpoint OpenAI-compatible do Databricks Model Serving. base_url termina em
# /serving-endpoints; o cliente acrescenta /chat/completions.
DATABRICKS_BASE_URL = os.environ.get("DATABRICKS_BASE_URL") or ""
DATABRICKS_MODEL = os.environ.get("DATABRICKS_MODEL") or "databricks-claude-sonnet-4-6"
# Teto de chamadas ao Databricks POR EXECUÇÃO (controle de custo). ~US$0,01/post,
# então 20 ≈ US$0,20 por run. Ajuste via variável DATABRICKS_MAX_CALLS.
DATABRICKS_MAX_CALLS = int(os.environ.get("DATABRICKS_MAX_CALLS") or "20")


def databricks_token() -> str:
    return os.environ.get("DATABRICKS_TOKEN") or ""


def databricks_enabled() -> bool:
    return bool(databricks_token() and DATABRICKS_BASE_URL)

# --- Detecção ---------------------------------------------------------------
# Máximo de rascunhos criados por execução (evita flood e estouro de rate limit).
DEFAULT_LIMIT = int(os.environ.get("POST_NEWS_DEFAULT_LIMIT") or "10")
# Quantas amostras criar na PRIMEIRA execução (bootstrap). 0 = só faz baseline do
# histórico (marca tudo como visto) sem criar issues; novidades futuras é que viram posts.
BOOTSTRAP_SAMPLE = int(os.environ.get("POST_NEWS_BOOTSTRAP_SAMPLE") or "0")

# --- Pollinations (imagem, sem chave) --------------------------------------
POLLINATIONS_BASE = os.environ.get("POLLINATIONS_BASE") or "https://image.pollinations.ai/prompt"
IMAGE_WIDTH = int(os.environ.get("POST_NEWS_IMAGE_WIDTH") or "1200")
IMAGE_HEIGHT = int(os.environ.get("POST_NEWS_IMAGE_HEIGHT") or "627")  # 1.91:1, formato LinkedIn

# --- LinkedIn ---------------------------------------------------------------
LINKEDIN_API_BASE = os.environ.get("LINKEDIN_API_BASE") or "https://api.linkedin.com"
# Versão da API no formato YYYYMM (header LinkedIn-Version). Usamos o mês ANTERIOR
# como padrão porque o LinkedIn costuma não publicar a versão do mês corrente ainda.
# Ajustável via variável de repositório LINKEDIN_VERSION se o erro 426 indicar outra.
LINKEDIN_VERSION = os.environ.get("LINKEDIN_VERSION") or "202605"

# URN da organização Databricks para mencionar (@Databricks) nos posts. Pode ser
# o número (ex.: "3608") ou o URN completo. Vazio = não menciona (só hashtag/texto).
_org = (os.environ.get("DATABRICKS_ORG_URN") or "").strip()
if _org.isdigit():
    _org = f"urn:li:organization:{_org}"
DATABRICKS_ORG_URN = _org

# Onde colocar o link da documentação:
#   "comment" (padrão) -> publica como 1º comentário (corpo limpo, melhor alcance)
#   "body"             -> acrescenta o link no fim do texto do post
#   "none"             -> não inclui o link
LINK_PLACEMENT = (os.environ.get("LINK_PLACEMENT") or "comment").lower()

# --- GitHub -----------------------------------------------------------------
GITHUB_API = os.environ.get("GITHUB_API_URL") or "https://api.github.com"

LABEL_PENDING = "pending-approval"
LABEL_APPROVED = "approved"
LABEL_REJECTED = "rejected"
LABEL_PUBLISHED = "published"


def require_env(name: str) -> str:
    """Lê uma variável de ambiente obrigatória, com mensagem de erro clara."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Variável de ambiente obrigatória ausente: {name}. "
            "Configure-a como secret do repositório (ou no .env local)."
        )
    return value


def gemini_api_key() -> str:
    return require_env("GEMINI_API_KEY")


def linkedin_token() -> str:
    return require_env("LINKEDIN_ACCESS_TOKEN")


def linkedin_author_urn() -> str:
    return require_env("LINKEDIN_AUTHOR_URN")


def github_token() -> str:
    return require_env("GITHUB_TOKEN")


def github_repo() -> str:
    """Ex.: 'raavier/post_news' (fornecido automaticamente no GitHub Actions)."""
    return require_env("GITHUB_REPOSITORY")
