"""OACP Client - 连接到 OACP Hub 的客户端

让 OpenClaw、Hermes、OpenHuman 能够连接到 AI Agent Club Hub
"""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from enum import Enum


class MessageType(str, Enum):
    """OACP 消息类型"""
    REGISTER = "REGISTER"
    REGISTER_ACK = "REGISTER_ACK"
    CAPABILITY_ANNOUNCE = "CAPABILITY_ANNOUNCE"
    COLLABORATION_REQUEST = "COLLABORATION_REQUEST"
    COLLABORATION_RESPONSE = "COLLABORATION_RESPONSE"
    COLLABORATION_RESULT = "COLLABORATION_RESULT"
    TASK_DISPATCH = "TASK_DISPATCH"
    RESULT_RETURN = "RESULT_RETURN"
    ERROR = "ERROR"
    HEARTBEAT = "HEARTBEAT"
    HEARTBEAT_ACK = "HEARTBEAT_ACK"


@dataclass
class OACPCapabilities:
    """OACP 能力声明"""
    # OpenClaw 能力
    tool_execution: bool = False
    tools: list[str] = field(default_factory=list)
    subagent_spawn: bool = False
    max_subagent_depth: int = 0
    channel_protocol: bool = False

    # Hermes 能力
    capability_assessment: bool = False
    fitness_scoring: bool = False
    skill_evolution: bool = False
    gepa_enabled: bool = False
    constraint_validation: bool = False

    # OpenHuman 能力
    human_feedback: bool = False
    ux_analysis: bool = False
    user_proxy: bool = False
    specialists: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_execution": {"enabled": self.tool_execution, "tools": self.tools},
            "subagent_spawn": {"enabled": self.subagent_spawn, "max_depth": self.max_subagent_depth},
            "channel_protocol": {"enabled": self.channel_protocol},
            "capability_assessment": {"enabled": self.capability_assessment},
            "fitness_scoring": {"enabled": self.fitness_scoring},
            "skill_evolution": {"enabled": self.skill_evolution, "gepa_enabled": self.gepa_enabled},
            "constraint_validation": {"enabled": self.constraint_validation},
            "human_feedback": {"enabled": self.human_feedback},
            "ux_analysis": {"enabled": self.ux_analysis},
            "user_proxy": {"enabled": self.user_proxy},
            "specialists": self.specialists,
        }


