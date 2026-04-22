"""
validate_suggestions.py — stub for M6.

Validates the bundled suggestions.yaml against the loader schema and exits
non-zero if any entries are invalid or skipped. Run locally before opening a PR
that adds or edits suggestions.

TODO (M6): implement validation logic using suggestions_loader.load_suggestions.
"""

if __name__ == "__main__":
    raise NotImplementedError(
        "validate_suggestions.py is not yet implemented. "
        "Run: python -m pytest tests/test_suggestions.py::TestSuggestionsLoader::test_loads_bundled_yaml -v"
    )
