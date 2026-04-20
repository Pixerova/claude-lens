"""
test_parser.py — Tests for parser.py: JSONL parsing, edge cases, and field
                 extraction correctness (both Claude Code and Cowork sources).

No filesystem watchers are started in these tests (those require watchdog
which needs real directories; we test the parsing functions directly).
"""

import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

from parser import parse_code_session, _extract_title
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
             "message": {"role": "assistant", "model": "claude-sonnet-4-6",
                         "content": "resp1",
                         "usage": {"input_tokens": 500, "output_tokens": 200,
                                   "cache_read_input_tokens": 0,
                                   "cache_creation_input_tokens": 0}}},
            {"type": "user",      "sessionId": "s1", "timestamp": t2,
             "message": {"role": "user", "content": "msg2"}},
            {"type": "assistant", "sessionId": "s1", "timestamp": t3,
             "message": {"role": "assistant", "model": "claude-sonnet-4-6",
                         "content": "resp2",
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

    def test_no_timestamps_returns_none(self, tmp_path):
        """Events with no timestamp field must return None (not IndexError)."""
        event = {
            "type": "user",
            "sessionId": "s1",
            "message": {"role": "user", "content": "hi"},
        }
        f = write_jsonl(tmp_path / "no-ts.jsonl", [event])
        assert parse_code_session(f) is None

    def test_synthetic_model_not_stored(self, tmp_path):
        """<synthetic> model label must be skipped; real model should win."""
        t0 = "2026-04-10T09:00:00+00:00"
        t1 = "2026-04-10T09:10:00+00:00"
        t2 = "2026-04-10T09:20:00+00:00"
        events = [
            {"type": "user", "sessionId": "s1", "timestamp": t0,
             "message": {"role": "user", "content": "hello"}},
            # synthetic event first — should be ignored
            {"type": "assistant", "sessionId": "s1", "timestamp": t1,
             "message": {"role": "assistant", "model": "<synthetic>",
                         "content": "...",
                         "usage": {"input_tokens": 0, "output_tokens": 0,
                                   "cache_read_input_tokens": 0,
                                   "cache_creation_input_tokens": 0}}},
            # real model event second — should win
            {"type": "assistant", "sessionId": "s1", "timestamp": t2,
             "message": {"role": "assistant", "model": "claude-sonnet-4-6",
                         "content": "reply",
                         "usage": {"input_tokens": 100, "output_tokens": 50,
                                   "cache_read_input_tokens": 0,
                                   "cache_creation_input_tokens": 0}}},
        ]
        f = write_jsonl(tmp_path / "synthetic.jsonl", events)
        result = parse_code_session(f)
        assert result is not None
        assert result["model"] == "claude-sonnet-4-6"

    def test_only_synthetic_model_stays_unknown(self, tmp_path):
        """If only <synthetic> events exist, model should remain 'unknown'."""
        t0 = "2026-04-10T09:00:00+00:00"
        t1 = "2026-04-10T09:10:00+00:00"
        events = [
            {"type": "user", "sessionId": "s1", "timestamp": t0,
             "message": {"role": "user", "content": "hello"}},
            {"type": "assistant", "sessionId": "s1", "timestamp": t1,
             "message": {"role": "assistant", "model": "<synthetic>",
                         "content": "...",
                         "usage": {"input_tokens": 0, "output_tokens": 0,
                                   "cache_read_input_tokens": 0,
                                   "cache_creation_input_tokens": 0}}},
        ]
        f = write_jsonl(tmp_path / "only-synthetic.jsonl", events)
        result = parse_code_session(f)
        assert result is not None
        assert result["model"] == "unknown"


class TestExtractTitle:

    def test_plain_string(self):
        assert _extract_title("Fix the login bug") == "Fix the login bug"

    def test_plain_string_truncated_to_200(self):
        long = "x" * 300
        result = _extract_title(long)
        assert result == "x" * 200

    def test_content_block_array_extracts_text(self):
        content = [
            {"type": "text", "text": "Hello world"},
            {"type": "tool_use", "id": "tu_1", "name": "Read"},
        ]
        assert _extract_title(content) == "Hello world"

    def test_content_block_array_joins_multiple_text_blocks(self):
        content = [
            {"type": "text", "text": "Part one"},
            {"type": "text", "text": "part two"},
        ]
        assert _extract_title(content) == "Part one part two"

    def test_empty_string_returns_none(self):
        assert _extract_title("") is None

    def test_empty_list_returns_none(self):
        assert _extract_title([]) is None

    def test_non_text_blocks_only_returns_none(self):
        content = [{"type": "tool_use", "id": "tu_1", "name": "Bash"}]
        assert _extract_title(content) is None

    def test_unsupported_type_returns_none(self):
        assert _extract_title(42) is None

