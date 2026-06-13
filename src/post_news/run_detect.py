"""Orquestra a detecção: feeds -> texto (Gemini) -> imagem (Pollinations) -> Issue.

Uso:
    python -m post_news.run_detect            # cria issues no GitHub e atualiza o estado
    python -m post_news.run_detect --dry-run  # só imprime os posts gerados, não cria nada
    python -m post_news.run_detect --limit 3  # processa no máximo N novidades por execução

No modo normal, requer GEMINI_API_KEY, GITHUB_TOKEN e GITHUB_REPOSITORY.
O --dry-run requer apenas GEMINI_API_KEY.
"""
from __future__ import annotations

import argparse

from . import config, feed, generate, github_issues, image


def run(dry_run: bool = False, limit: int | None = None) -> int:
    entries = feed.fetch_all_entries()
    seen = feed.load_seen()
    new_entries = feed.find_new_entries(entries, seen)

    if limit is not None:
        new_entries = new_entries[:limit]

    print(f"Entradas no feed: {len(entries)} | novas: {len(new_entries)}")
    if not new_entries:
        print("Nada novo. Encerrando.")
        return 0

    if not dry_run:
        github_issues.ensure_labels()

    created = 0
    for entry in new_entries:
        print(f"\n=== [{entry.platform}] {entry.title} ===")
        post_text = generate.generate_post_text(entry)
        image_url = image.build_image_url(entry)

        if dry_run:
            print(post_text)
            print(f"\n[imagem] {image_url}")
            continue

        title = f"[{entry.platform}] {entry.title}"[:250]
        body = github_issues.build_issue_body(entry, post_text, image_url)
        issue = github_issues.create_issue(title, body, [config.LABEL_PENDING])
        print(f"Issue criada: #{issue['number']} -> {issue['html_url']}")

        # Marca como visto só após criar a issue com sucesso (evita perder itens em falha).
        seen.add(entry.key)
        feed.save_seen(seen)
        created += 1

    if not dry_run:
        print(f"\nConcluído. Issues criadas: {created}. Estado atualizado em {config.STATE_PATH}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Detecta novidades da Databricks e cria rascunhos.")
    parser.add_argument("--dry-run", action="store_true", help="Não cria issues; só imprime.")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de novidades por execução.")
    args = parser.parse_args()
    return run(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
