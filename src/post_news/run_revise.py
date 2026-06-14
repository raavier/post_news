"""Revisa o TEXTO de uma issue de rascunho a partir de um comentário do usuário.

Acionado quando alguém comenta na issue começando com `/revisar` (ver
.github/workflows/revise.yml). Pega o texto atual do post + o pedido de ajuste e
manda o Gemini reescrever, preservando o card e os metadados. Pode ser repetido:
cada `/revisar` parte do texto mais recente.

Uso:
    python -m post_news.run_revise --issue 20 --feedback "deixa mais técnico"
    ISSUE_NUMBER=20 COMMENT_BODY="/revisar encurta" python -m post_news.run_revise

Requer: GEMINI_API_KEY, GITHUB_TOKEN, GITHUB_REPOSITORY.
"""
from __future__ import annotations

import argparse
import os

from . import config, generate, github_issues
from .run_regenerate import recover_entry


def _extract_feedback(comment_body: str) -> str | None:
    """Devolve o feedback (sem o prefixo) ou None se o comentário não for /revisar."""
    text = (comment_body or "").strip()
    if not text.startswith(config.REVISE_COMMAND):
        return None
    return text[len(config.REVISE_COMMAND):].strip()


def run(issue_number: int, comment_body: str) -> int:
    feedback = _extract_feedback(comment_body)
    if feedback is None:
        print(f"Comentário não começa com '{config.REVISE_COMMAND}'. Nada a fazer.")
        return 0
    if not feedback:
        github_issues.add_comment(
            issue_number,
            f"ℹ️ Para revisar, escreva o ajuste após o comando, ex.: "
            f"`{config.REVISE_COMMAND} deixa mais técnico e encurta`.",
        )
        print("Comando /revisar sem texto de ajuste.")
        return 0

    issue = github_issues.get_issue(issue_number)
    parsed = github_issues.parse_issue_body(issue.get("body") or "")
    entry = recover_entry(issue, parsed)

    novo = generate.revise_post_text(entry, parsed.get("post_text") or "", feedback)
    body = github_issues.build_issue_body(
        entry, novo, parsed.get("image_url") or "", parsed.get("image_file") or ""
    )
    github_issues.update_issue_body(issue_number, body)
    github_issues.add_comment(
        issue_number,
        f"✅ Texto revisado conforme seu comentário.\n\n"
        f"> {feedback}\n\n"
        f"---\n\n{novo}\n\n"
        f"Comente `{config.REVISE_COMMAND} ...` de novo para refinar.",
    )
    print(f"Issue #{issue_number} revisada:\n\n{novo}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Revisa o texto de uma issue via comentário.")
    parser.add_argument("--issue", type=int, default=None, help="Número da issue.")
    parser.add_argument("--feedback", default=None, help="Comentário (com ou sem o prefixo).")
    args = parser.parse_args()
    issue_number = args.issue or (int(os.environ["ISSUE_NUMBER"]) if os.environ.get("ISSUE_NUMBER") else None)
    if not issue_number:
        parser.error("Informe --issue N ou a variável de ambiente ISSUE_NUMBER.")
    comment_body = args.feedback if args.feedback is not None else os.environ.get("COMMENT_BODY", "")
    return run(issue_number, comment_body)


if __name__ == "__main__":
    raise SystemExit(main())
