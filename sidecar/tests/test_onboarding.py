"""
test_onboarding.py — Tests for onboarding status helpers and endpoints.

Coverage:
  - _read_onboarding_complete: absent config, complete flag, malformed JSON
  - _write_onboarding_complete: creates missing directory, preserves existing keys,
    sequential-write idempotency
  - GET /onboarding/status: returns correct boolean in both states
  - POST /onboarding/complete: writes flag, preserves keys, returns ok
"""

import json
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import main as m

pytestmark = pytest.mark.asyncio


# ══════════════════════════════════════════════════════════════════════════════
# Helper: _read_onboarding_complete
# ══════════════════════════════════════════════════════════════════════════════

class TestReadOnboardingComplete:
    def test_returns_false_when_config_absent(self, tmp_path, monkeypatch):
        """No config.json → onboarding not complete."""
        monkeypatch.setattr(m, "CONFIG_PATH", tmp_path / "config.json")
        assert m._read_onboarding_complete() is False

    def test_returns_false_when_flag_missing_from_config(self, tmp_path, monkeypatch):
        """Config exists but has no onboardingComplete key → False."""
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"hotkey": "Option+Space"}))
        monkeypatch.setattr(m, "CONFIG_PATH", cfg)
        assert m._read_onboarding_complete() is False

    def test_returns_false_when_flag_is_false(self, tmp_path, monkeypatch):
        """onboardingComplete: false → False."""
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"onboardingComplete": False}))
        monkeypatch.setattr(m, "CONFIG_PATH", cfg)
        assert m._read_onboarding_complete() is False

    def test_returns_true_when_flag_set(self, tmp_path, monkeypatch):
        """onboardingComplete: true → True."""
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"onboardingComplete": True}))
        monkeypatch.setattr(m, "CONFIG_PATH", cfg)
        assert m._read_onboarding_complete() is True

    def test_returns_false_on_malformed_json(self, tmp_path, monkeypatch):
        """Malformed JSON must not raise — returns False instead."""
        cfg = tmp_path / "config.json"
        cfg.write_text("{this is not json{{}")
        monkeypatch.setattr(m, "CONFIG_PATH", cfg)
        # Must not raise
        result = m._read_onboarding_complete()
        assert result is False

    def test_returns_false_on_non_object_json(self, tmp_path, monkeypatch):
        """Valid JSON but not an object (e.g. a list) → False without raising."""
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps([1, 2, 3]))
        monkeypatch.setattr(m, "CONFIG_PATH", cfg)
        assert m._read_onboarding_complete() is False


# ══════════════════════════════════════════════════════════════════════════════
# Helper: _write_onboarding_complete
# ══════════════════════════════════════════════════════════════════════════════

class TestWriteOnboardingComplete:
    def test_creates_config_when_absent(self, tmp_path, monkeypatch):
        """Creates config.json with the flag when the file does not exist."""
        cfg = tmp_path / "config.json"
        monkeypatch.setattr(m, "CONFIG_PATH", cfg)
        m._write_onboarding_complete()
        data = json.loads(cfg.read_text())
        assert data["onboardingComplete"] is True

    def test_creates_missing_parent_directory(self, tmp_path, monkeypatch):
        """Creates ~/.claudelens/ (and any intermediate dirs) if absent."""
        cfg = tmp_path / "nested" / "deep" / "config.json"
        monkeypatch.setattr(m, "CONFIG_PATH", cfg)
        m._write_onboarding_complete()
        assert cfg.exists()
        data = json.loads(cfg.read_text())
        assert data["onboardingComplete"] is True

    def test_preserves_existing_keys(self, tmp_path, monkeypatch):
        """Pre-existing config keys must survive the write."""
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({
            "hotkey": "Option+Space",
            "retentionDays": 14,
        }))
        monkeypatch.setattr(m, "CONFIG_PATH", cfg)
        m._write_onboarding_complete()
        data = json.loads(cfg.read_text())
        assert data["onboardingComplete"] is True
        assert data["hotkey"] == "Option+Space"
        assert data["retentionDays"] == 14

    def test_idempotent_when_already_set(self, tmp_path, monkeypatch):
        """Calling the helper twice leaves a valid config with the flag set."""
        cfg = tmp_path / "config.json"
        monkeypatch.setattr(m, "CONFIG_PATH", cfg)
        m._write_onboarding_complete()
        m._write_onboarding_complete()
        data = json.loads(cfg.read_text())
        assert data["onboardingComplete"] is True

    def test_overwrites_malformed_json_gracefully(self, tmp_path, monkeypatch):
        """If the existing file is corrupt, the write still succeeds."""
        cfg = tmp_path / "config.json"
        cfg.write_text("{bad json")
        monkeypatch.setattr(m, "CONFIG_PATH", cfg)
        # Should not raise
        m._write_onboarding_complete()
        data = json.loads(cfg.read_text())
        assert data["onboardingComplete"] is True

    def test_concurrent_writes_leave_valid_json(self, tmp_path, monkeypatch):
        """Multiple threads writing simultaneously must not corrupt the file."""
        cfg = tmp_path / "config.json"
        monkeypatch.setattr(m, "CONFIG_PATH", cfg)

        errors: list[Exception] = []

        def _write():
            try:
                m._write_onboarding_complete()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_write) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent writes raised: {errors}"
        # File must still be valid JSON with the flag set.
        data = json.loads(cfg.read_text())
        assert data["onboardingComplete"] is True


