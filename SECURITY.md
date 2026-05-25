# Security Policy

## Supported Versions

OpenHive is currently pre-1.0. Security fixes are applied to the latest mainline release.

## Reporting a Vulnerability

Please do not open a public issue for credentials, remote execution problems, or runtime bridge vulnerabilities.

Report privately to the maintainer email listed in `pyproject.toml`, or use the repository's private vulnerability reporting feature if enabled.

Include:

- Affected version or commit
- Reproduction steps
- Impact and required permissions
- Whether any credentials, runtime tokens, or generated memory files were exposed

## Secrets and Runtime State

Do not commit:

- API keys
- OpenClaw or Hermes runtime tokens
- `.env` files
- `.openhive_memory_*.json`
- Browser/session state from local tools

OpenClaw credentials must be provided through `OPENHIVE_OPENCLAW_TOKEN` or passed directly to `OpenClawOACPAdapter(openclaw_token=...)`.
