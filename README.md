# OpenHive

OpenHive is an open-source multi-agent collaboration framework. It coordinates specialist agents, shared memory, runtime bridges, and auditable swarm decisions so teams can compose multiple AI workers instead of relying on a single assistant.

[![Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-green.svg)](pyproject.toml)

Chinese version: [README_CN.md](README_CN.md)

## What It Does

- Auto-assembles specialist teams from a user goal.
- Runs subtasks through local specialists and optional external runtimes.
- Stores shared team memory in `.openhive_memory_<team>.json` by default.
- Produces auditable `swarm_decision` records for confidence, retries, routing, and selected responders.
- Connects external workers such as OpenClaw and Hermes through the OACP hub.

## Quick Start

```bash
python -m pip install -e .
openhive init
openhive status
openhive run-auto --goal "Create a short electric vehicle market brief"
openhive memory-list --type-filter swarm_decision
openhive swarm-audit --risk high --max-confidence 0.8
```

No API key is required for the first run. If no LLM key is configured, OpenHive uses a mock LLM client so the local workflow can be verified.

For real MiniMax calls, either set `llm.api_key` in `openhive.yaml` or export:

```bash
export MINIMAX_API_KEY="your-api-key"
```

## Installation

```bash
git clone <repo-url>
cd openhive
python -m pip install -e .
```

For development:

```bash
python -m pip install -e ".[dev]"
```

## Core Commands

| Command | Purpose |
| --- | --- |
| `openhive init` | Create `openhive.yaml` |
| `openhive status` | Validate team configuration |
| `openhive run --goal "..."` | Run a goal with configured agents |
| `openhive run-auto --goal "..."` | Auto-assemble specialists and execute |
| `openhive discuss --question "..."` | Run a multi-agent discussion |
| `openhive hub --host 0.0.0.0 --port 9090` | Start the OACP hub |
| `openhive memory-list --type-filter swarm_decision` | Inspect stored decisions |
| `openhive swarm-audit --risk high --max-confidence 0.8` | Review swarm quality and alerts |

## Runtime Bridge

OpenHive can add external runtimes into `run-auto` decisions through OACP.

1. Start the hub:

```bash
openhive hub --host 0.0.0.0 --port 9090
```

2. Enable runtime bridge in `openhive.yaml`:

```yaml
enterprise:
  runtime_bridge:
    enabled: true
    hub_url: ws://localhost:9090/ws
    connect_timeout_seconds: 10
    request_timeout_seconds: 120
    runtimes:
      - openclaw
      - hermes
```

3. Start or connect runtimes:

```bash
python -m openhive.runtime.start_club
```

For a real OpenClaw gateway, do not hard-code credentials. Set:

```bash
export OPENHIVE_OPENCLAW_TOKEN="your-openclaw-token"
```

For Hermes, the adapter expects the bridge socket at `/tmp/hermes-agent-bridge.sock` by default.

## Configuration

The default config is `openhive.yaml`.

Important sections:

- `agents`: local orchestrator and specialist definitions.
- `enterprise.policy`: parallelism, redundancy, risk threshold, confidence threshold, retry settings, and audit behavior.
- `enterprise.runtime_bridge`: optional OACP runtime integration.
- `llm`: provider, base URL, model, max tokens, and temperature.
- `redis` / `database`: optional production backends. Local JSON memory is used by default.

## Project Structure

```text
src/openhive/
  agent/          Orchestrator and specialist agents
  cli/            Typer CLI commands
  core/           Team, task, memory, queue, config, and swarm policies
  integrations/   LLM client and provider failover
  runtime/        OACP hub, server, clients, and adapters
  skills/         Skill contracts and registry
  tools/          Tool descriptors and registry
tests/
  unit/           Fast unit tests
  integration/    Integration test package placeholder
docs/
  OACP.md
  enterprise-swarm.md
```

## Development Checks

Run these before publishing or opening a pull request:

```bash
python3 -m compileall -q src tests
python3 -m unittest discover -s tests/unit -p 'test_*.py'
openhive --help
```

If `ruff` is installed through `.[dev]`, also run:

```bash
ruff check src tests
```

## Publishing Notes

- Replace `<repo-url>` with the real repository URL before publishing examples.
- Do not commit `.openhive_memory_*.json`, `.env`, API keys, runtime tokens, or local browser/session artifacts.
- Keep English documentation as the primary public surface. Chinese docs can live beside it as `*_CN.md`.
- Include `swarm-audit` output or screenshots in release notes when changing routing or arbitration behavior.

## Security

See [SECURITY.md](SECURITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Chinese version: [CONTRIBUTING_CN.md](CONTRIBUTING_CN.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
