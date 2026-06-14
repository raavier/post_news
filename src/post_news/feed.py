"""Detecção de novidades nos feeds (multi-marca, definidos em feeds.json).

Responsável por:
- descobrir a URL do feed RSS/Atom (auto-descoberta + candidatas);
- parsear as entradas e marcá-las com a marca/tag/hashtags da fonte;
- deduplicar (a chave inclui a marca, então marcas diferentes não colidem);
- gerir o estado já processado (state/seen.json), com baseline POR MARCA.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

from . import config

# Namespace do Atom (RSS 2.0 não usa namespace nos elementos principais).
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


@dataclass
class Entry:
    """Uma novidade normalizada, vinda de um feed."""

    key: str            # chave de dedupe: slug(marca) + dia + slug(título)
    title: str
    summary: str
    link: str
    published: str      # data como vem no feed
    brand: str          # nome do produto (ex.: "Databricks", "GitHub Copilot")
    tag: str = ""       # badge curto (ex.: "AWS", "OpenAI"); default = brand
    hashtags: tuple[str, ...] = field(default_factory=tuple)


def _http_get(url: str) -> requests.Response:
    return requests.get(
        url,
        headers={"User-Agent": config.HTTP_USER_AGENT, "Accept": "*/*"},
        timeout=config.HTTP_TIMEOUT,
    )


_RSS_LINK_RE = re.compile(
    r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', re.IGNORECASE
)
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


def discover_feed_url(page_url: str) -> str | None:
    """Lê o <head> da página e extrai o href do feed RSS/Atom."""
    try:
        resp = _http_get(page_url)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    for tag in _RSS_LINK_RE.findall(resp.text):
        m = _HREF_RE.search(tag)
        if not m:
            continue
        href = m.group(1)
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            from urllib.parse import urljoin

            href = urljoin(page_url, href)
        return href
    return None


def resolve_feed_url(source: config.FeedSource) -> str | None:
    """Determina a URL do feed para uma fonte (direta, descoberta ou candidata)."""
    if source.feed_url:
        return source.feed_url
    if source.page_url:
        discovered = discover_feed_url(source.page_url)
        if discovered:
            return discovered
    for candidate in source.feed_candidates:
        try:
            resp = _http_get(candidate)
        except requests.RequestException:
            continue
        ctype = resp.headers.get("Content-Type", "")
        if resp.status_code == 200 and ("xml" in ctype or resp.text.lstrip().startswith("<?xml")):
            return candidate
    return None


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:80]


def _make_key(brand: str, title: str, published: str) -> str:
    """Chave estável e única por marca: slug(marca):dia:slug(título)."""
    day = (published or "")[:10]
    base = f"{day}:{_slugify(title)}" if day else _slugify(title)
    return f"{_slugify(brand)}:{base}"


def _entry_from(source: config.FeedSource, title: str, summary: str, link: str, published: str) -> Entry:
    return Entry(
        key=_make_key(source.brand, title, published),
        title=title,
        summary=_strip_html(summary),
        link=link,
        published=published,
        brand=source.brand,
        tag=source.badge,
        hashtags=source.hashtags,
    )


def _text(elem: ET.Element | None) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def _parse_rss(root: ET.Element, source: config.FeedSource) -> list[Entry]:
    """RSS 2.0: channel/item com title, link, description, pubDate."""
    entries: list[Entry] = []
    for item in root.iter("item"):
        title = _text(item.find("title"))
        if not title:
            continue
        entries.append(
            _entry_from(
                source, title,
                _text(item.find("description")),
                _text(item.find("link")),
                _text(item.find("pubDate")),
            )
        )
    return entries


def _parse_atom(root: ET.Element, source: config.FeedSource) -> list[Entry]:
    """Atom: feed/entry com title, link[@href], summary/content, updated/published."""
    entries: list[Entry] = []
    for entry in root.iter(f"{_ATOM_NS}entry"):
        title = _text(entry.find(f"{_ATOM_NS}title"))
        if not title:
            continue
        link = ""
        for link_el in entry.findall(f"{_ATOM_NS}link"):
            rel = link_el.get("rel", "alternate")
            if rel == "alternate" or not link:
                link = link_el.get("href", "")
        summary = _text(entry.find(f"{_ATOM_NS}summary")) or _text(entry.find(f"{_ATOM_NS}content"))
        published = _text(entry.find(f"{_ATOM_NS}published")) or _text(entry.find(f"{_ATOM_NS}updated"))
        entries.append(_entry_from(source, title, summary, link, published))
    return entries


def parse_feed(feed_url: str, source: config.FeedSource) -> list[Entry]:
    """Busca e parseia um feed RSS 2.0 ou Atom usando a biblioteca padrão."""
    try:
        resp = _http_get(feed_url)
        resp.raise_for_status()
    except requests.RequestException:
        return []
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return []

    tag = root.tag.lower()
    if tag.endswith("rss") or root.find("channel") is not None:
        return _parse_rss(root, source)
    if tag.endswith("feed"):
        return _parse_atom(root, source)
    return _parse_rss(root, source) or _parse_atom(root, source)


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    text = _TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _parse_date(value: str) -> datetime | None:
    """Parseia data RFC822 (RSS) ou ISO 8601 (Atom); devolve sempre tz-aware (UTC)."""
    if not value:
        return None
    dt = None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def sort_newest_first(entries: list[Entry]) -> list[Entry]:
    """Ordena por data de publicação (mais recente primeiro); sem data vai para o fim."""
    return sorted(entries, key=lambda e: _parse_date(e.published) or _EPOCH, reverse=True)


def fetch_all_entries() -> list[Entry]:
    """Busca e deduplica entradas de todas as fontes (feeds.json)."""
    by_key: dict[str, Entry] = {}
    for source in config.load_sources():
        feed_url = resolve_feed_url(source)
        if not feed_url:
            continue
        for entry in parse_feed(feed_url, source):
            by_key.setdefault(entry.key, entry)
    return list(by_key.values())


# --- Estado (state/seen.json) ----------------------------------------------

@dataclass
class State:
    seen: set[str]                          # chaves já vistas (baseline + posts)
    baselined_brands: set[str]              # marcas cujo histórico já foi "zerado"
    posted: set[str] = field(default_factory=set)  # chaves que viraram issue de fato


def load_state(path: Path | None = None) -> State:
    path = path or config.STATE_PATH
    if not path.exists():
        return State(set(), set(), set())
    data = json.loads(path.read_text(encoding="utf-8"))
    return State(
        set(data.get("seen_keys", [])),
        set(data.get("baselined_brands", [])),
        set(data.get("posted_keys", [])),
    )


def save_state(state: State, path: Path | None = None) -> None:
    path = path or config.STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "seen_keys": sorted(state.seen),
        "baselined_brands": sorted(state.baselined_brands),
        "posted_keys": sorted(state.posted),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_new_entries(entries: list[Entry], seen: set[str]) -> list[Entry]:
    return [e for e in entries if e.key not in seen]


def _main() -> None:
    """Diagnóstico local: lista feeds resolvidos e entradas recentes/novas."""
    print("Fontes configuradas:")
    for source in config.load_sources():
        url = resolve_feed_url(source)
        print(f"  - {source.brand} [{source.badge}]: {url or '(feed não resolvido)'}")

    entries = sort_newest_first(fetch_all_entries())
    print(f"\nTotal de entradas: {len(entries)}")
    for e in entries[:15]:
        print(f"  [{e.brand}/{e.tag}] {e.published[:10]}  {e.title}")

    state = load_state()
    new = find_new_entries(entries, state.seen)
    print(f"\nMarcas já baselined: {sorted(state.baselined_brands)}")
    print(f"Novas (não vistas): {len(new)}")


if __name__ == "__main__":
    _main()
