"""
test_keychain.py — Tests for keychain.py: token extraction, keyring lookup,
                   security CLI fallback, and failure handling.

macOS Keychain and the `keyring` library are always mocked — no real
Keychain access occurs during tests.
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from keychain import (
    _extract_access_token,
    _get_via_keyring,
    _get_via_security_cli,
    get_oauth_token,
    is_authenticated,
)


# ── _extract_access_token ─────────────────────────────────────────────────────

class TestExtractAccessToken:
    def test_bare_token_returned_as_is(self):
        token = "sk-ant-oat01-abc123xyz"
        result = _extract_access_token(token)
        assert result == token

    def test_json_blob_with_access_token_key(self):
        payload = json.dumps({
            "accessToken": "sk-ant-oat01-from-json",
            "refreshToken": "refresh-xyz",
            "expiresAt": "2026-12-01T00:00:00Z",
        })
        result = _extract_access_token(payload)
        assert result == "sk-ant-oat01-from-json"

    def test_json_blob_with_snake_case_key(self):
        payload = json.dumps({"access_token": "sk-ant-oat01-snake"})
        result = _extract_access_token(payload)
        assert result == "sk-ant-oat01-snake"

    def test_json_blob_prefers_camel_case(self):
        payload = json.dumps({
            "accessToken": "sk-ant-oat01-camel",
            "access_token": "sk-ant-oat01-snake",
        })
        result = _extract_access_token(payload)
        assert result == "sk-ant-oat01-camel"

    def test_json_blob_without_token_returns_none(self):
        payload = json.dumps({"refreshToken": "something", "expiresAt": "..."})
        result = _extract_access_token(payload)
        assert result is None

    def test_unrecognised_string_returns_none(self):
        result = _extract_access_token("not-a-valid-token-format")
        assert result is None

    def test_empty_string_returns_none(self):
        result = _extract_access_token("")
        assert result is None

    def test_whitespace_stripped(self):
        result = _extract_access_token("  sk-ant-oat01-with-spaces  ")
        assert result == "sk-ant-oat01-with-spaces"

    def test_malformed_json_falls_through_to_bare_check(self):
        result = _extract_access_token("{broken json")
        assert result is None  # doesn't start with sk-ant- either


# ── _get_via_keyring ──────────────────────────────────────────────────────────

class TestGetViaKeyring:
    def test_returns_token_when_keyring_succeeds(self):
        with patch("keychain._keyring") as mock_kr:
            mock_kr.get_password.return_value = "sk-ant-oat01-from-keyring"
            result = _get_via_keyring()
        assert result == "sk-ant-oat01-from-keyring"

    def test_returns_none_when_keyring_returns_none(self):
        with patch("keychain._keyring") as mock_kr:
            mock_kr.get_password.return_value = None
            result = _get_via_keyring()
        assert result is None

    def test_returns_none_when_keyring_raises(self):
        with patch("keychain._keyring") as mock_kr:
            mock_kr.get_password.side_effect = Exception("keyring not available")
            result = _get_via_keyring()
        assert result is None

    def test_tries_service_name_as_username_fallback(self):
        """If first get_password returns None, tries again with service as username."""
        with patch("keychain._keyring") as mock_kr:
            mock_kr.get_password.side_effect = [
                None,  # First call returns nothing
                "sk-ant-oat01-second-try",  # Second call succeeds
            ]
            result = _get_via_keyring()
        assert result == "sk-ant-oat01-second-try"
        assert mock_kr.get_password.call_count == 2

    def test_handles_json_blob_from_keyring(self):
        blob = json.dumps({"accessToken": "sk-ant-oat01-json-in-keyring"})
        with patch("keychain._keyring") as mock_kr:
            mock_kr.get_password.return_value = blob
            result = _get_via_keyring()
        assert result == "sk-ant-oat01-json-in-keyring"


# ── _get_via_security_cli ─────────────────────────────────────────────────────

class TestGetViaSecurityCli:
    def test_returns_token_on_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "sk-ant-oat01-from-cli\n"

        with patch("keychain.subprocess.run", return_value=mock_result):
            result = _get_via_security_cli()
        assert result == "sk-ant-oat01-from-cli"

    def test_returns_none_on_nonzero_exit(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("keychain.subprocess.run", return_value=mock_result):
            result = _get_via_security_cli()
        assert result is None

    def test_returns_none_when_subprocess_raises(self):
        with patch("keychain.subprocess.run", side_effect=FileNotFoundError("security not found")):
            result = _get_via_security_cli()
        assert result is None

    def test_handles_json_blob_from_cli(self):
        blob = json.dumps({"accessToken": "sk-ant-oat01-cli-json"})
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = blob

        with patch("keychain.subprocess.run", return_value=mock_result):
            result = _get_via_security_cli()
        assert result == "sk-ant-oat01-cli-json"


# ── get_oauth_token (integration of both methods) ─────────────────────────────

class TestGetOAuthToken:
    def test_uses_keyring_first(self):
        with patch("keychain._get_via_keyring", return_value="sk-ant-oat01-keyring"), \
             patch("keychain._get_via_security_cli") as mock_cli:
            result = get_oauth_token()
        assert result == "sk-ant-oat01-keyring"
        mock_cli.assert_not_called()

    def test_falls_back_to_cli_when_keyring_fails(self):
        with patch("keychain._get_via_keyring", return_value=None), \
             patch("keychain._get_via_security_cli", return_value="sk-ant-oat01-cli"):
            result = get_oauth_token()
        assert result == "sk-ant-oat01-cli"

    def test_returns_none_when_both_methods_fail(self):
        with patch("keychain._get_via_keyring", return_value=None), \
             patch("keychain._get_via_security_cli", return_value=None):
            result = get_oauth_token()
        assert result is None

    def test_returns_token_string(self):
        with patch("keychain._get_via_keyring", return_value="sk-ant-oat01-test"):
            result = get_oauth_token()
        assert isinstance(result, str)
        assert result.startswith("sk-ant-")


# ── is_authenticated ──────────────────────────────────────────────────────────

class TestIsAuthenticated:
    @pytest.fixture(autouse=True)
    def reset_auth_cache(self, monkeypatch):
        """Clear the module-level _auth_cache before each test so results
        from a prior test don't bleed through the 60 s TTL."""
        import keychain
        monkeypatch.setattr(keychain, "_auth_cache", None)

    def test_true_when_token_present(self):
        with patch("keychain.get_oauth_token", return_value="sk-ant-oat01-ok"):
            assert is_authenticated() is True

    def test_false_when_no_token(self):
        with patch("keychain.get_oauth_token", return_value=None):
            assert is_authenticated() is False
