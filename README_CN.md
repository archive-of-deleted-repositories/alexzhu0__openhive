# OpenHive 中文说明

OpenHive 是一个开源多智能体协作框架，用于把多个专家型 AI worker 组合成可编排、可审计、可扩展的团队。

英文主文档见：[README.md](README.md)。

## 快速开始

```bash
python -m pip install -e .
openhive init
openhive status
openhive run-auto --goal "帮我输出电动车市场趋势简报"
openhive memory-list --type-filter swarm_decision
openhive swarm-audit --risk high --max-confidence 0.8
```

默认无需 API Key。未配置真实 LLM 时，会使用 mock 模式帮助你跑通本地链路。

如需真实 MiniMax 推理：

```bash
export MINIMAX_API_KEY="your-api-key"
```

也可以直接写入 `openhive.yaml` 的 `llm.api_key`。

## 核心能力

- 根据目标自动组建专家团队。
- 将任务拆给本地 specialist 或外部 runtime。
- 使用共享记忆文件 `.openhive_memory_<team>.json` 保存团队结果。
- 通过 `swarm_decision` 记录仲裁、信心分、重试、路由等审计信息。
- 通过 OACP Hub 接入 OpenClaw、Hermes 等外部智能体员工。

## 外部 Runtime 接入

启动 Hub：

```bash
openhive hub --host 0.0.0.0 --port 9090
```

在 `openhive.yaml` 中打开：

```yaml
enterprise:
  runtime_bridge:
    enabled: true
    hub_url: ws://localhost:9090/ws
    runtimes:
      - openclaw
      - hermes
```

OpenClaw token 不要写进代码。使用环境变量：

```bash
export OPENHIVE_OPENCLAW_TOKEN="your-openclaw-token"
```

Hermes 默认使用 `/tmp/hermes-agent-bridge.sock`。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `openhive init` | 创建配置 |
| `openhive status` | 查看团队状态 |
| `openhive run --goal "..."` | 使用配置团队执行目标 |
| `openhive run-auto --goal "..."` | 自动组队执行目标 |
| `openhive hub` | 启动 OACP Hub |
| `openhive memory-list` | 查看团队记忆 |
| `openhive swarm-audit` | 查看蜂群审计 |

## 发布前检查

```bash
python3 -m compileall -q src tests
python3 -m unittest discover -s tests/unit -p 'test_*.py'
openhive --help
```

不要提交 `.openhive_memory_*.json`、`.env`、API Key 或 runtime token。
