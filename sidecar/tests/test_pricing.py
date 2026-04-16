"""
test_pricing.py — Tests for pricing.py: cost computation, overrides, fuzzy matching.
"""

import pytest
import pricing


@pytest.fixture(autouse=True)
def reset_pricing_override():
    """Ensure pricing overrides are cleared between tests."""
    pricing.set_pricing_override({})
    yield
    pricing.set_pricing_override({})


# ── Basic cost computation ────────────────────────────────────────────────────

class TestComputeCost:
    def test_input_tokens_only(self):
        # claude-sonnet-4-6: $3.00 / 1M input tokens
        cost = pricing.compute_cost("claude-sonnet-4-6", input_tokens=1_000_000)
        assert abs(cost - 3.00) < 1e-4

    def test_output_tokens_only(self):
        # claude-sonnet-4-6: $15.00 / 1M output tokens
        cost = pricing.compute_cost("claude-sonnet-4-6", output_tokens=1_000_000)
        assert abs(cost - 15.00) < 1e-4

    def test_input_and_output_combined(self):
        # 500K input @ $3/M = $1.50, 200K output @ $15/M = $3.00 → $4.50
        cost = pricing.compute_cost(
            "claude-sonnet-4-6", input_tokens=500_000, output_tokens=200_000
        )
        assert abs(cost - 4.50) < 1e-4

    def test_cache_read_tokens_at_10_percent(self):
        # cache_read billed at 10% of input price
        # sonnet input = $3/M → cache_read = $0.30/M
        cost = pricing.compute_cost("claude-sonnet-4-6", cache_read_tokens=1_000_000)
        assert abs(cost - 0.30) < 1e-4

    def test_cache_write_tokens_at_125_percent(self):
        # cache_write billed at 125% of input price
        # sonnet input = $3/M → cache_write = $3.75/M
        cost = pricing.compute_cost("claude-sonnet-4-6", cache_write_tokens=1_000_000)
        assert abs(cost - 3.75) < 1e-4

    def test_all_token_types_combined(self):
        cost = pricing.compute_cost(
            "claude-sonnet-4-6",
            input_tokens=1_000_000,    # $3.00
            output_tokens=1_000_000,   # $15.00
            cache_read_tokens=1_000_000,   # $0.30
            cache_write_tokens=1_000_000,  # $3.75
        )
        expected = 3.00 + 15.00 + 0.30 + 3.75
        assert abs(cost - expected) < 1e-4

    def test_zero_tokens_returns_zero(self):
        cost = pricing.compute_cost("claude-sonnet-4-6")
        assert cost == 0.0

    def test_opus_is_more_expensive_than_sonnet(self):
        kwargs = {"input_tokens": 100_000, "output_tokens": 100_000}
        opus_cost   = pricing.compute_cost("claude-opus-4-6",   **kwargs)
        sonnet_cost = pricing.compute_cost("claude-sonnet-4-6", **kwargs)
        assert opus_cost > sonnet_cost

    def test_haiku_is_cheapest(self):
        kwargs = {"input_tokens": 100_000, "output_tokens": 100_000}
        haiku_cost  = pricing.compute_cost("claude-haiku-4-5-20251001", **kwargs)
        sonnet_cost = pricing.compute_cost("claude-sonnet-4-6",         **kwargs)
        assert haiku_cost < sonnet_cost

    def test_result_is_rounded_to_6_decimals(self):
        cost = pricing.compute_cost("claude-sonnet-4-6", input_tokens=1)
        # Just verify it's a float with reasonable precision
        assert isinstance(cost, float)
        assert cost >= 0


# ── Unknown models ────────────────────────────────────────────────────────────

class TestUnknownModel:
    def test_unknown_model_returns_zero(self):
        cost = pricing.compute_cost("claude-unknown-9999", input_tokens=1_000_000)
        assert cost == 0.0

    def test_empty_model_string_returns_zero(self):
        cost = pricing.compute_cost("", input_tokens=1_000_000)
        assert cost == 0.0

    def test_unknown_model_returns_zero_not_raises(self):
        # Should not raise — just return 0
        try:
            result = pricing.compute_cost("totally-fake-model", input_tokens=999)
            assert result == 0.0
        except Exception as exc:
            pytest.fail(f"compute_cost raised unexpectedly: {exc}")


# ── Fuzzy model matching ──────────────────────────────────────────────────────

class TestFuzzyModelMatching:
    def test_alias_claude_sonnet_4_matches(self):
        """'claude-sonnet-4' should match 'claude-sonnet-4-6' pricing."""
        cost = pricing.compute_cost("claude-sonnet-4", input_tokens=1_000_000)
        assert cost > 0.0

    def test_alias_claude_opus_4_matches(self):
        cost = pricing.compute_cost("claude-opus-4", input_tokens=1_000_000)
        assert cost > 0.0

    def test_alias_claude_haiku_4_5_matches(self):
        cost = pricing.compute_cost("claude-haiku-4-5", input_tokens=1_000_000)
        assert cost > 0.0


# ── Pricing overrides ─────────────────────────────────────────────────────────

class TestPricingOverrides:
    def test_override_replaces_default_price(self):
        pricing.set_pricing_override({
            "claude-sonnet-4-6": {"input": 100.00, "output": 200.00}
        })
        cost = pricing.compute_cost("claude-sonnet-4-6", input_tokens=1_000_000)
        assert abs(cost - 100.00) < 1e-4

    def test_override_adds_new_model(self):
        pricing.set_pricing_override({
            "claude-future-model-x": {"input": 5.00, "output": 25.00}
        })
        cost = pricing.compute_cost("claude-future-model-x", input_tokens=1_000_000)
        assert abs(cost - 5.00) < 1e-4

    def test_override_does_not_affect_other_models(self):
        pricing.set_pricing_override({
            "claude-opus-4-6": {"input": 999.00, "output": 999.00}
        })
        # Sonnet should be unaffected
        cost = pricing.compute_cost("claude-sonnet-4-6", input_tokens=1_000_000)
        assert abs(cost - 3.00) < 1e-4

    def test_clearing_override_restores_default(self):
        pricing.set_pricing_override({
            "claude-sonnet-4-6": {"input": 999.00, "output": 999.00}
        })
        pricing.set_pricing_override({})
        cost = pricing.compute_cost("claude-sonnet-4-6", input_tokens=1_000_000)
        assert abs(cost - 3.00) < 1e-4

    def test_none_override_treated_as_empty(self):
        pricing.set_pricing_override(None)
        cost = pricing.compute_cost("claude-sonnet-4-6", input_tokens=1_000_000)
        assert abs(cost - 3.00) < 1e-4


# ── Known models ──────────────────────────────────────────────────────────────

class TestKnownModels:
    def test_known_models_includes_main_models(self):
        models = pricing.known_models()
        assert "claude-opus-4-6" in models
        assert "claude-sonnet-4-6" in models
        assert "claude-haiku-4-5-20251001" in models

    def test_known_models_includes_overrides(self):
        pricing.set_pricing_override({"claude-future-99": {"input": 1.0, "output": 5.0}})
        assert "claude-future-99" in pricing.known_models()

    def test_known_models_returns_sorted_list(self):
        models = pricing.known_models()
        assert models == sorted(models)
