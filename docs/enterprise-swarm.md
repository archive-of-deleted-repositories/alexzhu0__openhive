# Enterprise Swarm Design

This document describes the governance layer behind `openhive run-auto`.

## Goals

OpenHive turns a single-agent workflow into an auditable enterprise swarm:

1. Route low-risk and high-risk work differently.
2. Select local and external responders by capability.
3. Record arbitration decisions for later review.
4. Surface retry, confidence, and routing data through CLI audit commands.

## Control Plane

Enterprise settings live under `openhive.yaml -> enterprise -> policy`.

| Field | Purpose |
| --- | --- |
| `parallelism` | Maximum responders per subtask |
| `redundancy` | Extra responders for high-risk work |
| `candidate_count` | Base number of candidates produced by `TeamAssembler` |
| `high_risk_threshold` | Risk level that enables high-risk behavior (`high` or `critical`) |
| `min_result_chars` | Minimum output length before scoring |
| `winner_confidence_threshold` | Arbitration confidence threshold |
| `max_retry_rounds` | Maximum retry rounds for low-confidence high-risk work |
| `retry_on_low_confidence` | Enables/disables low-confidence retries |
| `audit_enabled` | Writes `swarm_decision` records into memory |

## Execution Plane

1. `TeamAssembler` creates subtasks and candidate specialists.
2. `OrchestratorAgent` selects responders from the policy.
3. Local specialists run directly.
4. External runtimes are filtered through `select_external_runtimes(...)`.
5. Responses are scored, deduplicated, and arbitrated.
6. The chosen result and audit metadata are written as `swarm_decision`.

## External Runtime Routing

External runtimes such as `openclaw`, `hermes`, and `openhuman` can join the candidate pool when `enterprise.runtime_bridge.enabled` is true.

Routing uses:

- task `required_capabilities`
- assigned specialist name
- task risk level

For high-risk tasks, OpenHive keeps external responders as a fallback when capability routing has no exact match. For lower-risk tasks, non-matching external responders can be removed before execution.

## Audit Records

Each `swarm_decision` includes:

- `chosen`
- `winner_confidence`
- `attempts`
- `retry_reason`
- `risk_level`
- `routing_notes`

Inspect raw memory:

```bash
openhive memory-list --type-filter swarm_decision
```

Aggregate decisions:

```bash
openhive swarm-audit --risk high --max-confidence 0.8
```