class OACPClient:
    """OACP 客户端

    连接到 Hub 并进行通信
    """

    def __init__(
        self,
        runtime_kind: str,  # "openclaw", "hermes", "openhuman"
        runtime_name: str,
        hub_url: str = "ws://localhost:9090",
        capabilities: OACPCapabilities | None = None,
        connect_timeout_seconds: float = 10.0,
    ):
        self.runtime_kind = runtime_kind
        self.runtime_name = runtime_name
        self.hub_url = hub_url
        self.capabilities = capabilities or OACPCapabilities()
        self.connect_timeout_seconds = connect_timeout_seconds
        self._websocket = None
        self._runtime_id = None
        self._connected = False
        self._handlers: dict[str, Callable] = {}
        self._session_id = None
        self._pending_requests: dict[str, asyncio.Future] = {}

    async def connect(self) -> bool:
        """连接到 Hub"""
        import websockets

        try:
            self._websocket = await websockets.connect(
                self.hub_url,
                open_timeout=self.connect_timeout_seconds,
            )
            self._connected = True

            # 注册自己
            await self._send_register()

            # 启动心跳
            asyncio.create_task(self._heartbeat_loop())

            # 启动消息接收循环
            asyncio.create_task(self._receive_loop())

            print(f"✅ 已连接到 OACP Hub: {self.hub_url}")
            print(f"   Runtime: {self.runtime_name} ({self.runtime_kind})")
            return True

        except Exception as e:
            print(f"❌ 连接失败: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """断开连接"""
        if self._websocket:
            await self._websocket.close()
        self._connected = False

    async def _send_register(self) -> None:
        """发送注册消息"""
        await self._send({
            "protocol": "OACP",
            "version": "1.0",
            "type": "REGISTER",
            "runtime_kind": self.runtime_kind,
            "runtime_name": self.runtime_name,
            "capabilities": self.capabilities.to_dict(),
        })

    async def _send(self, message: dict) -> None:
        """发送消息"""
        if self._websocket:
            await self._websocket.send(json.dumps(message, ensure_ascii=False))

    async def _receive_loop(self) -> None:
        """接收消息循环"""
        try:
            async for message in self._websocket:
                await self._handle_message(message)
        except Exception as e:
            print(f"接收消息错误: {e}")
            self._connected = False

    async def _handle_message(self, message: str) -> None:
        """处理接收到的消息"""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")

            # 特殊处理
            if msg_type == "REGISTER_ACK":
                self._runtime_id = data.get("runtime_id")
                self._session_id = data.get("session_id")
                print(f"   Runtime ID: {self._runtime_id}")
                print(f"   在线 Runtime 数: {data.get('online_runtimes', 0)}")
                return

            if msg_type == "COLLABORATION_REQUEST":
                await self._handle_collaboration_request(data)
                return

            if msg_type == "TASK_DISPATCH":
                await self._handle_task_dispatch(data)
                return

            if msg_type == "RESULT_RETURN":
                await self._handle_result_return(data)
                return

            # 调用注册的处理器
            if msg_type in self._handlers:
                await self._handlers[msg_type](data)

        except Exception as e:
            print(f"处理消息错误: {e}")

    async def _handle_collaboration_request(self, data: dict) -> None:
        """处理协作讨论请求"""
        session_id = data.get("session_id", "")
        question = data.get("question", "")
        perspective = data.get("perspective", "")
        turn = data.get("turn", 1)

        print(f"\n📋 收到协作讨论请求")
        print(f"   会话: {session_id}")
        print(f"   问题: {question[:50]}...")
        print(f"   视角: {perspective} (第 {turn} 轮)")

        # 根据视角生成回复
        if self.runtime_kind == "openclaw":
            response = await self._openclaw_analyze(question, perspective)
        elif self.runtime_kind == "hermes":
            response = await self._hermes_analyze(question, perspective)
        else:
            response = await self._openhuman_analyze(question, perspective)

        # 发送响应
        await self._send({
            "protocol": "OACP",
            "version": "1.0",
            "type": "COLLABORATION_RESPONSE",
            "from": self._runtime_id,
            "session_id": session_id,
            "perspective": perspective,
            "turn": turn,
            "content": response,
        })

        print(f"✅ 已发送 {perspective} 视角回复")

    async def _handle_task_dispatch(self, data: dict) -> None:
        """处理任务分发"""
        task_id = data.get("task_id", "")
        payload = data.get("payload", {})

        print(f"\n📦 收到任务分发")
        print(f"   Task ID: {task_id}")
        print(f"   目标: {payload.get('goal', 'N/A')}")

        # 执行任务（这里需要根据实际情况实现）
        result = {
            "summary": f"[{self.runtime_kind}] 任务完成",
            "findings": ["placeholder"],
        }

        # 发送结果
        await self._send({
            "protocol": "OACP",
            "version": "1.0",
            "type": "RESULT_RETURN",
            "from": self._runtime_id,
            "task_id": task_id,
            "status": "success",
            "result": result,
        })

    async def _handle_result_return(self, data: dict) -> None:
        """处理任务返回"""
        task_id = data.get("task_id", "")
        if not task_id:
            return

        future = self._pending_requests.get(task_id)
        if not future or future.done():
            return
        future.set_result(data)

    async def dispatch_task(
        self,
        task_id: str,
        payload: dict[str, Any] | None = None,
        required_capabilities: list[str] | None = None,
        timeout_seconds: float = 60.0,
    ) -> dict[str, Any]:
        """向 Hub 派发任务并等待结果"""
        if not self.is_connected:
            return {
                "task_id": task_id,
                "status": "error",
                "error": "OACP client not connected",
            }

        required_capabilities = required_capabilities or []
        payload = payload or {}

        pending = asyncio.get_event_loop().create_future()
        self._pending_requests[task_id] = pending

        await self._send({
            "protocol": "OACP",
            "version": "1.0",
            "type": "TASK_DISPATCH",
            "from": self._runtime_id,
            "task_id": task_id,
            "required_capabilities": required_capabilities,
            "payload": payload,
        })

        try:
            result = await asyncio.wait_for(pending, timeout=timeout_seconds)
            if not isinstance(result, dict):
                return {
                    "task_id": task_id,
                    "status": "error",
                    "error": "invalid result payload from hub",
                }

            normalized = dict(result)
            normalized.setdefault("task_id", task_id)

            message_type = str(normalized.get("type", "")).upper()
            status = str(normalized.get("status", "")).lower()

            if message_type == MessageType.ERROR.value or status in {"error", "failed", "failure"}:
                error_payload = normalized.get("error")
                if isinstance(error_payload, dict):
                    error_message = str(
                        error_payload.get("message")
                        or error_payload.get("detail")
                        or error_payload
                    )
                else:
                    error_message = str(error_payload or "task dispatch failed")
                normalized["status"] = "error"
                normalized["error"] = error_message
                return normalized
            if status == "timeout":
                normalized.setdefault("error", "task result timeout")
                normalized["status"] = "timeout"

            normalized.setdefault("status", "success")
            return normalized
        except asyncio.TimeoutError:
            return {
                "task_id": task_id,
                "status": "timeout",
                "error": f"task result timeout after {timeout_seconds}s",
            }
        finally:
            self._pending_requests.pop(task_id, None)

    async def _openclaw_analyze(self, question: str, perspective: str) -> dict:
        """OpenClaw 分析"""
        return {
            "viewpoint": f"[技术架构视角] 从系统设计角度分析：{question[:30]}... "
                         f"这个框架采用了模块化架构，具有良好的扩展性。",
            "key_points": [
                "模块化设计降低耦合度",
                "工具链标准化接口",
                "支持子 Agent 嵌套调用",
            ],
            "concerns": [
                "学习曲线较陡",
                "依赖管理复杂度",
            ],
        }

    async def _hermes_analyze(self, question: str, perspective: str) -> dict:
        """Hermes 分析"""
        return {
            "viewpoint": f"[技能进化视角] 从能力提升角度分析：{question[:30]}... "
                         f"框架支持动态能力扩展和自我优化。",
            "key_points": [
                "能力约束零容忍机制",
                "适应度多维评分系统",
                "GEPA 自动优化",
            ],
            "concerns": [
                "进化收敛速度",
                "评估指标准确性",
            ],
        }

    async def _openhuman_analyze(self, question: str, perspective: str) -> dict:
        """OpenHuman 分析"""
        return {
            "viewpoint": f"[用户体验视角] 从用户角度分析：{question[:30]}... "
                         f"框架需要关注普通用户的可操作性。",
            "key_points": [
                "配置复杂度需要降低",
                "文档和示例完善度",
                "社区响应速度",
            ],
            "concerns": [
                "学习成本较高",
                "错误信息不够友好",
            ],
        }

    async def _heartbeat_loop(self) -> None:
        """心跳循环"""
        while self._connected:
            await asyncio.sleep(30)
            try:
                await self._send({
                    "protocol": "OACP",
                    "version": "1.0",
                    "type": "HEARTBEAT",
                    "from": self._runtime_id,
                })
            except Exception:
                break

    def on(self, message_type: str, handler: Callable) -> None:
        """注册消息处理器"""
        self._handlers[message_type] = handler

    async def send_capability_update(self) -> None:
        """发送能力更新"""
        await self._send({
            "protocol": "OACP",
            "version": "1.0",
            "type": "CAPABILITY_ANNOUNCE",
            "from": self._runtime_id,
            "capabilities": self.capabilities.to_dict(),
            "status": "ready",
            "load": 0.3,
        })

    async def request_collaboration(
        self,
        question: str,
        perspectives: list[str],
        rounds: int = 2,
    ) -> dict:
        """发起协作讨论请求"""
        session_id = str(uuid.uuid4())

        await self._send({
            "protocol": "OACP",
            "version": "1.0",
            "type": "COLLABORATION_REQUEST",
            "from": self._runtime_id,
            "session_id": session_id,
            "question": question,
            "required_perspectives": [
                {"perspective": p} for p in perspectives
            ],
            "discussion_rounds": rounds,
            "timeout_seconds": 300,
        })

        # 等待结果（简化实现）
        await asyncio.sleep(rounds * 5 + 5)

        return {"session_id": session_id, "status": "completed"}

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def runtime_id(self) -> str | None:
        return self._runtime_id
