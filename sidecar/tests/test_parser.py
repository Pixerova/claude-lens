"""
test_parser.py — Tests for parser.py: JSONL parsing, Cowork JSON parsing,
                 edge cases, and field extraction correctness.

No filesystem watchers are started in these tests (those require watchdog
which needs real directories; we test the parsing functions directly).
"""

import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

from parser import parse_code_session, parse_cowork_session
from conftest import write_jsonl, make_code_events


# ── parse_code_session ────────────────────────────────────────────────────────

class TestParseCodeSession:

    def test_valid_session_returns_dict(self, tmp_path):
        events = make_code_events()
        f = write_jsonl(tmp_path / "session.jsonl", events)
        result = parse_code_session(f)
        assert result is not None
        assert isinstance(result, dict)

    def test_source_is_code(self, tmp_path):
        f = write_jsonl(tmp_path / "s.jsonl", make_code_events())
        result = parse_code_session(f)
        assert result["source"] == "code"

    def test_session_id_extracted(self, tmp_path):
        events = make_code_events(session_id="my-session-xyz")
        f = write_jsonl(tmp_path / "s.jsonl", events)
        result = parse_code_session(f)
        assert result["session_id"] == "my-session-xyz"

    def test_project_extracted_from_cwd(self, tmp_path):
        events = make_code_events(cwd="/Users/martha/projects/auth-service")
        f = write_jsonl(tmp_path / "s.jsonl", events)
        result = parse_code_session(f)
        assert result["project"] == "auth-service"

    def test_model_extracted_from_assistant_event(self, tmp_path):
        events = make_code_events(model="claude-opus-4-6")
        f = write_jsonl(tmp_path / "s.jsonl", events)
        result = parse_code_session(f)
        assert result["model"] == "claude-opus-4-6"

    def test_token_counts_aggregated(self, tmp_path):
        events = make_code_events(
            input_tokens=1000,
            output_tokens=500,
            cache_read=200,
            cache_write=100,
        )
        f = write_jsonl(tmp_path / "s.jsonl", events)
        result = parse_code_session(f)
        # Cost should be non-zero (tokens were present)
        assert result["cost_usd"] > 0

    def test_cost_is_positive_for_known_model(self, tmp_path):
        events = make_code_events(
            model="claude-sonnet-4-6",
            input_tokens=10_000,
            output_tokens=5_000,
        )
        f = write_jsonl(tmp_path / "s.jsonl", events)
        result = parse_code_session(f)
        assert result["cost_usd"] > 0

    def test_duration_calculated_from_timestamps(self, tmp_path):
        # Events are 45 minutes apart in make_code_events (09:00 → 09:45)
        events = make_code_events()
        f = write_jsonl(tmp_path / "s.jsonl", events)
        result = parse_code_session(f)
        assert result["duration_sec"] == 45 * 60

    def test_started_at_is_earliest_timestamp(self, tmp_path):
        events = make_code_events()
        f = write_jsonl(tmp_path / "s.jsonl", events)
        result = parse_code_session(f)
        assert result["started_at"] == "2026-04-10T09:00:00+00:00"

    def test_ended_at_is_latest_timestamp(self, tmp_path):
        events = make_code_events()
        f = write_jsonl(tmp_path / "s.jsonl", events)
        result = parse_code_session(f)
        assert result["ended_at"] == "2026-04-10T09:45:00+00:00"

    def test_empty_file_returns_none(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        assert parse_code_session(f) is None

    def test_nonexistent_file_returns_none(self, tmp_path):
        assert parse_code_session(tmp_path / "ghost.jsonl") is None

    def test_all_malformed_lines_returns_none(self, tmp_path):
        f = tmp_path / "bad.jsonl"
        f.write_text("not json\nalso not json\n{broken")
        assert parse_code_session(f) is None

    def test_partial_malformed_lines_still_parses(self, tmp_path):
        events = make_code_events()
        lines = [json.dumps(e) for e in events]
        lines.insert(1, "THIS LINE IS CORRUPT")
        (tmp_path / "partial.jsonl").write_text("\n".join(lines))
        result = parse_code_session(tmp_path / "partial.jsonl")
        # Should still parse the valid lines
        assert result is not None

    def test_session_id_falls_back_to_filename(self, tmp_path):
        """When sessionId is absent, the filename stem is used."""
        event = {
            "type": "user",
            "timestamp": "2026-04-10T10:00:00+00:00",
            "message": {"role": "user", "content": "hi"},
        }
        f = write_jsonl(tmp_path / "fallback-id.jsonl", [event])
        result = parse_code_session(f)
        assert result is not None
        assert result["session_id"] == "fallback-id"

    def test_multiple_assistant_events_tokens_summed(self, tmp_path):
        t = "2026-04-10T10:00:00+00:00"
        t2 = "2026-04-10T10:30:00+00:00"
        t3 = "2026-04-10T11:00:00+00:00"
        events = [
            {"type": "user",      "sessionId": "s1", "timestamp": t,
             "message": {"role": "user", "content": "msg1"}},
            {"type": "assistant", "sessionId": "s1", "timestamp": t2,
             "model": "claude-sonnet-4-6",
             "message": {"role": "assistant", "content": "resp1",
                         "usage": {"input_tokens": 500, "output_tokens": 200,
                                   "cache_read_input_tokens": 0,
                                   "cache_creation_input_tokens": 0}}},
            {"type": "user",      "sessionId": "s1", "timestamp": t2,
             "message": {"role": "user", "content": "msg2"}},
            {"type": "assistant", "sessionId": "s1", "timestamp": t3,
             "model": "claude-sonnet-4-6",
             "message": {"role": "assistant", "content": "resp2",
                         "usage": {"input_tokens": 300, "output_tokens": 150,
                                   "cache_read_input_tokens": 0,
                                   "cache_creation_input_tokens": 0}}},
        ]
        f = write_jsonl(tmp_path / "multi.jsonl", events)
        result = parse_code_session(f)
        # Cost should reflect 800 input + 350 output tokens for sonnet
        from pricing import compute_cost
        expected = compute_cost("claude-sonnet-4-6", input_tokens=800, output_tokens=350)
        assert abs(result["cost_usd"] - expected) < 1e-6

    def test_duration_is_non_negative(self, tmp_path):
        # If timestamps are identical, duration should be 0 not negative
        event = {
            "type": "user",
            "sessionId": "s1",
            "timestamp": "2026-04-10T10:00:00+00:00",
            "message": {"role": "user", "content": "hi"},
        }
        f = write_jsonl(tmp_path / "instant.jsonl", [event])
        result = parse_code_session(f)
        assert result is not None
        assert result["duration_sec"] >= 0


# ── parse_cowork_session ──────────────────────────────────────────────────────

class TestParseCoworkSession:

    def _write_cowork(self, tmp_path, data: dict, filename="session.json") -> Path:
        path = tmp_path / filename
        path.write_text(json.dumps(data))
        return path

    def _valid_cowork_data(self, **overrides):
        base = {
            "sessionId": "cowork-sess-001",
            "startedAt": "2026-04-10T14:00:00+00:00",
            "endedAt":   "2026-04-10T14:08:00+00:00",
            "model":     "claude-sonnet-4-6",
            "project":   "browser-automation",
            "usage": {
                "input_tokens": 500,
                "output_tokens": 200,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        }
        return {**base, **overrides}

    def test_valid_session_returns_dict(self, tmp_path):
        f = self._write_cowork(tmp_path, self._valid_cowork_data())
        result = parse_cowork_session(f)
        assert result is not None
        assert isinstance(result, dict)

    def test_source_is_cowork(self, tmp_path):
        f = self._write_cowork(tmp_path, self._valid_cowork_data())
        result = parse_cowork_session(f)
        assert result["source"] == "cowork"

    def test_session_id_extracted(self, tmp_path):
        f = self._write_cowork(tmp_path, self._valid_cowork_data(sessionId="cw-xyz"))
        result = parse_cowork_session(f)
        assert result["session_id"] == "cw-xyz"

    def test_duration_calculated(self, tmp_path):
        # 14:00 → 14:08 = 480 seconds
        f = self._write_cowork(tmp_path, self._valid_cowork_data())
        result = parse_cowork_session(f)
        assert result["duration_sec"] == 480

    def test_cost_is_positive_for_known_model(self, tmp_path):
        f = self._write_cowork(tmp_path, self._valid_cowork_data())
        result = parse_cowork_session(f)
        assert result["cost_usd"] > 0

    def test_project_extracted(self, tmp_path):
        f = self._write_cowork(tmp_path, self._valid_cowork_data(project="invoice-filler"))
        result = parse_cowork_session(f)
        assert result["project"] == "invoice-filler"

    def test_project_from_cwd_uses_leaf(self, tmp_path):
        data = self._valid_cowork_data()
        del data["project"]
        data["cwd"] = "/Users/martha/projects/deep-project"
        f = self._write_cowork(tmp_path, data)
        result = parse_cowork_session(f)
        assert result["project"] == "deep-project"

    def test_session_id_falls_back_to_filename(self, tmp_path):
        data = self._valid_cowork_data()
        del data["sessionId"]
        f = self._write_cowork(tmp_path, data, filename="my-cowork-file.json")
        result = parse_cowork_session(f)
        assert result["session_id"] == "my-cowork-file"

    def test_missing_timestamp_returns_none(self, tmp_path):
        data = self._valid_cowork_data()
        del data["startedAt"]
        f = self._write_cowork(tmp_path, data)
        result = parse_cowork_session(f)
        assert result is None

    def test_invalid_json_returns_none(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not: valid json")
        assert parse_cowork_session(f) is None

    def test_empty_file_returns_none(self, tmp_path):
        f = tmp_path / "empty.json"
        f.write_text("")
        assert parse_cowork_session(f) is None

    def test_nonexistent_file_returns_none(self, tmp_path):
        assert parse_cowork_session(tmp_path / "ghost.json") is None

    def test_array_json_returns_none(self, tmp_path):
        """Top-level JSON array (not an object) should return None."""
        f = tmp_path / "array.json"
        f.write_text(json.dumps([{"key": "value"}]))
        assert parse_cowork_session(f) is None

    def test_alternate_field_names_parsed(self, tmp_path):
        """Support alternative field names seen in different Cowork versions."""
        data = {
            "id":         "alt-id-001",
            "created_at": "2026-04-10T15:00:00+00:00",
            "updated_at": "2026-04-10T15:20:00+00:00",
            "model":      "claude-haiku-4-5-20251001",
            "tokens": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        }
        f = self._write_cowork(tmp_path, data)
        result = parse_cowork_session(f)
        assert result is not None
        assert result["session_id"] == "alt-id-001"
        assert result["duration_sec"] == 20 * 60

    def test_zero_usage_gives_zero_cost(self, tmp_path):
        data = self._valid_cowork_data()
        data["usage"] = {
            "input_tokens": 0, "output_tokens": 0,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        }
        f = self._write_cowork(tmp_path, data)
        result = parse_cowork_session(f)
        assert result["cost_usd"] == 0.0
