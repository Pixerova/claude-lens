"""
keychain.py — Retrieve the Claude OAuth access token from macOS Keychain.

Claude Code stores credentials under the service name "Claude Code-credentials".
We try two methods in order:
  1. Python `keyring` library  (clean, cross-platform)
  2. macOS `security` CLI      (fallback, macOS-only)

The token has the shape: sk-ant-oat01-...
"""

import json
import subprocess
import logging
import time
from typing import Optional

try:
    import keyring as _keyring
except Exception:
    _keyring = None  # keyring unavailable; CLI fallback will be used

log = logging.getLogger(__name__)

KEYCHAIN_SERVICE = "Claude Code-credentials"


# ── Primary: keyring ──────────────────────────────────────────────────────────

def _get_via_keyring() -> Optional[str]:
    try:
        if _keyring is None:
            return None
        raw = _keyring.get_password(KEYCHAIN_SERVICE, "")
        if not raw:
            # Some keyring backends store under the service name as both service + username
            raw = _keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_SERVICE)
        if raw:
            return _extract_access_token(raw)
    except Exception as exc:
        log.debug("keyring lookup failed: %s", exc)
    return None


# ── Fallback: macOS security CLI ─────────────────────────────────────────────

def _get_via_security_cli() -> Optional[str]:
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return _extract_access_token(result.stdout.strip())
    except Exception as exc:
        log.debug("security CLI lookup failed: %s", exc)
    return None


# ── Token extraction ──────────────────────────────────────────────────────────

def _extract_access_token(raw: str) -> Optional[str]:
    """
    The keychain value may be a raw token string or a JSON blob like:
      {"accessToken": "sk-ant-oat01-...", "refreshToken": "...", "expiresAt": "..."}
    Handle both.
    """
    raw = raw.strip()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            token = data.get("accessToken") or data.get("access_token")
            if not token:
                inner = data.get("claudeAiOauth")
                if isinstance(inner, dict):
                    token = inner.get("accessToken") or inner.get("access_token")
                elif isinstance(inner, str):
                    token = inner
            if token:
                return token
        except json.JSONDecodeError:
            pass
    # Treat as bare token
    if raw.startswith("sk-ant-"):
        return raw
    log.warning("Keychain value found but unrecognised format")
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def get_oauth_token() -> Optional[str]:
    """
    Return the Claude OAuth access token, or None if not found.
    Tries keyring first, then falls back to the macOS security CLI.
    """
    token = _get_via_keyring()
    if token:
        log.debug("OAuth token retrieved via keyring")
        return token

    token = _get_via_security_cli()
    if token:
        log.debug("OAuth token retrieved via security CLI")
        return token

    log.error(
        "Could not retrieve Claude OAuth token from Keychain. "
        "Make sure Claude Code is installed and you are logged in."
    )
    return None


_AUTH_CACHE_TTL = 60.0  # seconds
_auth_cache: tuple[bool, float] | None = None


def is_authenticated() -> bool:
    """Quick check — does a token exist? Result is cached for 60 s to avoid
    repeated Keychain subprocess calls on every /health poll."""
    global _auth_cache
    now = time.monotonic()
    if _auth_cache is not None:
        cached_result, cached_at = _auth_cache
        if now - cached_at < _AUTH_CACHE_TTL:
            return cached_result
    result = get_oauth_token() is not None
    _auth_cache = (result, now)
    return result
