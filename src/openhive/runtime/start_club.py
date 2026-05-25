#!/usr/bin/env python3
"""AI Agent Club 启动器

同时启动 Hub 和多个 Runtime 客户端
"""

import asyncio
import sys
from pathlib import Path

# 添加 src 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def main():
    from openhive.runtime.server import HubServer
    from openhive.runtime.oacp_client import OACPClient, OACPCapabilities

    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   🌐 AI Agent Club 启动器                                  ║
║                                                              ║
║   启动 Hub + OpenClaw + Hermes + OpenHuman 客户端         ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)

    # 启动 Hub
    print("📡 启动 OACP Hub...")
    hub = HubServer(host="0.0.0.0", port=9090)
    await hub.start()

    # 等待 Hub 启动
    await asyncio.sleep(1)

    # 启动 OpenClaw 客户端
    print("\n🔴 启动 OpenClaw 客户端...")
    openclaw_caps = OACPCapabilities(
        tool_execution=True,
        tools=["web_search", "bash", "read_file", "write_file"],
        subagent_spawn=True,
        max_subagent_depth=3,
        channel_protocol=True,
        specialists=["research", "analysis", "technical"],
    )
    openclaw = OACPClient(
        runtime_kind="openclaw",
        runtime_name="OpenClaw Technical Agent",
        hub_url="ws://localhost:9090/ws",
        capabilities=openclaw_caps,
    )
    await openclaw.connect()

    # 启动 Hermes 客户端
    print("\n🟡 启动 Hermes 客户端...")
    hermes_caps = OACPCapabilities(
        capability_assessment=True,
        fitness_scoring=True,
        skill_evolution=True,
        gepa_enabled=True,
        constraint_validation=True,
        specialists=["analysis", "research", "strategy", "governance"],
    )
    hermes = OACPClient(
        runtime_kind="hermes",
        runtime_name="Hermes Evolution Agent",
        hub_url="ws://localhost:9090/ws",
        capabilities=hermes_caps,
    )
    await hermes.connect()

    # 启动 OpenHuman 客户端
    print("\n🟢 启动 OpenHuman 客户端...")
    openhuman_caps = OACPCapabilities(
        human_feedback=True,
        ux_analysis=True,
        user_proxy=True,
        specialists=["user_feedback", "experience"],
    )
    openhuman = OACPClient(
        runtime_kind="openhuman",
        runtime_name="OpenHuman Experience Agent",
        hub_url="ws://localhost:9090/ws",
        capabilities=openhuman_caps,
    )
    await openhuman.connect()

    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   ✅ AI Agent Club 启动完成！                               ║
║                                                              ║
║   🌐 Hub:    ws://localhost:9090                           ║
║   🔴 OpenClaw:  已连接                                      ║
║   🟡 Hermes:    已连接                                      ║
║   🟢 OpenHuman: 已连接                                      ║
║                                                              ║
║   访问 http://localhost:9090 查看 Web UI                    ║
║                                                              ║
║   按 Ctrl+C 停止                                            ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)

    # 保持运行
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\n正在关闭...")
        await openclaw.disconnect()
        await hermes.disconnect()
        await openhuman.disconnect()
        await hub.stop()


if __name__ == "__main__":
    asyncio.run(main())
