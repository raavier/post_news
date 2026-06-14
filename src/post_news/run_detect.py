"""Orquestra a detecção: feeds -> texto (Gemini) + card (local) -> Issue.

Fluxo em DUAS FASES (usado pelo detect.yml):
    1) prepare        -> gera texto e renderiza os cards, grava .work/pending.json
       (o workflow commita/empurra drafts/)
    2) create-issues  -> cria as issues (raw URL já resolve) e atualiza o estado

BASELINE POR MARCA: a primeira vez que uma marca aparece, seu histórico é
marcado como "visto" SEM criar issues — só os lançamentos futuros viram posts.
Assim, adicionar um feed novo em feeds.json nunca causa enxurrada de issues.

Modos:
    python -m post_news.run_detect --dry-run [--limit N]
    python -m post_news.run_detect --prepare [--limit N]
    python -m post_news.run_detect --create-issues
"""
from __future__ import annotations

import argparse
import json
import time

from . import config, feed, generate, github_issues, image

PENDING_PATH = config.WORK_DIR / "pending.json"


def _issue_title(brand: str, tag: str, title: str) -> str:
    prefix = f"{brand} · {tag}" if tag and tag != brand else brand
    return f"[{prefix}] {title}"[:250]


def _select(entries, state):
    """Retorna (candidatas_a_post, chaves_de_baseline, marcas_presentes)."""
    brands_now = {e.brand for e in entries}
    new_brands = brands_now - state.baselined_brands
    candidates = [e for e in entries if e.brand not in new_brands and e.key not in state.seen]
    baseline_keys = [e.key for e in entries if e.brand in new_brands]
    return candidates, baseline_keys, brands_now, new_brands


def prepare(limit: int | None = None) -> int:
    entries = feed.sort_newest_first(feed.fetch_all_entries())
    state = feed.load_state()
    candidates, baseline_keys, brands_now, new_brands = _select(entries, state)
    n = limit if limit is not None else config.DEFAULT_LIMIT
    to_process = candidates[:n]

    if new_brands:
        print(f"Baseline (marcas novas, sem postar): {sorted(new_brands)} — {len(baseline_keys)} itens.")
    print(f"Entradas: {len(entries)} | candidatas a post: {len(candidates)} | preparando: {len(to_process)}")

    prepared = []
    for i, entry in enumerate(to_process):
        print(f"\n=== [{entry.brand}/{entry.tag}] {entry.title} ===")
        try:
            post_text = generate.generate_post_text(entry)
        except Exception as exc:  # ex.: 429 do Gemini — para e salva o que já temos
            print(f"Geração interrompida em '{entry.title}': {exc}")
            break
        image.save_card(entry)
        prepared.append(
            {
                "key": entry.key, "title": entry.title, "brand": entry.brand,
                "tag": entry.tag, "link": entry.link, "post_text": post_text,
                "image_url": image.raw_url_for(entry), "image_file": image.card_filename(entry),
            }
        )
        if i < len(to_process) - 1:
            time.sleep(config.GEMINI_DELAY_SECONDS)

    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(
        json.dumps(
            {"prepared": prepared, "baseline_keys": baseline_keys, "all_brands": sorted(brands_now)},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nPreparado: {len(prepared)} rascunho(s).")
    return 0


def create_issues() -> int:
    if not PENDING_PATH.exists():
        print("Nada preparado (.work/pending.json ausente). Encerrando.")
        return 0
    payload = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    prepared = payload.get("prepared", [])
    state = feed.load_state()

    if prepared:
        github_issues.ensure_labels()

    created = 0
    for item in prepared:
        entry = feed.Entry(
            key=item["key"], title=item["title"], summary="", link=item["link"],
            published="", brand=item["brand"], tag=item.get("tag", ""),
        )
        title = _issue_title(entry.brand, entry.tag, entry.title)
        body = github_issues.build_issue_body(entry, item["post_text"], item["image_url"], item["image_file"])
        issue = github_issues.create_issue(title, body, [config.LABEL_PENDING])
        print(f"Issue criada: #{issue['number']} -> {issue['html_url']}")
        state.seen.add(entry.key)
        created += 1

    # Baseline das marcas novas + registro das marcas vistas.
    state.seen.update(payload.get("baseline_keys", []))
    state.baselined_brands.update(payload.get("all_brands", []))
    feed.save_state(state)

    print(f"\nConcluído. Issues criadas: {created}. Estado em {config.STATE_PATH}.")
    return 0


def run(dry_run: bool = True, limit: int | None = None) -> int:
    """Modo local/dry-run: imprime os rascunhos e renderiza os cards, sem criar issues."""
    entries = feed.sort_newest_first(feed.fetch_all_entries())
    state = feed.load_state()
    candidates, _baseline, _brands, new_brands = _select(entries, state)
    n = limit if limit is not None else config.DEFAULT_LIMIT
    to_process = candidates[:n]
    if new_brands:
        print(f"[dry-run] Marcas novas que seriam baselined: {sorted(new_brands)}")
    print(f"[dry-run] candidatas: {len(candidates)} | amostra: {len(to_process)}")

    for entry in to_process:
        print(f"\n=== [{entry.brand}/{entry.tag}] {entry.title} ===")
        print(generate.generate_post_text(entry))
        print(f"[card] {image.save_card(entry)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Detecta novidades e cria rascunhos.")
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
