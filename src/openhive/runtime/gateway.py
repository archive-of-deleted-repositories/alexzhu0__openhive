"""Multi-Runtime Gateway - 多运行时网关

允许 OpenHive 作为「元框架」协调多个外部运行时：
- OpenClaw Runtime
- Hermes Runtime
- OpenHuman Runtime

架构：
┌─────────────────────────────────────────────────────────────┐
│                     OpenHive Gateway                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │ OpenClaw   │  │  Hermes     │  │ OpenHuman   │       │
│  │ Adapter    │  │  Adapter    │  │ Adapter     │       │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘       │
│         │                 │                 │               │
│  ┌──────┴────────────────┴─────────────────┴──────┐       │
│  │              Runtime Registry                    │       │
│  │  - 能力清单注册                                 │       │
│  │  - 状态管理                                     │       │
│  │  - 流量调度                                     │       │
│  └────────────────────────────────────────────────┘       │
│  ┌────────────────────────────────────────────────┐       │
│  │            Unified Message Bus                   │       │
│  │  - 跨运行时消息路由                             │       │
│  │  - 协议转换                                     │       │
│  └────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class RuntimeKind(Enum):
    """运行时类型"""

    OPENCLAW = "openclaw"
    HERMES = "hermes"
    OPENHUMAN = "openhuman"
    OPENHIVE = "openhive"
    CUSTOM = "custom"


class RuntimeStatus(Enum):
    """运行时状态"""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    BUSY = "busy"
    ERROR = "error"


@dataclass
class AgentCapability:
    """Agent 能力"""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    runtime: RuntimeKind = RuntimeKind.CUSTOM
    runtime_agent_id: str = ""  # 在原运行时中的 ID


@dataclass
class RuntimeInfo:
    """运行时信息"""

    id: UUID
    kind: RuntimeKind
    name: str
    status: RuntimeStatus
    agents: list[AgentCapability] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class RuntimeAdapter(ABC):
    """运行时适配器基类

    每个外部运行时需要实现一个 Adapter：
    - 协议转换
    - 消息路由
    - 状态同步
    """

    @property
    @abstractmethod
    def kind(self) -> RuntimeKind:
        """运行时类型"""
        pass

    @abstractmethod
    async def connect(self) -> None:
        """连接运行时"""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        pass

    @abstractmethod
    async def list_agents(self) -> list[AgentCapability]:
        """列出所有 Agent 能力"""
        pass

    @abstractmethod
    async def send_message(
        self,
        agent_id: str,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        """发送消息给 Agent"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        pass


