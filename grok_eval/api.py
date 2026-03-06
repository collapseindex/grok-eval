"""Grok + Umbra HTTP helpers and terminal formatting."""

from __future__ import annotations

import os
import sys
import time

import httpx

# ── Defaults ──────────────────────────────────────────────────────
XAI_BASE = "https://api.x.ai/v1"
GROK_REASONING = "grok-4.20-experimental-beta-0304-reasoning"
GROK_NON_REASONING = "grok-4.20-experimental-beta-0304-non-reasoning"
DEFAULT_UMBRA_URL = "http://127.0.0.1:8400"


# ── URL validation ────────────────────────────────────────────────
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def validate_umbra_url(url: str) -> str:
    """Validate Umbra URL is localhost-only to prevent SSRF."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host not in _ALLOWED_HOSTS:
        print(f"{RED}Error: Umbra URL must be localhost (got: {host}){RESET}")
        print("Umbra runs locally. Use http://127.0.0.1:8400")
        sys.exit(1)
    if parsed.scheme not in ("http", "https"):
        print(f"{RED}Error: Umbra URL must use http/https{RESET}")
        sys.exit(1)
    return url


# ── API helpers ───────────────────────────────────────────────────
def umbra_check(
    client: httpx.Client,
    umbra_url: str,
    agent: str,
    action: str,
    escalation: bool = False,
) -> tuple[dict, float]:
    """POST /check to Umbra. Returns (response_json, latency_ms)."""
    body: dict = {"agent": agent, "action": action}
    if escalation:
        body["escalation"] = True
    t0 = time.perf_counter()
    resp = client.post(f"{umbra_url}/check", json=body)
    latency_ms = (time.perf_counter() - t0) * 1000
    resp.raise_for_status()
    return resp.json(), latency_ms


def grok_chat(
    client: httpx.Client,
    api_key: str,
    system: str,
    prompt: str,
    model: str = GROK_REASONING,
    temperature: float = 0.7,
    max_tokens: int = 200,
) -> dict:
    """Call Grok chat completions. Returns dict with content, latency, tokens, error."""
    t0 = time.perf_counter()
    try:
        resp = client.post(
            f"{XAI_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=60.0,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        content = data["choices"][0]["message"]["content"].strip()
        return {
            "content": content,
            "latency_ms": round(latency_ms, 2),
            "tokens_in": usage.get("prompt_tokens", 0),
            "tokens_out": usage.get("completion_tokens", 0),
            "error": None,
        }
    except httpx.HTTPStatusError as e:
        latency_ms = (time.perf_counter() - t0) * 1000
        return {
            "content": None,
            "latency_ms": round(latency_ms, 2),
            "tokens_in": 0,
            "tokens_out": 0,
            "error": f"HTTP {e.response.status_code}",
        }
    except Exception:
        latency_ms = (time.perf_counter() - t0) * 1000
        return {
            "content": None,
            "latency_ms": round(latency_ms, 2),
            "tokens_in": 0,
            "tokens_out": 0,
            "error": "request_failed",
        }


def get_xai_key() -> str:
    """Read XAI_API_KEY from environment. Exits if missing."""
    key = os.environ.get("XAI_API_KEY", "")
    if not key:
        print(f"{RED}Error: XAI_API_KEY not set{RESET}")
        print("Set it:  $env:XAI_API_KEY = \"your-key\"")
        sys.exit(1)
    return key


# ── Terminal colours ──────────────────────────────────────────────
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
WHITE = "\033[97m"
RESET = "\033[0m"

AGENT_TERM_COLORS = {
    "grok-captain": CYAN,
    "grok-harper": GREEN,
    "grok-benjamin": YELLOW,
    "grok-lucas": MAGENTA,
}


def colorize_decision(d: str) -> str:
    colors = {"allow": GREEN, "warn": YELLOW, "gate": RED, "block": f"{RED}{BOLD}"}
    return f"{colors.get(d, '')}{d.upper()}{RESET}"


def print_header(text: str) -> None:
    w = 64
    print(f"\n{BOLD}{CYAN}{'=' * w}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * w}{RESET}\n")


def print_section(num: int, text: str) -> None:
    print(f"\n{YELLOW}[{num}] {text}{RESET}")
