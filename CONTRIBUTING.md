# Contributing to claude-lens

Thank you for your interest in improving claude-lens.

## The easiest way to contribute: add a suggestion

The primary contribution target is `sidecar/data/suggestions.yaml`. Suggestions are the smart tips surfaced by the widget when certain usage conditions are met (e.g. low utilisation near a weekly reset). Adding a well-crafted suggestion is a high-value, low-friction contribution — no Rust or Python knowledge required.

### How suggestions work

Each suggestion entry defines a title, a short description, a prompt the user can copy into Claude, and a trigger condition that controls when it appears. The schema and annotated examples are at the top of `sidecar/data/suggestions.yaml`.

### Validate before submitting

Run the validator to catch schema errors before opening a pull request:

```bash
python3 sidecar/validate_suggestions.py sidecar/data/suggestions.yaml
```

If it exits with a message like `42 entries, all valid.` you're good to go. The validator checks required fields, type constraints, and naming rules.
To validate a personal custom file at `~/.claudelens/custom_suggestions.yaml`, run it with no argument.

### Naming rules for custom suggestions

If you are adding suggestions meant for personal or local use (not for merging into the built-in set), prefix both `id` and `category` with `custom_` and place them in `~/.claudelens/custom_suggestions.yaml` instead. This keeps them out of source control and prevents ID collisions with built-in entries.

For a contribution to the built-in set, choose a descriptive ID in the form `<category><nnn>` (e.g. `testing001`, `refactor003`) and pick the most appropriate existing category, or propose a new one in your PR description.

## Running the test suites

Before submitting any code changes, make sure both suites pass:

```bash
# Python sidecar
pytest sidecar/tests/ -v

# Frontend (TypeScript / React)
npm test
```

## Code style notes

- Python: follow the conventions in the existing `sidecar/` files (type hints, docstrings, module-level `log = logging.getLogger(__name__)`).
- TypeScript/React: match the patterns in `src/` (functional components, Tailwind utility classes, no default prop mutations).
- Do not add milestone or sprint labels to source code, comments, or docstrings.

## Pull request checklist

- [ ] `python3 sidecar/validate_suggestions.py sidecar/data/suggestions.yaml` passes (if you touched `suggestions.yaml`)
- [ ] `pytest sidecar/tests/ -v` passes
- [ ] `npm test` passes
- [ ] No new files contain internal milestone labels (e.g. "Sprint N", "Phase N")
- [ ] PR description explains _what_ changed and _why_
