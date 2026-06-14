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
from datetime import datetime, timedelta, timezone

from . import config, feed, generate, github_issues, image

PENDING_PATH = config.WORK_DIR / "pending.json"


def _issue_title(brand: str, tag: str, title: str) -> str:
    prefix = f"{brand} · {tag}" if tag and tag != brand else brand
    return f"[{prefix}] {title}"[:250]


def _plan(entries, state, *, limit=None, days=None, per_brand=None, backfill=False):
    """Decide o que vira post agora (`to_process`) e o que só é marcado como visto.

    - Modo normal: só marcas já baselined e itens ainda não vistos; limite global.
    - Modo backfill: itens dentro da janela de `days` dias, até `per_brand` por marca,
      ignorando o baseline. O resto (mais antigo/excedente) é marcado como visto.
    Em ambos, `entries` chega ordenado do mais novo p/ o mais antigo.
    """
    brands_now = {e.brand for e in entries}
    if backfill:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None
        counts: dict[str, int] = {}
        to_process = []
        for e in entries:
            if e.key in state.seen:
                continue
            if cutoff is not None:
                d = feed._parse_date(e.published)
                if d is None or d < cutoff:
                    continue
            if per_brand is not None and counts.get(e.brand, 0) >= per_brand:
                continue
            to_process.append(e)
            counts[e.brand] = counts.get(e.brand, 0) + 1
        if limit is not None:
            to_process = to_process[:limit]
    else:
        new_brands = brands_now - state.baselined_brands
        candidates = [e for e in entries if e.brand not in new_brands and e.key not in state.seen]
        n = limit if limit is not None else config.DEFAULT_LIMIT
        to_process = candidates[:n]

    sel = {e.key for e in to_process}
    baseline_keys = [e.key for e in entries if e.key not in sel]
    return to_process, baseline_keys, brands_now


def prepare(limit=None, days=None, per_brand=None, backfill=False) -> int:
    entries = feed.sort_newest_first(feed.fetch_all_entries())
    state = feed.load_state()
    to_process, baseline_keys, brands_now = _plan(
        entries, state, limit=limit, days=days, per_brand=per_brand, backfill=backfill
    )

    mode = f"backfill (até {per_brand}/marca, últimos {days}d)" if backfill else "normal"
    print(f"Modo {mode}: {len(entries)} entradas | preparando: {len(to_process)} | baseline: {len(baseline_keys)}")

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


def _print_diagnostics(entries) -> None:
    """Mostra quais feeds resolveram e, por marca, total + item mais recente."""
    print("\n--- Feeds (resolução) ---")
    for s in config.load_sources():
        url = feed.resolve_feed_url(s)
        print(f"  {s.brand} [{s.badge}]: {url or '*** NÃO RESOLVEU ***'}")

    by_brand: dict[str, list] = {}
    for e in entries:
        by_brand.setdefault(e.brand, []).append(e)
    print("\n--- Entradas por marca ---")
    if not by_brand:
        print("  (nenhuma)")
    for brand in sorted(by_brand):
        items = by_brand[brand]
        dates = [d for d in (feed._parse_date(i.published) for i in items) if d]
        newest = max(dates).date().isoformat() if dates else "s/ data"
        print(f"  {brand}: {len(items)} itens | mais recente: {newest}")


def run(dry_run: bool = True, limit=None, days=None, per_brand=None, backfill=False) -> int:
    """Modo local/dry-run: imprime os rascunhos e renderiza os cards, sem criar issues."""
    entries = feed.sort_newest_first(feed.fetch_all_entries())
    state = feed.load_state()
    _print_diagnostics(entries)
    to_process, baseline_keys, _brands = _plan(
        entries, state, limit=limit, days=days, per_brand=per_brand, backfill=backfill
    )
    print(f"\n[dry-run] amostra: {len(to_process)} | seria baselined: {len(baseline_keys)}")

    for entry in to_process:
        print(f"\n=== [{entry.brand}/{entry.tag}] {entry.title} ===")
        print(generate.generate_post_text(entry))
        print(f"[card] {image.save_card(entry)}")
    return 0


def _backfill_defaults(args):
    """No modo backfill, aplica padrões amigáveis (14 dias, 5 por marca)."""
    if not args.backfill:
        return args.days, args.per_brand
    return (args.days if args.days is not None else 14,
            args.per_brand if args.per_brand is not None else 5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detecta novidades e cria rascunhos.")
    parser.add_argument("--dry-run", action="store_true", help="Não cria issues; só imprime.")
    parser.add_argument("--prepare", action="store_true", help="Fase 1: gera texto e cards.")
    parser.add_argument("--create-issues", action="store_true", help="Fase 2: cria as issues.")
    parser.add_argument("--limit", type=int, default=None, help="Teto global de novidades por execução.")
    parser.add_argument("--backfill", action="store_true",
                        help="Recupera o histórico recente (janela + por marca), ignorando o baseline.")
    parser.add_argument("--days", type=int, default=None, help="Janela em dias (backfill; padrão 14).")
    parser.add_argument("--per-brand", type=int, default=None,
                        help="Máximo de itens por marca (backfill; padrão 5).")
    args = parser.parse_args()
    if args.create_issues:
        return create_issues()
    days, per_brand = _backfill_defaults(args)
    if args.prepare:
        return prepare(limit=args.limit, days=days, per_brand=per_brand, backfill=args.backfill)
    return run(dry_run=True, limit=args.limit, days=days, per_brand=per_brand, backfill=args.backfill)


if __name__ == "__main__":
    raise SystemExit(main())
