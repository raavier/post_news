"""Orquestra a publicação de uma issue aprovada no LinkedIn.

Uso:
    python -m post_news.run_publish --issue 42
    ISSUE_NUMBER=42 python -m post_news.run_publish

Lê o corpo (possivelmente editado) da issue, extrai o texto final e a URL da
imagem, baixa a imagem, publica no LinkedIn, comenta a URL e fecha a issue.

Requer: GITHUB_TOKEN, GITHUB_REPOSITORY, LINKEDIN_ACCESS_TOKEN, LINKEDIN_AUTHOR_URN.
"""
from __future__ import annotations

import argparse
import os

from . import carousel, config, github_issues, image, linkedin


def _has_label(issue: dict, name: str) -> bool:
    return any((lb.get("name") if isinstance(lb, dict) else lb) == name for lb in issue.get("labels", []))


def run(issue_number: int, dry_run: bool = False) -> int:
    issue = github_issues.get_issue(issue_number)
    parsed = github_issues.parse_issue_body(issue.get("body") or "")
    text = parsed["post_text"]
    image_file = parsed.get("image_file")
    image_url = parsed.get("image_url")
    doc_file = parsed.get("doc_file")
    source = parsed.get("source") or ""

    # Carrossel só quando a label estiver presente E houver PDF gerado para a issue.
    as_carousel = _has_label(issue, config.LABEL_CAROUSEL) and bool(doc_file)

    print(f"Publicando issue #{issue_number}: {issue.get('title')}")

    doc_bytes = None
    image_bytes = None
    if as_carousel:
        try:
            doc_bytes = carousel.load_doc_bytes(doc_file)
            print(f"Carrossel: drafts/{doc_file} ({len(doc_bytes)} bytes)")
        except FileNotFoundError:
            print(f"PDF local drafts/{doc_file} não encontrado; caindo para imagem única.")
            as_carousel = False

    if not as_carousel:
        # Preferimos o PNG local (versionado em drafts/, presente no checkout);
        # se faltar, caímos para baixar pela raw URL (repo público).
        if image_file:
            try:
                image_bytes = image.load_card_bytes(image_file)
                print(f"Imagem: drafts/{image_file} ({len(image_bytes)} bytes)")
            except FileNotFoundError:
                print(f"Card local drafts/{image_file} não encontrado; tentando raw URL...")
        if image_bytes is None and image_url:
            image_bytes = image.download_image(image_url)
            print(f"Imagem (download): {image_url}")

    # Decide onde entra o link da documentação (ver config.LINK_PLACEMENT).
    text_to_post = text
    comment_text = None
    if source and config.LINK_PLACEMENT == "body":
        text_to_post = f"{text}\n\n📄 Documentação: {source}"
    elif source and config.LINK_PLACEMENT == "comment":
        comment_text = f"📄 Documentação da novidade: {source}"

    if dry_run:
        print("\n[dry-run] Texto que seria publicado:\n")
        print(text_to_post)
        print(f"\n[dry-run] Comentário com link: {comment_text or '(nenhum)'}")
        print(f"[dry-run] Formato: {'carrossel (PDF)' if as_carousel else 'imagem'}")
        size = len(doc_bytes) if as_carousel else (len(image_bytes) if image_bytes else 0)
        print(f"[dry-run] Mídia: {size} bytes")
        return 0

    url = linkedin.publish(
        text_to_post, image_bytes, comment_text=comment_text,
        doc_bytes=doc_bytes, doc_title=issue.get("title") or "Novidade",
    )
    print(f"Publicado no LinkedIn ({'carrossel' if as_carousel else 'imagem'}): "
          f"{url or '(URL não retornada nos headers)'}")

    comment = (
        f"✅ Publicado no LinkedIn com sucesso.\n\n"
        f"{('🔗 ' + url) if url else '(LinkedIn não retornou a URL do post nos headers.)'}"
    )
    github_issues.add_comment(issue_number, comment)
    github_issues.remove_label(issue_number, config.LABEL_PENDING)
    github_issues.add_labels(issue_number, [config.LABEL_PUBLISHED])
    github_issues.close_issue(issue_number)
    print("Issue atualizada e fechada.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Publica uma issue aprovada no LinkedIn.")
    parser.add_argument("--issue", type=int, default=None, help="Número da issue.")
    parser.add_argument("--dry-run", action="store_true", help="Não publica; só imprime.")
    args = parser.parse_args()

    issue_number = args.issue or (int(os.environ["ISSUE_NUMBER"]) if os.environ.get("ISSUE_NUMBER") else None)
    if not issue_number:
        parser.error("Informe --issue N ou a variável de ambiente ISSUE_NUMBER.")
    return run(issue_number=issue_number, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
