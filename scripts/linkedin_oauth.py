#!/usr/bin/env python3
"""Helper LOCAL para obter o access token, refresh token e o URN do LinkedIn.

Passo único de configuração. Roda um servidor local para receber o callback do
OAuth 2.0 (Authorization Code), troca o code por tokens e descobre o seu URN de
pessoa via OpenID Connect (/v2/userinfo).

Pré-requisitos:
1. Crie um app em https://www.linkedin.com/developers/apps
2. Adicione o produto "Share on LinkedIn" (e "Sign In with LinkedIn using OpenID Connect").
3. Em Auth, adicione a Redirect URL: http://localhost:8000/callback
4. Pegue o Client ID e Client Secret.

Uso:
    LINKEDIN_CLIENT_ID=xxx LINKEDIN_CLIENT_SECRET=yyy python scripts/linkedin_oauth.py

Ao final, copie os valores para os secrets do repositório:
    LINKEDIN_ACCESS_TOKEN, LINKEDIN_AUTHOR_URN
(guarde também o refresh token para renovar quando expirar ~60 dias).
"""
from __future__ import annotations

import os
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

REDIRECT_URI = os.environ.get("LINKEDIN_REDIRECT_URI", "http://localhost:8000/callback")
SCOPES = os.environ.get("LINKEDIN_SCOPES", "openid profile w_member_social")
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"

_auth_code: str | None = None


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        global _auth_code
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        _auth_code = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = "Autorizacao recebida. Pode fechar esta aba e voltar ao terminal."
        if not _auth_code:
            msg = "Falha: nenhum code recebido. " + str(params)
        self.wfile.write(f"<html><body><h3>{msg}</h3></body></html>".encode("utf-8"))

    def log_message(self, *args):  # silencia logs do servidor
        pass


def main() -> int:
    client_id = os.environ.get("LINKEDIN_CLIENT_ID")
    client_secret = os.environ.get("LINKEDIN_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Defina LINKEDIN_CLIENT_ID e LINKEDIN_CLIENT_SECRET no ambiente.", file=sys.stderr)
        return 1

    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    }
    auth_link = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"
    print("Abrindo o navegador para autorizar...\n", auth_link, "\n")
    webbrowser.open(auth_link)

    host, port = "localhost", int(urllib.parse.urlparse(REDIRECT_URI).port or 8000)
    server = HTTPServer((host, port), _Handler)
    print(f"Aguardando callback em {REDIRECT_URI} ...")
    while _auth_code is None:
        server.handle_request()

    print("Code recebido. Trocando por tokens...")
    token_resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": _auth_code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    token_resp.raise_for_status()
    tokens = token_resp.json()
    access_token = tokens["access_token"]

    userinfo = requests.get(
        USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=30
    )
    userinfo.raise_for_status()
    sub = userinfo.json()["sub"]
    author_urn = f"urn:li:person:{sub}"

    print("\n=== Configure estes secrets no repositório ===")
    print(f"LINKEDIN_ACCESS_TOKEN={access_token}")
    print(f"LINKEDIN_AUTHOR_URN={author_urn}")
    if tokens.get("refresh_token"):
        print(f"\n(Guarde para renovar) LINKEDIN_REFRESH_TOKEN={tokens['refresh_token']}")
    print(f"\nExpira em ~{tokens.get('expires_in', '??')} segundos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