# ══════════════════════════════════════════════════════════════════════════════
# Shared _api_client for endpoint tests
# (mirrors the helper in test_endpoints.py)
# ══════════════════════════════════════════════════════════════════════════════

import contextlib
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone


def _make_mock_poller() -> MagicMock:
    snap = MagicMock()
    snap.weekly_pct = 0.30
    snap.session_pct = 0.10
    snap.weekly_resets_at = "2099-01-01T00:00:00+00:00"
    snap.recorded_at = datetime.now(timezone.utc).isoformat()
    snap.is_stale = False

    p = MagicMock()
    p.current = snap
    p.interval_sec = 300
    p.auth_error = False
    p.is_sleeping = False
    p.active_until = None
    p.force_refresh = AsyncMock(return_value=snap)
    p.stop = MagicMock()
    return p


@contextlib.asynccontextmanager
async def _api_client(tmp_config_path: Path):
    """Yield an AsyncClient with module state patched to use tmp_config_path."""
    saved = {
        "_poller":            m._poller,
        "_config":            m._config,
        "_all_suggestions":   m._all_suggestions,
        "_suggestions_yaml_error": m._suggestions_yaml_error,
        "_prior_weekly_pct":  m._prior_weekly_pct,
        "_prior_recorded_at": m._prior_recorded_at,
    }
    m._poller = _make_mock_poller()
    m._config = m.DEFAULT_CONFIG.copy()
    m._all_suggestions = []
    m._suggestions_yaml_error = None
    m._prior_weekly_pct = None
    m._prior_recorded_at = None

    transport = httpx.ASGITransport(app=m.app)
    try:
        with patch("main.is_authenticated", return_value=True), \
             patch.object(m, "CONFIG_PATH", tmp_config_path):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        for k, v in saved.items():
            setattr(m, k, v)


# ══════════════════════════════════════════════════════════════════════════════
# GET /onboarding/status
# ══════════════════════════════════════════════════════════════════════════════

async def test_onboarding_status_false_when_config_absent(isolated_db, tmp_path):
    """Returns complete: false when config.json does not exist."""
    cfg = tmp_path / "config.json"   # file intentionally not created
    async with _api_client(cfg) as client:
        resp = await client.get("/onboarding/status")
    assert resp.status_code == 200
    assert resp.json() == {"complete": False}


async def test_onboarding_status_false_when_flag_missing(isolated_db, tmp_path):
    """Returns complete: false when config exists but lacks the flag."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"hotkey": "Option+Space"}))
    async with _api_client(cfg) as client:
        resp = await client.get("/onboarding/status")
    assert resp.status_code == 200
    assert resp.json() == {"complete": False}


async def test_onboarding_status_true_after_flag_written(isolated_db, tmp_path):
    """Returns complete: true when onboardingComplete is true in config."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"onboardingComplete": True}))
    async with _api_client(cfg) as client:
        resp = await client.get("/onboarding/status")
    assert resp.status_code == 200
    assert resp.json() == {"complete": True}


async def test_onboarding_status_false_on_malformed_config(isolated_db, tmp_path):
    """Malformed config.json → complete: false without 500."""
    cfg = tmp_path / "config.json"
    cfg.write_text("{not valid json")
    async with _api_client(cfg) as client:
        resp = await client.get("/onboarding/status")
    assert resp.status_code == 200
    assert resp.json() == {"complete": False}


# ══════════════════════════════════════════════════════════════════════════════
# POST /onboarding/complete
# ══════════════════════════════════════════════════════════════════════════════

async def test_onboarding_complete_returns_ok(isolated_db, tmp_path):
    """Response body is {"status": "ok", "complete": true}."""
    cfg = tmp_path / "config.json"
    async with _api_client(cfg) as client:
        resp = await client.post("/onboarding/complete")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["complete"] is True


async def test_onboarding_complete_writes_flag_to_disk(isolated_db, tmp_path):
    """Flag is persisted to config.json after a successful POST."""
    cfg = tmp_path / "config.json"
    async with _api_client(cfg) as client:
        await client.post("/onboarding/complete")
    assert cfg.exists()
    data = json.loads(cfg.read_text())
    assert data["onboardingComplete"] is True


async def test_onboarding_complete_preserves_existing_keys(isolated_db, tmp_path):
    """Pre-existing config keys are not clobbered by the POST."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"retentionDays": 60, "hotkey": "Cmd+Shift+L"}))
    async with _api_client(cfg) as client:
        await client.post("/onboarding/complete")
    data = json.loads(cfg.read_text())
    assert data["onboardingComplete"] is True
    assert data["retentionDays"] == 60
    assert data["hotkey"] == "Cmd+Shift+L"


async def test_onboarding_complete_then_status_returns_true(isolated_db, tmp_path):
    """Status endpoint reflects the flag immediately after POST."""
    cfg = tmp_path / "config.json"
    async with _api_client(cfg) as client:
        post_resp = await client.post("/onboarding/complete")
        assert post_resp.status_code == 200
        get_resp = await client.get("/onboarding/status")
    assert get_resp.json() == {"complete": True}


async def test_onboarding_complete_is_idempotent(isolated_db, tmp_path):
    """Calling POST twice is safe — second call also returns ok."""
    cfg = tmp_path / "config.json"
    async with _api_client(cfg) as client:
        r1 = await client.post("/onboarding/complete")
        r2 = await client.post("/onboarding/complete")
    assert r1.status_code == 200
    assert r2.status_code == 200
    data = json.loads(cfg.read_text())
    assert data["onboardingComplete"] is True
