"""
pricing.py — Cost computation from token counts using Anthropic published pricing.

Prices are per 1,000,000 tokens (USD).
Cache reads are billed at 10% of input price.
Cache writes are billed at 125% of input price.

To override pricing (e.g. when Anthropic changes rates), add a "pricing" key
to ~/.claudelens/config.json:

  "pricing": {
    "claude-sonnet-4-6": { "input": 3.00, "output": 15.00 }
  }
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)

# Prices in USD per 1,000,000 tokens
_DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6":            {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6":          {"input":  3.00, "output": 15.00},
    "claude-haiku-4-5-20251001":  {"input":  0.80, "output":  4.00},
    # Aliases / alternate model strings seen in JSONL logs
    "claude-opus-4":              {"input": 15.00, "output": 75.00},
    "claude-sonnet-4":            {"input":  3.00, "output": 15.00},
    "claude-haiku-4-5":           {"input":  0.80, "output":  4.00},
}

_CACHE_READ_MULTIPLIER  = 0.10   # 10% of input price
_CACHE_WRITE_MULTIPLIER = 1.25   # 125% of input price

# Runtime override loaded from config (set by main.py on startup)
_pricing_override: dict[str, dict[str, float]] = {}


def set_pricing_override(override: dict[str, dict[str, float]]) -> None:
    """Called by main.py when it loads config.json."""
    global _pricing_override
    _pricing_override = override or {}


def _get_rates(model: str) -> Optional[dict[str, float]]:
    """Return pricing rates for a model, checking overrides first."""
    if not model:
        return None
    if model in _pricing_override:
        return _pricing_override[model]
    if model in _DEFAULT_PRICING:
        return _DEFAULT_PRICING[model]
    # Fuzzy match: strip version suffix and try again
    base = model.rsplit("-", 1)[0]
    if not base or base == model:
        # No suffix to strip — avoid matching everything with an empty prefix
        log.warning("No pricing found for model '%s'; cost will be 0", model)
        return None
    for key, rates in {**_DEFAULT_PRICING, **_pricing_override}.items():
        if key.startswith(base):
            log.debug("Pricing fuzzy match: %s → %s", model, key)
            return rates
    log.warning("No pricing found for model '%s'; cost will be 0", model)
    return None


def compute_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """
    Return estimated cost in USD for a set of token counts.

    Args:
        model:              Model ID string from JSONL (e.g. 'claude-sonnet-4-6')
        input_tokens:       Standard input tokens
        output_tokens:      Output tokens
        cache_read_tokens:  Tokens served from prompt cache (billed at 10% input)
        cache_write_tokens: Tokens written to prompt cache (billed at 125% input)

    Returns:
        Cost in USD (float), rounded to 6 decimal places.
    """
    rates = _get_rates(model)
    if not rates:
        return 0.0

    input_price  = rates["input"]
    output_price = rates["output"]

    cost = (
        input_tokens        * input_price                        / 1_000_000
        + output_tokens     * output_price                       / 1_000_000
        + cache_read_tokens * input_price * _CACHE_READ_MULTIPLIER  / 1_000_000
        + cache_write_tokens * input_price * _CACHE_WRITE_MULTIPLIER / 1_000_000
    )
    return round(cost, 6)


def known_models() -> list[str]:
    """Return all model IDs we have pricing for (default + overrides)."""
    return sorted({**_DEFAULT_PRICING, **_pricing_override}.keys())