class OpenClawAdapter(RuntimeAdapter):
    """OpenClaw 运行时适配器

    集成 OpenClaw 的：
    - pi-embedded-runner
    - ToolDescriptor 系统
    - Channel 端口/适配器模式
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8080,
        api_key: str = "",
    ):
        self._host = host
        self._port = port
        self._api_key = api_key
        self._connected = False

    @property
    def kind(self) -> RuntimeKind:
        return RuntimeKind.OPENCLAW

    async def connect(self) -> None:
        # 连接 OpenClaw Runtime API
        self._connected = True
        pass

    async def disconnect(self) -> None:
        self._connected = False

    async def list_agents(self) -> list[AgentCapability]:
        # 从 OpenClaw Runtime 获取 Agent 列表
        return [
            AgentCapability(
                name="openclaw.researcher",
                description="OpenClaw 研究 Agent",
                runtime=RuntimeKind.OPENCLAW,
                runtime_agent_id="researcher-001",
            ),
            AgentCapability(
                name="openclaw.analyst",
                description="OpenClaw 分析 Agent",
                runtime=RuntimeKind.OPENCLAW,
                runtime_agent_id="analyst-001",
            ),
        ]

    async def send_message(
        self,
        agent_id: str,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        # 通过 OpenClaw API 发送消息
        return {"status": "ok", "result": f"OpenClaw response to {agent_id}"}

    async def health_check(self) -> bool:
        return self._connected


class HermesAdapter(RuntimeAdapter):
    """Hermes 运行时适配器

    集成 Hermes 的：
    - Skill constraints (零容忍)
    - Fitness scoring
    - GEPA 进化系统
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8081,
        api_key: str = "",
    ):
        self._host = host
        self._port = port
        self._api_key = api_key
        self._connected = False

    @property
    def kind(self) -> RuntimeKind:
        return RuntimeKind.HERMES

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def list_agents(self) -> list[AgentCapability]:
        return [
            AgentCapability(
                name="hermes.evolver",
                description="Hermes 进化 Agent",
                runtime=RuntimeKind.HERMES,
                runtime_agent_id="evolver-001",
            ),
        ]

    async def send_message(
        self,
        agent_id: str,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        return {"status": "ok", "result": f"Hermes response to {agent_id}"}

    async def health_check(self) -> bool:
        return self._connected


class OpenHumanAdapter(RuntimeAdapter):
    """OpenHuman 运行时适配器"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8082,
        api_key: str = "",
    ):
        self._host = host
        self._port = port
        self._api_key = api_key
        self._connected = False

    @property
    def kind(self) -> RuntimeKind:
        return RuntimeKind.OPENHUMAN

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def list_agents(self) -> list[AgentCapability]:
        return []

    async def send_message(
        self,
        agent_id: str,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        return {"status": "ok", "result": f"OpenHuman response to {agent_id}"}

    async def health_check(self) -> bool:
        return self._connected


class MultiRuntimeGateway:
    """多运行时网关

    统一管理多个运行时：
    - 注册/注销运行时
    - 能力发现
    - 消息路由
    - 负载均衡
    """

    def __init__(self):
        self._runtimes: dict[UUID, tuple[RuntimeInfo, RuntimeAdapter]] = {}
        self._lock = asyncio.Lock()

    async def register_runtime(
        self,
        adapter: RuntimeAdapter,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> UUID:
        """注册一个运行时"""
        async with self._lock:
            runtime_id = uuid4()

            info = RuntimeInfo(
                id=runtime_id,
                kind=adapter.kind,
                name=name,
                status=RuntimeStatus.DISCONNECTED,
                metadata=metadata or {},
            )

            self._runtimes[runtime_id] = (info, adapter)
            return runtime_id

    async def connect_runtime(self, runtime_id: UUID) -> bool:
        """连接运行时"""
        async with self._lock:
            if runtime_id not in self._runtimes:
                return False

            info, adapter = self._runtimes[runtime_id]
            try:
                await adapter.connect()
                info.status = RuntimeStatus.CONNECTED
                info.agents = await adapter.list_agents()
                return True
            except Exception:
                info.status = RuntimeStatus.ERROR
                return False

    async def disconnect_runtime(self, runtime_id: UUID) -> bool:
        """断开运行时"""
        async with self._lock:
            if runtime_id not in self._runtimes:
                return False

            info, adapter = self._runtimes[runtime_id]
            await adapter.disconnect()
            info.status = RuntimeStatus.DISCONNECTED
            return True

    async def list_runtimes(self) -> list[RuntimeInfo]:
        """列出所有已注册运行时"""
        return [info for info, _ in self._runtimes.values()]

    async def list_all_agents(self) -> list[AgentCapability]:
        """列出所有 Agent 能力"""
        agents = []
        for info, adapter in self._runtimes.values():
            if info.status == RuntimeStatus.CONNECTED:
                agents.extend(info.agents)
        return agents

    async def find_agents_by_capability(
        self,
        capability_name: str,
    ) -> list[AgentCapability]:
        """按能力名称查找 Agent"""
        all_agents = await self.list_all_agents()
        return [
            agent
            for agent in all_agents
            if capability_name.lower() in agent.name.lower()
        ]

    async def route_message(
        self,
        agent_id: str,
        runtime_kind: RuntimeKind,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        """路由消息到指定运行时"""
        for info, adapter in self._runtimes.values():
            if info.kind == runtime_kind and info.status == RuntimeStatus.CONNECTED:
                return await adapter.send_message(agent_id, message)

        raise RuntimeError(f"No connected runtime for {runtime_kind}")

    async def broadcast_to_all(
        self,
        message: dict[str, Any],
    ) -> dict[RuntimeKind, dict[str, Any]]:
        """广播消息到所有运行时"""
        results = {}
        for info, adapter in self._runtimes.values():
            if info.status == RuntimeStatus.CONNECTED:
                try:
                    # 发送到该运行时所有 Agent
                    for agent in info.agents:
                        result = await adapter.send_message(agent.runtime_agent_id, message)
                        results[info.kind] = result
                except Exception as e:
                    results[info.kind] = {"error": str(e)}
        return results

    async def health_check_all(self) -> dict[UUID, bool]:
        """健康检查所有运行时"""
        results = {}
        for runtime_id, (info, adapter) in self._runtimes.items():
            try:
                is_healthy = await adapter.health_check()
                results[runtime_id] = is_healthy
                if is_healthy and info.status != RuntimeStatus.CONNECTED:
                    info.status = RuntimeStatus.CONNECTED
                elif not is_healthy and info.status == RuntimeStatus.CONNECTED:
                    info.status = RuntimeStatus.DISCONNECTED
            except Exception:
                results[runtime_id] = False
                info.status = RuntimeStatus.ERROR
        return results


# 全局网关实例
_global_gateway: MultiRuntimeGateway | None = None


def get_gateway() -> MultiRuntimeGateway:
    """获取全局网关"""
    global _global_gateway
    if _global_gateway is None:
        _global_gateway = MultiRuntimeGateway()
    return _global_gateway
