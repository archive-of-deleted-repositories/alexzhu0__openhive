# Repository Guidelines

## Project Structure & Module Organization

OpenHive uses a `src` layout.

- `src/openhive/core/`: shared models and services (`team`, `task`, `memory`, `config`, `swarm`, `queue`).
- `src/openhive/agent/`: `OrchestratorAgent` and specialist implementations.
- `src/openhive/runtime/` + `runtime/adapters/`: OACP hub, gateway, and adapters.
- `src/openhive/integrations/`: LLM/provider wrappers.
- `src/openhive/skills/` and `src/openhive/tools/`: contracts and registries.
- `src/openhive/cli/`: Typer CLI (`init`, `status`, `run`, `run-auto`, `hub`, `discuss`, `memory-list`, `swarm-audit`).
- `tests/unit/` for fast tests, `tests/integration/` for runtime integration checks.
- `openhive.yaml` is the sample config; `.openhive_memory_*.json` are generated runtime artifacts.

## Build, Test, and Development Commands

- `python -m pip install -e ".[dev]"`: install dev toolchain.
- `openhive init --config-path openhive.yaml`: create sample config.
- `openhive status --config-path openhive.yaml`: validate configuration and components.
- `openhive run --goal "..." --config-path openhive.yaml`: execute with configured team.
- `openhive run-auto --goal "..." --config-path openhive.yaml`: auto-assemble team from goal.
- `openhive hub --host 0.0.0.0 --port 9090`: start OACP hub + web UI.
- `pytest` or `python -m unittest discover -s tests/unit -p 'test_*.py'`: run tests.

## Coding Style & Naming Conventions

- Target Python 3.10+; 4-space indentation.
- Keep types on public interfaces; prefer explicit imports.
- `snake_case` for functions/variables/modules/files; `PascalCase` for classes/enums.
- Prefer short, readable Chinese/English messages in logs and comments.
- Formatting/linting: `ruff` (line length 100, Python 3.12 compatibility).

## Testing Guidelines

- Naming: `test_<feature>.py`, test funcs as `test_<scenario>()`.
- Prefer tests for success/error/timeout/fallback branches when changing dispatch, memory, or orchestration logic.
- Use scoped runs:
  - `pytest tests/unit/test_runtime_bridge.py`
  - `pytest tests/unit/test_config.py`
  - `python -m unittest discover -s tests/unit -p 'test_*.py'`

## Commit & Pull Request Guidelines

- Use concise, imperative commit messages (e.g. `feat: add runtime bridge fallback test`).
- Keep commits single-purpose.
- PRs should include summary, rationale, config impact, and test command outputs.
- Attach logs/screenshots when changing hub UI or CLI output.

## Security & Configuration Notes

- Do not commit API keys, session credentials, or generated memory files.
- Put secrets in environment variables.
- For new external runtime adapters, mirror `runtime/adapters/` conventions and keep local fallback behavior tested.
