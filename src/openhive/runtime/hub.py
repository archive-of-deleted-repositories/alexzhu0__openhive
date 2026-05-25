"""OACP Hub - Open Agent Collaboration Protocol Hub

全球 AI Agent 协作中心
- 接收全球 OpenClaw/Hermes/OpenHuman Runtime 的连接
- 能力注册与发现
- 任务分发与结果聚合
- 实时协作讨论

WebSocket 支持实现实时双向通信
"""

import asyncio
import json
import uuid
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

import websockets
from websockets.server import WebSocketServerProtocol


class MessageType(str, Enum):
    """OACP 消息类型"""
    CAPABILITY_ANNOUNCE = "CAPABILITY_ANNOUNCE"
    TASK_DISPATCH = "TASK_DISPATCH"
    RESULT_RETURN = "RESULT_RETURN"
    COLLABORATION_REQUEST = "COLLABORATION_REQUEST"
    COLLABORATION_RESPONSE = "COLLABORATION_RESPONSE"
    ERROR = "ERROR"
    HEARTBEAT = "HEARTBEAT"
    REGISTER = "REGISTER"  # Runtime 注册
    DEREGISTER = "DEREGISTER"  # Runtime 注销


@dataclass
class RuntimeEndpoint:
    """注册的 Runtime 端点"""
    runtime_id: str  # 全局唯一 ID (格式: runtime_kind@peer_id)
    kind: str  # openclaw, hermes, openhuman
    name: str  # 人类可读名称
    websocket: WebSocketServerProtocol | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    status: str = "connected"
    load: float = 0.0
    registered_at: datetime = field(default_factory=datetime.utcnow)
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)
    peer_address: str = ""


@dataclass
class CollaborationSession:
    """协作讨论会话"""
    session_id: str
    question: str
    required_perspectives: list[dict]
    rounds: int
    timeout: int
    participants: list[str] = field(default_factory=list)
    responses: list[dict] = field(default_factory=list)
    status: str = "pending"  # pending, active, completed, timeout


class OACPMessage:
    """OACP 消息封装"""

    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.protocol = data.get("protocol", "")
        self.version = data.get("version", "1.0")
        self.type = MessageType(data.get("type", ""))
        self.from_id = data.get("from", "")
        self.to_id = data.get("to", "")

    def to_dict(self) -> dict[str, Any]:
        return self.data

    def is_valid(self) -> bool:
        return self.protocol == "OACP" and self.type in MessageType


