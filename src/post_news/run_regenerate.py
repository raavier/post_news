"""Regera o TEXTO de uma issue de rascunho existente com o prompt atual.

Útil para testar/ajustar o prompt sem criar issues novas. Preserva a imagem
(card) e os metadados; só reescreve o texto do post.

Uso:
    python -m post_news.run_regenerate --issue 20
    ISSUE_NUMBER=20 python -m post_news.run_regenerate

Requer: GEMINI_API_KEY, GITHUB_TOKEN, GITHUB_REPOSITORY.
"""
from __future__ import annotations

import argparse
import os

from . import feed, generate, github_issues
from .feed import Entry


def recover_entry(issue: dict, parsed: dict) -> Entry:
    """Recupera o Entry completo do feed (resumo/hashtags); fallback p/ dados da issue."""
    key = parsed["key"]
    entry = next((e for e in feed.fetch_all_entries() if e.key == key), None)
    if entry is not None:
        return entry
    title = issue.get("title", "")
    if title.startswith("["):
        title = title.split("] ", 1)[-1]
    print("Entrada não encontrada no feed; usando título/fonte da issue.")
    return Entry(
        key=key, title=title, summary="", link=parsed.get("source") or "",
        published="", brand=parsed.get("brand") or "Databricks", tag=parsed.get("tag", ""),
    )


def run(issue_number: int) -> int:
    issue = github_issues.get_issue(issue_number)
    parsed = github_issues.parse_issue_body(issue.get("body") or "")
    entry = recover_entry(issue, parsed)

    text = generate.generate_post_text(entry)
    body = github_issues.build_issue_body(
        entry, text, parsed.get("image_url") or "", parsed.get("image_file") or ""
    )
    github_issues.update_issue_body(issue_number, body)
    print(f"Issue #{issue_number} regenerada com o prompt atual:\n")
    print(text)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Regera o texto de uma issue de rascunho.")
    parser.add_argument("--issue", type=int, default=None, help="Número da issue.")
    args = parser.parse_args()
    issue_number = args.issue or (int(os.environ["ISSUE_NUMBER"]) if os.environ.get("ISSUE_NUMBER") else None)
    if not issue_number:
        parser.error("Informe --issue N ou a variável de ambiente ISSUE_NUMBER.")
    return run(issue_number)


if __name__ == "__main__":
    raise SystemExit(main())
