# Open Agent Collaboration Protocol (OACP)

OACP is the lightweight protocol OpenHive uses to connect external runtimes such as OpenClaw, Hermes, and future human-in-the-loop runtimes.

## Purpose

Without a common protocol, each runtime only knows its own tools, memory, and execution model. OACP provides:

- runtime registration
- capability declaration
- task dispatch
- result return
- multi-agent collaboration messages

## Runtime Topology

```text
OpenHive run-auto
  -> OACP client
  -> OACP Hub (ws://localhost:9090/ws)
  -> external runtimes
     - openclaw
     - hermes
     - openhuman
```

## Default Endpoints

| Component | Default |
| --- | --- |
| OpenHive Hub HTTP | `http://localhost:9090` |
| OpenHive Hub WebSocket | `ws://localhost:9090/ws` |
| OpenClaw gateway | `ws://localhost:18789` |
| Hermes bridge | `/tmp/hermes-agent-bridge.sock` |

## Message Types

### REGISTER

```json
{
  "protocol": "OACP",
  "version": "1.0",
  "type": "REGISTER",
  "runtime_kind": "openclaw",
  "runtime_name": "OpenClaw Technical Agent",
  "capabilities": {
    "tool_execution": {"enabled": true, "tools": ["bash", "web_search"]},
    "subagent_spawn": {"enabled": true, "max_depth": 3},
    "specialists": ["research", "analysis", "technical"]
  }
}
```

### REGISTER_ACK

```json
{
  "protocol": "OACP",
  "version": "1.0",
  "type": "REGISTER_ACK",
  "runtime_id": "openclaw@d242584903c5",
  "online_runtimes": 1
}
```

### TASK_DISPATCH

```json
{
  "protocol": "OACP",
  "version": "1.0",
  "type": "TASK_DISPATCH",
  "task_id": "task-123",
  "required_capabilities": ["research", "data_analysis"],
  "payload": {
    "description": "Analyze the target market",
    "risk_level": "high"
  }
}
```

### RESULT_RETURN

```json
{
  "protocol": "OACP",
  "version": "1.0",
  "type": "RESULT_RETURN",
  "from": "hermes@abc123",
  "task_id": "task-123",
  "status": "success",
  "result": {
    "summary": "Analysis complete",
    "findings": ["..."]
  }
}
```

## Quick Start

Start the hub:

```bash
openhive hub --host 0.0.0.0 --port 9090
```

Check status:

```bash
curl http://localhost:9090/api/status
```

Start built-in demo clients:

```bash
python -m openhive.runtime.start_club
```

## Security

Runtime tokens must not be committed. OpenClaw credentials should be provided through:

```bash
export OPENHIVE_OPENCLAW_TOKEN="your-openclaw-token"
```

See [../SECURITY.md](../SECURITY.md).