class OACPHub:
    """OACP Hub - 全球 AI Agent 协作中心"""

    def __init__(self, host: str = "0.0.0.0", port: int = 9090):
        self.host = host
        self.port = port
        self._runtimes: dict[str, RuntimeEndpoint] = {}
        self._sessions: dict[str, CollaborationSession] = {}
        self._server = None
        self._clients: set[WebSocketServerProtocol] = set()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """启动 Hub 服务"""
        self._server = await websockets.serve(
            self._handle_client,
            self.host,
            self.port,
            subprotocols=["oacp"],
        )
        print(f"🌐 OACP Hub 启动成功!")
        print(f"   地址: ws://{self.host}:{self.port}")
        print(f"   协议: OACP v1.0")
        print(f"   等待全球 Runtime 连接...")
        # Keep server alive until stopped
        await asyncio.Future()

    async def stop(self) -> None:
        """停止 Hub 服务"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_client(
        self,
        websocket: WebSocketServerProtocol,
        path: str,
    ) -> None:
        """处理客户端连接"""
        client_id = str(uuid.uuid4())[:8]
        peer = websocket.remote_address
        print(f"🔗 新连接: {peer[0]}:{peer[1]} (id: {client_id})")

        self._clients.add(websocket)

        try:
            async for message in websocket:
                await self._process_message(websocket, message, client_id)
        except websockets.exceptions.ConnectionClosed:
            print(f"🔌 连接断开: {client_id}")
        finally:
            self._clients.discard(websocket)
            # 清理该客户端注册的 runtime
            await self._cleanup_client_runtimes(websocket)

    async def _process_message(
        self,
        websocket: WebSocketServerProtocol,
        message: str,
        client_id: str,
    ) -> None:
        """处理接收到的消息"""
        try:
            data = json.loads(message)
            msg = OACPMessage(data)

            if not msg.is_valid():
                await self._send_error(
                    websocket,
                    "INVALID_MESSAGE",
                    "Missing or invalid protocol/version/type"
                )
                return

            # 处理不同类型的消息
            handler = getattr(self, f"_handle_{msg.type.value}", None)
            if handler:
                await handler(websocket, msg, client_id)
            else:
                print(f"  未知消息类型: {msg.type}")

        except json.JSONDecodeError:
            await self._send_error(websocket, "JSON_ERROR", "Invalid JSON")
        except Exception as e:
            print(f"  处理消息错误: {e}")
            await self._send_error(websocket, "SERVER_ERROR", str(e))

    async def _handle_REGISTER(
        self,
        websocket: WebSocketServerProtocol,
        msg: OACPMessage,
        client_id: str,
    ) -> None:
        """处理 Runtime 注册"""
        data = msg.data
        runtime_kind = data.get("runtime_kind", "unknown")
        runtime_name = data.get("runtime_name", f"{runtime_kind}-{client_id}")
        capabilities = data.get("capabilities", {})

        # 生成全局唯一 ID
        peer = websocket.remote_address
        peer_id = hashlib.md5(f"{peer[0]}:{peer[1]}:{runtime_kind}".encode()).hexdigest()[:12]
        runtime_id = f"{runtime_kind}@{peer_id}"

        endpoint = RuntimeEndpoint(
            runtime_id=runtime_id,
            kind=runtime_kind,
            name=runtime_name,
            websocket=websocket,
            capabilities=capabilities,
            peer_address=f"{peer[0]}:{peer[1]}",
        )

        async with self._lock:
            self._runtimes[runtime_id] = endpoint

        print(f"✅ Runtime 注册: {runtime_id} ({runtime_name})")
        print(f"   能力: {list(capabilities.keys())}")
        print(f"   在线 Runtime 数: {len(self._runtimes)}")

        # 广播新 Runtime 加入
        await self._broadcast({
            "protocol": "OACP",
            "version": "1.0",
            "type": "RUNTIME_JOINED",
            "runtime_id": runtime_id,
            "runtime_name": runtime_name,
            "runtime_count": len(self._runtimes),
        }, exclude=[websocket])

        # 返回注册确认
        await self._send(websocket, {
            "protocol": "OACP",
            "version": "1.0",
            "type": "REGISTER_ACK",
            "runtime_id": runtime_id,
            "message": "Registered successfully",
            "online_runtimes": len(self._runtimes),
        })

    async def _handle_CAPABILITY_ANNOUNCE(
        self,
        websocket: WebSocketServerProtocol,
        msg: OACPMessage,
        client_id: str,
    ) -> None:
        """处理能力声明更新"""
        # 找到对应的 runtime 并更新能力
        for endpoint in self._runtimes.values():
            if endpoint.websocket == websocket:
                endpoint.capabilities = msg.data.get("capabilities", {})
                endpoint.status = msg.data.get("status", "ready")
                endpoint.load = msg.data.get("load", 0.0)
                endpoint.last_heartbeat = datetime.utcnow()
                break

    async def _handle_COLLABORATION_REQUEST(
        self,
        websocket: WebSocketServerProtocol,
        msg: OACPMessage,
        client_id: str,
    ) -> None:
        """处理协作讨论请求"""
        data = msg.data
        session_id = data.get("session_id", str(uuid.uuid4()))
        question = data.get("question", "")
        perspectives = data.get("required_perspectives", [])
        rounds = data.get("discussion_rounds", 2)
        timeout = data.get("timeout_seconds", 300)

        # 创建协作会话
        session = CollaborationSession(
            session_id=session_id,
            question=question,
            required_perspectives=perspectives,
            rounds=rounds,
            timeout=timeout,
        )

        async with self._lock:
            self._sessions[session_id] = session

        print(f"📋 新协作请求: {session_id}")
        print(f"   问题: {question[:50]}...")
        print(f"   视角: {[p.get('perspective') for p in perspectives]}")

        # 找到能提供各视角的 runtime
        for perspective in perspectives:
            perspective_name = perspective.get("perspective", "")
            matching_runtime = self._find_runtime_for_perspective(perspective_name)

            if matching_runtime:
                session.participants.append(matching_runtime.runtime_id)

                # 发送协作请求给该 runtime
                request_payload = {
                    "protocol": "OACP",
                    "version": "1.0",
                    "type": "COLLABORATION_REQUEST",
                    "from": "oacp-hub",
                    "session_id": session_id,
                    "question": question,
                    "perspective": perspective_name,
                    "round": 1,
                    "total_rounds": rounds,
                    "other_participants": [
                        p for p in session.participants if p != matching_runtime.runtime_id
                    ],
                }

                if matching_runtime.websocket:
                    await self._send(matching_runtime.websocket, request_payload)

        # 返回会话信息给发起者
        await self._send(websocket, {
            "protocol": "OACP",
            "version": "1.0",
            "type": "COLLABORATION_ACK",
            "session_id": session_id,
            "participants": session.participants,
            "message": "Collaboration session created",
        })

    async def _handle_COLLABORATION_RESPONSE(
        self,
        websocket: WebSocketServerProtocol,
        msg: OACPMessage,
        client_id: str,
    ) -> None:
        """处理协作讨论响应"""
        data = msg.data
        session_id = data.get("session_id", "")
        perspective = data.get("perspective", "")
        content = data.get("content", {})
        turn = data.get("turn", 1)

        async with self._lock:
            if session_id in self._sessions:
                session = self._sessions[session_id]
                session.responses.append({
                    "from": msg.from_id,
                    "perspective": perspective,
                    "turn": turn,
                    "content": content,
                    "timestamp": datetime.utcnow().isoformat(),
                })

                # 如果是最后一轮，生成共识
                if turn >= session.rounds:
                    session.status = "completed"
                    await self._finalize_session(session)

    async def _finalize_session(self, session: CollaborationSession) -> None:
        """完成协作会话，生成共识"""
        print(f"📝 协作会话完成: {session.session_id}")
        print(f"   收到 {len(session.responses)} 条回复")

        # 广播最终结果给所有参与者
        result = {
            "protocol": "OACP",
            "version": "1.0",
            "type": "COLLABORATION_RESULT",
            "session_id": session.session_id,
            "question": session.question,
            "responses": session.responses,
            "summary": self._generate_summary(session),
        }

        await self._broadcast(result)

    def _generate_summary(self, session: CollaborationSession) -> str:
        """生成共识摘要"""
        all_points = []
        for resp in session.responses:
            content = resp.get("content", {})
            if isinstance(content, dict):
                points = content.get("key_points", [])
                all_points.extend(points)

        if all_points:
            unique_points = list(set(all_points))[:5]
            return "一致观点: " + ", ".join(unique_points)
        return "讨论完成，请查看详细回复"

    async def _handle_HEARTBEAT(
        self,
        websocket: WebSocketServerProtocol,
        msg: OACPMessage,
        client_id: str,
    ) -> None:
        """处理心跳"""
        for endpoint in self._runtimes.values():
            if endpoint.websocket == websocket:
                endpoint.last_heartbeat = datetime.utcnow()
                break

        # 回复心跳确认
        await self._send(websocket, {
            "protocol": "OACP",
            "version": "1.0",
            "type": "HEARTBEAT_ACK",
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def _handle_TASK_DISPATCH(
        self,
        websocket: WebSocketServerProtocol,
        msg: OACPMessage,
        client_id: str,
    ) -> None:
        """处理任务分发"""
        data = msg.data
        task_id = data.get("task_id", "")
        required_capabilities = data.get("required_capabilities", [])
        if not isinstance(required_capabilities, list):
            required_capabilities = []

        candidates = []
        for capability in required_capabilities:
            runtime = self._find_runtime_by_capability(capability)
            if runtime and runtime not in candidates:
                candidates.append(runtime)

        selected_runtime = candidates[0] if candidates else self._find_ready_runtime()
        if not selected_runtime or not selected_runtime.websocket:
            await self._send(websocket, {
                "protocol": "OACP",
                "version": "1.0",
                "type": "ERROR",
                "error": {
                    "code": "NO_RUNTIME_AVAILABLE",
                    "message": "No ready runtime for this task",
                },
                "task_id": task_id,
            })
            return

        payload = data.get("payload", {})
        await self._send(selected_runtime.websocket, {
            "protocol": "OACP",
            "version": "1.0",
            "type": "TASK_DISPATCH",
            "from": msg.from_id,
            "task_id": task_id,
            "payload": payload,
            "required_capabilities": required_capabilities,
            "required_by": msg.from_id,
            "required_for": data.get("required_for", ""),
            "required_specialists": data.get("required_specialists", []),
        })

    def _find_runtime_for_perspective(self, perspective: str) -> RuntimeEndpoint | None:
        """根据视角找到合适的 runtime"""
        perspective_map = {
            "technical": "openclaw",
            "skill_evolution": "hermes",
            "user_experience": "openhuman",
        }

        kind = perspective_map.get(perspective.lower())
        if not kind:
            return None

        for endpoint in self._runtimes.values():
            if endpoint.kind == kind and endpoint.status == "ready":
                return endpoint

        # Fallback: 返回任何匹配的
        for endpoint in self._runtimes.values():
            if endpoint.status == "ready":
                return endpoint

        return None

    def _find_runtime_by_capability(self, capability: str) -> RuntimeEndpoint | None:
        """根据能力找到 runtime"""
        for endpoint in self._runtimes.values():
            if endpoint.status != "ready":
                continue
            for cap_group in endpoint.capabilities.values():
                if isinstance(cap_group, dict):
                    if capability in cap_group.get("tools", []):
                        return endpoint
                elif isinstance(cap_group, list):
                    if capability in cap_group:
                        return endpoint
        return None

    def _find_ready_runtime(self) -> RuntimeEndpoint | None:
        """返回任意一条就绪 runtime"""
        for endpoint in self._runtimes.values():
            if endpoint.status == "ready":
                return endpoint
        return None

    async def _cleanup_client_runtimes(self, websocket: WebSocketServerProtocol) -> None:
        """清理断开连接的 runtime"""
        to_remove = []
        for runtime_id, endpoint in self._runtimes.items():
            if endpoint.websocket == websocket:
                to_remove.append(runtime_id)

        for runtime_id in to_remove:
            del self._runtimes[runtime_id]
            print(f"🗑️ Runtime 注销: {runtime_id}")

        if to_remove:
            await self._broadcast({
                "protocol": "OACP",
                "version": "1.0",
                "type": "RUNTIME_LEFT",
                "runtime_ids": to_remove,
                "online_count": len(self._runtimes),
            })

    async def _send_error(
        self,
        websocket: WebSocketServerProtocol,
        code: str,
        message: str,
    ) -> None:
        """发送错误消息"""
        await self._send(websocket, {
            "protocol": "OACP",
            "version": "1.0",
            "type": "ERROR",
            "error": {"code": code, "message": message},
        })

    async def _send(self, websocket: WebSocketServerProtocol, data: dict) -> None:
        """发送消息"""
        try:
            await websocket.send(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            print(f"发送消息失败: {e}")

    async def _broadcast(self, data: dict, exclude: list | None = None) -> None:
        """广播消息给所有客户端"""
        exclude = exclude or []
        message = json.dumps(data, ensure_ascii=False)

        for client in self._clients:
            if client not in exclude:
                try:
                    await client.send(message)
                except Exception:
                    pass

    def get_status(self) -> dict[str, Any]:
        """获取 Hub 状态"""
        return {
            "online_runtimes": len(self._runtimes),
            "active_sessions": len(self._sessions),
            "runtimes": [
                {
                    "id": e.runtime_id,
                    "kind": e.kind,
                    "name": e.name,
                    "status": e.status,
                    "capabilities": list(e.capabilities.keys()),
                    "load": e.load,
                    "registered_at": e.registered_at.isoformat(),
                }
                for e in self._runtimes.values()
            ],
        }
