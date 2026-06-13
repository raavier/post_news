"""Detecção de novidades nos feeds RSS de release notes da Databricks (AWS + Azure).

Responsável por:
- descobrir a URL do feed RSS (auto-descoberta + candidatas);
- parsear as entradas;
- normalizar e deduplicar entre os feeds (a mesma novidade costuma aparecer
  nas docs de AWS e Azure);
- comparar com o estado já processado (state/seen.json).
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

from . import config

# Namespace do Atom (RSS 2.0 não usa namespace nos elementos principais).
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


@dataclass
class Entry:
    """Uma novidade normalizada, vinda de um feed."""

    key: str  # chave de dedupe (slug do título + data)
    title: str
    summary: str
    link: str
    published: str  # ISO/string como vem no feed
    platform: str  # "AWS" | "Azure"


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
    """Lê o <head> da página de release notes e extrai o href do feed RSS/Atom."""
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
            # Resolve relativo ao host da página.
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


def _make_key(title: str, published: str) -> str:
    """Chave de dedupe estável entre feeds: slug do título + dia da publicação."""
    day = (published or "")[:10]
    return f"{day}:{_slugify(title)}" if day else _slugify(title)


def _text(elem: ET.Element | None) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def _parse_rss(root: ET.Element, platform: str) -> list[Entry]:
    """RSS 2.0: channel/item com title, link, description, pubDate."""
    entries: list[Entry] = []
    for item in root.iter("item"):
        title = _text(item.find("title"))
        if not title:
            continue
        link = _text(item.find("link"))
        summary = _text(item.find("description"))
        published = _text(item.find("pubDate"))
        entries.append(
            Entry(
                key=_make_key(title, published),
                title=title,
                summary=_strip_html(summary),
                link=link,
                published=published,
                platform=platform,
            )
        )
    return entries


def _parse_atom(root: ET.Element, platform: str) -> list[Entry]:
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
        entries.append(
            Entry(
                key=_make_key(title, published),
                title=title,
                summary=_strip_html(summary),
                link=link,
                published=published,
                platform=platform,
            )
        )
    return entries


def parse_feed(feed_url: str, platform: str) -> list[Entry]:
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
        return _parse_rss(root, platform)
    if tag.endswith("feed"):
        return _parse_atom(root, platform)
    # Tenta ambos como fallback.
    return _parse_rss(root, platform) or _parse_atom(root, platform)


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    text = _TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_all_entries() -> list[Entry]:
    """Busca e deduplica entradas de todas as fontes configuradas.

    Quando a mesma novidade aparece em AWS e Azure, mantemos a primeira
    ocorrência (ordem das fontes em config.SOURCES) e ignoramos a duplicata.
    """
    by_key: dict[str, Entry] = {}
    for source in config.SOURCES:
        feed_url = resolve_feed_url(source)
        if not feed_url:
            continue
        for entry in parse_feed(feed_url, source.platform):
            by_key.setdefault(entry.key, entry)
    return list(by_key.values())


# --- Estado (state/seen.json) ----------------------------------------------

def load_seen(path: Path | None = None) -> set[str]:
    path = path or config.STATE_PATH
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return set(data.get("seen_keys", []))


def save_seen(keys: set[str], path: Path | None = None) -> None:
    path = path or config.STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"seen_keys": sorted(keys)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_new_entries(entries: list[Entry], seen: set[str]) -> list[Entry]:
    return [e for e in entries if e.key not in seen]


def _main() -> None:
    """Diagnóstico local: lista feeds descobertos e entradas recentes/novas."""
    print("Fontes configuradas:")
    for source in config.SOURCES:
        url = resolve_feed_url(source)
        print(f"  - {source.platform}: {url or '(feed não resolvido)'}")

    entries = fetch_all_entries()
    print(f"\nTotal de entradas (após dedupe AWS+Azure): {len(entries)}")
    for e in entries[:10]:
        print(f"  [{e.platform}] {e.published[:10]}  {e.title}")

    seen = load_seen()
    new = find_new_entries(entries, seen)
    print(f"\nNovas (não vistas em state/seen.json): {len(new)}")
    for e in new[:10]:
        print(f"  - {e.key}  ->  {e.title}")


if __name__ == "__main__":
    _main()
