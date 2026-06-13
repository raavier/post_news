"""Orquestra a detecção: feeds -> texto (Gemini) + card (local) -> Issue.

Fluxo em DUAS FASES (usado pelo detect.yml), para que o PNG do card já esteja
publicado no repo antes da issue referenciá-lo via raw URL:

    1) prepare        -> gera texto e renderiza os cards em drafts/, grava .work/pending.json
       (o workflow commita/empurra drafts/)
    2) create-issues  -> cria as issues (raw URL já resolve) e atualiza state/seen.json

Modos:
    python -m post_news.run_detect --dry-run [--limit N]   # local: só imprime, não cria nada
    python -m post_news.run_detect --prepare [--limit N]
    python -m post_news.run_detect --create-issues
"""
from __future__ import annotations

import argparse
import json
import time

from . import config, feed, generate, github_issues, image

PENDING_PATH = config.WORK_DIR / "pending.json"


def _select(entries: list[feed.Entry], seen: set[str], limit: int | None):
    """Decide quais entradas processar, aplicando bootstrap/limite."""
    first_run = not seen
    new_entries = feed.find_new_entries(entries, seen)
    if first_run:
        n = limit if limit is not None else config.BOOTSTRAP_SAMPLE
    else:
        n = limit if limit is not None else config.DEFAULT_LIMIT
    return new_entries[:n], first_run, len(new_entries)


def prepare(limit: int | None = None) -> int:
    entries = feed.sort_newest_first(feed.fetch_all_entries())
    seen = feed.load_seen()
    to_process, first_run, new_count = _select(entries, seen, limit)

    print(
        f"{'[bootstrap] ' if first_run else ''}Entradas: {len(entries)} | "
        f"novas: {new_count} | preparando: {len(to_process)}"
    )

    prepared = []
    for i, entry in enumerate(to_process):
        print(f"\n=== [{entry.platform}] {entry.title} ===")
        try:
            post_text = generate.generate_post_text(entry)
        except Exception as exc:  # ex.: 429 do Gemini — para e salva o que já temos
            print(f"Geração interrompida em '{entry.title}': {exc}")
            print("Salvando o que já foi preparado; o restante fica para a próxima execução.")
            break
        image.save_card(entry)
        prepared.append(
            {
                "key": entry.key,
                "title": entry.title,
                "platform": entry.platform,
                "link": entry.link,
                "post_text": post_text,
                "image_url": image.raw_url_for(entry),
                "image_file": image.card_filename(entry),
            }
        )
        if i < len(to_process) - 1:
            time.sleep(config.GEMINI_DELAY_SECONDS)

    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "prepared": prepared,
        "first_run": first_run,
        "all_keys": [e.key for e in entries] if first_run else [],
    }
    PENDING_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPreparado: {len(prepared)} rascunho(s). Cards em {config.DRAFTS_DIR}.")
    return 0


def create_issues() -> int:
    if not PENDING_PATH.exists():
        print("Nada preparado (.work/pending.json ausente). Encerrando.")
        return 0
    payload = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    prepared = payload.get("prepared", [])
    seen = feed.load_seen()

    if prepared:
        github_issues.ensure_labels()

    created = 0
    for item in prepared:
        entry = feed.Entry(
            key=item["key"], title=item["title"], summary="", link=item["link"],
            published="", platform=item["platform"],
        )
        title = f"[{entry.platform}] {entry.title}"[:250]
        body = github_issues.build_issue_body(
            entry, item["post_text"], item["image_url"], item["image_file"]
        )
        issue = github_issues.create_issue(title, body, [config.LABEL_PENDING])
        print(f"Issue criada: #{issue['number']} -> {issue['html_url']}")
        seen.add(entry.key)
        feed.save_seen(seen)
        created += 1

    # Baseline do histórico na primeira execução: marca tudo como visto.
    if payload.get("first_run"):
        seen.update(payload.get("all_keys", []))
        feed.save_seen(seen)
        print(f"Baseline concluído: {len(seen)} itens marcados como vistos.")

    print(f"\nConcluído. Issues criadas: {created}. Estado em {config.STATE_PATH}.")
    return 0


def run(dry_run: bool = True, limit: int | None = None) -> int:
    """Modo local/dry-run: imprime os rascunhos e renderiza os cards, sem criar issues."""
    entries = feed.sort_newest_first(feed.fetch_all_entries())
    seen = feed.load_seen()
    to_process, first_run, new_count = _select(entries, seen, limit)
    print(f"{'[bootstrap] ' if first_run else ''}Entradas: {len(entries)} | novas: {new_count} | amostra: {len(to_process)}")

    for entry in to_process:
        print(f"\n=== [{entry.platform}] {entry.title} ===")
        post_text = generate.generate_post_text(entry)
        path = image.save_card(entry)
        print(post_text)
        print(f"\n[card local] {path}")
        print(f"[raw url]    {image.raw_url_for(entry)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Detecta novidades da Databricks e cria rascunhos.")
    parser.add_argument("--dry-run", action="store_true", help="Não cria issues; só imprime.")
    parser.add_argument("--prepare", action="store_true", help="Fase 1: gera texto e cards.")
    parser.add_argument("--create-issues", action="store_true", help="Fase 2: cria as issues.")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de novidades por execução.")
    args = parser.parse_args()

    if args.create_issues:
        return create_issues()
    if args.prepare:
        return prepare(limit=args.limit)
    return run(dry_run=True, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
