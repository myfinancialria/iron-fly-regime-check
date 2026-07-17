"""Upstox OAuth: turn a one-time authorization ``code`` into a daily access token.

Upstox has no headless login. Once a day you visit the authorize URL, log in +
2FA, and get redirected with ``?code=...``. This exchanges that code for an
``access_token`` and writes it to the repo-root ``.env`` as ``UPSTOX_TOKEN``.
"""
from __future__ import annotations

import os
import sys
import urllib.parse
from pathlib import Path

import requests

TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
AUTHORIZE_URL = "https://api.upstox.com/v2/login/authorization/dialog"

# repo root = .../ironfly_check/login.py -> parents[1]
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def read_env() -> dict[str, str]:
    data: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            data[k.strip()] = v.strip()
    for k in os.environ:
        if k.startswith("UPSTOX_") or k.startswith("IFC_"):
            data[k] = os.environ[k]
    return data


def set_env_value(key: str, value: str) -> None:
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    out, found = [], False
    for line in lines:
        s = line.strip()
        if s.startswith(f"{key}=") or s.startswith(f"{key} ="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n")
    os.environ[key] = value


def authorize_url(env: dict[str, str] | None = None) -> str:
    env = env or read_env()
    api_key = env.get("UPSTOX_API_KEY", "")
    redirect = env.get("UPSTOX_REDIRECT_URI", "")
    if not api_key or not redirect:
        raise SystemExit("Set UPSTOX_API_KEY and UPSTOX_REDIRECT_URI in .env first.")
    q = urllib.parse.urlencode(
        {"response_type": "code", "client_id": api_key, "redirect_uri": redirect}
    )
    return f"{AUTHORIZE_URL}?{q}"


def _extract_code(code_or_url: str) -> str:
    code_or_url = code_or_url.strip()
    if code_or_url.startswith("http"):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(code_or_url).query)
        codes = qs.get("code")
        if not codes:
            raise SystemExit(f"No `code` param found in URL: {code_or_url}")
        return codes[0]
    return code_or_url


def exchange_code(code_or_url: str, env: dict[str, str] | None = None) -> str:
    env = env or read_env()
    api_key = env.get("UPSTOX_API_KEY", "")
    api_secret = env.get("UPSTOX_API_SECRET", "")
    redirect = env.get("UPSTOX_REDIRECT_URI", "")
    if not (api_key and api_secret and redirect):
        raise SystemExit("Missing UPSTOX_API_KEY / UPSTOX_API_SECRET / UPSTOX_REDIRECT_URI in .env")
    code = _extract_code(code_or_url)
    resp = requests.post(
        TOKEN_URL,
        headers={"accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "code": code, "client_id": api_key, "client_secret": api_secret,
            "redirect_uri": redirect, "grant_type": "authorization_code",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise SystemExit(f"Token exchange failed [{resp.status_code}]: {resp.text[:300]}")
    token = resp.json().get("access_token")
    if not token:
        raise SystemExit(f"No access_token in response: {resp.text[:300]}")
    set_env_value("UPSTOX_TOKEN", token)
    return token


def _cli(argv: list[str]) -> None:
    if not argv or argv[0] in ("url", "--url"):
        print("Open this URL in a browser, log in, then copy the redirect URL:\n")
        print(authorize_url())
        print("\nThen run:  python -m ironfly_check login <paste-redirect-url-or-code>")
        return
    token = exchange_code(argv[0])
    print(f"Saved UPSTOX_TOKEN to {ENV_PATH} (…{token[-6:]}). Valid until ~03:30 IST.")


if __name__ == "__main__":
    _cli(sys.argv[1:])
