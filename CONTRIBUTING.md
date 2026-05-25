# Contributing to OpenHive

Thanks for contributing to OpenHive. Please follow this process so the public repository stays stable and review-friendly.

## 1. Development setup

```bash
python -m pip install -e ".[dev]"
```

Requirements:

- Python 3.10+
- `openhive` command available (`python3 -m pip install -e .`)
- No real API keys, `.openhive_memory_*.json`, or local temporary artifacts committed

## 2. Code standards

- Use 4-space indentation and existing project style.
- Prefer explicit type annotations and clear naming.
- Keep complex logic readable and add comments where intent is non-obvious.
- Formatting/linting: `ruff` (configured in `pyproject.toml`).
- Prefer minimal, reviewable diffs.

## 3. Commit convention

- Use imperative prefixes (`feat:` / `fix:` / `refactor:` / `test:`).
- Keep PRs focused on one goal.
- Example commit messages:
  - `feat: add runtime bridge routing test`
  - `fix: guard low-confidence retry fallback`
  - `test: add enterprise audit unit cases`

## 4. Required checks

```bash
python3 -m compileall -q src tests
python3 -m unittest discover -s tests/unit -p 'test_*.py'
openhive --help
```

If you change runtime behavior, add/update tests and include command output in the PR description.

## 5. Pull request checklist

Each PR should include:

- Scope and impact (1–3 lines)
- Main changed files
- New/changed config items (if any)
- Regression risk assessment (`low`/`medium`/`high`)
- Commands and outputs for verification

## 6. Change discussion and compatibility

- Reproduce and explain the issue first in Issue when possible, then open PR.
- If breaking, mark PR title/body with `BREAKING CHANGE`.
- For `openclaw` / `hermes` runtime changes, validate `enterprise.runtime_bridge` docs and behavior together.

## Chinese Version

See [CONTRIBUTING_CN.md](CONTRIBUTING_CN.md).
