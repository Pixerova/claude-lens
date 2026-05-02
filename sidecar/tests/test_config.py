"""
test_config.py — Tests for config loading and fraction-field validation.
"""

import copy
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import main as m


def _merged(**overrides) -> dict:
    """Return a deep-merged config with the given leaf overrides applied."""
    def _set(d, path, value):
        keys = path.split(".")
        for k in keys[:-1]:
            d = d[k]
        d[keys[-1]] = value

    base = copy.deepcopy(m.DEFAULT_CONFIG)
    for path, value in overrides.items():
        _set(base, path, value)
    return base


# ── Valid config passes through unchanged ─────────────────────────────────────

def test_valid_config_unchanged():
    cfg = copy.deepcopy(m.DEFAULT_CONFIG)
    assert m._validate_config(cfg) == cfg


# ── warnings ──────────────────────────────────────────────────────────────────

def test_warning_percentage_above_1_is_replaced(caplog):
    cfg = _merged(**{"warnings.warningPercentage": 1.5})
    with caplog.at_level(logging.ERROR, logger="main"):
        result = m._validate_config(cfg)
    assert result["warnings"]["warningPercentage"] == m.DEFAULT_CONFIG["warnings"]["warningPercentage"]
    assert "warnings.warningPercentage" in caplog.text


def test_critical_percentage_negative_is_replaced(caplog):
    cfg = _merged(**{"warnings.criticalPercentage": -0.1})
    with caplog.at_level(logging.ERROR, logger="main"):
        result = m._validate_config(cfg)
    assert result["warnings"]["criticalPercentage"] == m.DEFAULT_CONFIG["warnings"]["criticalPercentage"]
    assert "warnings.criticalPercentage" in caplog.text


def test_warning_percentage_string_is_replaced(caplog):
    cfg = _merged(**{"warnings.warningPercentage": "high"})
    with caplog.at_level(logging.ERROR, logger="main"):
        result = m._validate_config(cfg)
    assert result["warnings"]["warningPercentage"] == m.DEFAULT_CONFIG["warnings"]["warningPercentage"]
    assert "warnings.warningPercentage" in caplog.text


# ── warnings ordering ────────────────────────────────────────────────────────

def test_inverted_warning_thresholds_resets_both_to_defaults(caplog):
    cfg = _merged(**{"warnings.warningPercentage": 0.95, "warnings.criticalPercentage": 0.80})
    with caplog.at_level(logging.ERROR, logger="main"):
        result = m._validate_config(cfg)
    assert result["warnings"]["warningPercentage"] == m.DEFAULT_CONFIG["warnings"]["warningPercentage"]
    assert result["warnings"]["criticalPercentage"] == m.DEFAULT_CONFIG["warnings"]["criticalPercentage"]
    assert "warningPercentage" in caplog.text


# ── poll thresholds ───────────────────────────────────────────────────────────

def test_poll_threshold_above_out_of_range_is_replaced(caplog):
    cfg = copy.deepcopy(m.DEFAULT_CONFIG)
    cfg["poll"]["thresholds"]["critical"]["above"] = 2.0
    with caplog.at_level(logging.ERROR, logger="main"):
        result = m._validate_config(cfg)
    assert result["poll"]["thresholds"]["critical"]["above"] == \
        m.DEFAULT_CONFIG["poll"]["thresholds"]["critical"]["above"]
    assert "poll.thresholds.critical.above" in caplog.text


def test_poll_threshold_interval_sec_string_is_replaced(caplog):
    cfg = copy.deepcopy(m.DEFAULT_CONFIG)
    cfg["poll"]["thresholds"]["critical"]["intervalSec"] = "fast"
    with caplog.at_level(logging.ERROR, logger="main"):
        result = m._validate_config(cfg)
    assert result["poll"]["thresholds"]["critical"]["intervalSec"] == \
        m.DEFAULT_CONFIG["poll"]["thresholds"]["critical"]["intervalSec"]
    assert "intervalSec" in caplog.text


def test_poll_threshold_interval_sec_negative_is_replaced(caplog):
    cfg = copy.deepcopy(m.DEFAULT_CONFIG)
    cfg["poll"]["thresholds"]["critical"]["intervalSec"] = -10
    with caplog.at_level(logging.ERROR, logger="main"):
        result = m._validate_config(cfg)
    assert result["poll"]["thresholds"]["critical"]["intervalSec"] == \
        m.DEFAULT_CONFIG["poll"]["thresholds"]["critical"]["intervalSec"]
    assert "intervalSec" in caplog.text


# ── post_reset ────────────────────────────────────────────────────────────────

def test_post_reset_threshold_above_1_is_replaced(caplog):
    cfg = copy.deepcopy(m.DEFAULT_CONFIG)
    cfg["suggestions"]["triggers"]["post_reset"]["weeklyPercentageBelow"] = 99
    with caplog.at_level(logging.ERROR, logger="main"):
        result = m._validate_config(cfg)
    assert result["suggestions"]["triggers"]["post_reset"]["weeklyPercentageBelow"] == \
        m.DEFAULT_CONFIG["suggestions"]["triggers"]["post_reset"]["weeklyPercentageBelow"]
    assert "post_reset.weeklyPercentageBelow" in caplog.text


# ── no error logged for valid values ──────────────────────────────────────────

def test_no_error_logged_for_default_config(caplog):
    with caplog.at_level(logging.ERROR, logger="main"):
        m._validate_config(copy.deepcopy(m.DEFAULT_CONFIG))
    assert caplog.text == ""
