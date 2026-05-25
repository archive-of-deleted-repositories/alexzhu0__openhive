"""OACP Hub server for AI Agent Club."""

import asyncio
import json
from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.web import middleware

from openhive.runtime.hub import OACPHub


class HubServer:
    """Hub 服务器 - HTTP + WebSocket Hub"""

    def __init__(self, host: str = "0.0.0.0", port: int = 9090):
        self.host = host
        self.port = port
        self.hub = OACPHub(host=host, port=port)
        self.app = web.Application()
        self.app.middlewares.append(self._cors_middleware)
        self._setup_routes()
        self._runner: web.AppRunner | None = None
        # Store (websocket, runtime_info) tuples instead of just websocket
        self._runtimes: list[tuple[web.WebSocketResponse, dict]] = []
        # task_id -> websocket clients waiting for RESULT_RETURN
        self._task_waiters: dict[str, list[web.WebSocketResponse]] = {}
        # debate session_id -> {question, round, max_rounds, history, pending}
        self._debates: dict[str, dict] = {}

    def _setup_routes(self) -> None:
        """设置路由"""
        # Web 前端
        static_path = Path(__file__).parent / "static"
        self.app.router.add_get("/", self._serve_index)
        self.app.router.add_static("/static", static_path, show_index=True)

        # API 端点
        self.app.router.add_get("/api/status", self._api_status)
        self.app.router.add_post("/api/collaborate", self._api_collaborate)
        self.app.router.add_post("/api/dispatch", self._api_dispatch)

        # WebSocket 端点
        self.app.router.add_get("/ws", self._handle_websocket)

    @middleware
    async def _cors_middleware(self, request: web.Request, handler):
        """CORS 中间件"""
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            response = await handler(request)

        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, WebSocket"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Sec-WebSocket-Protocol"
        return response

    async def _serve_index(self, request: web.Request) -> web.Response:
        """服务首页"""
        static_path = Path(__file__).parent / "static" / "index.html"
        if static_path.exists():
            return web.FileResponse(static_path)
        return web.Response(text="AI Agent Club - OACP Hub", content_type="text/html")

    async def _api_status(self, request: web.Request) -> web.Response:
        """获取状态"""
        runtimes = [
            {"id": info.get("runtime_id", "unknown"), "name": info.get("runtime_name", "unknown"), "kind": info.get("runtime_kind", "unknown")}
            for ws, info in self._runtimes
        ]
        status = {
            "online_runtimes": len(self._runtimes),
            "active_sessions": 0,
            "runtimes": runtimes
        }
        return web.json_response(status)

    async def _api_collaborate(self, request: web.Request) -> web.Response:
        """发起协作讨论（HTTP API 版本）"""
        try:
            data = await request.json()
            question = data.get("question", "")

            return web.json_response({
                "session_id": "demo-session-001",
                "status": "completed",
                "responses": [
                    {
                        "from": "openclaw",
                        "perspective": "technical",
                        "content": {
                            "viewpoint": "从技术架构角度，这个框架采用了模块化设计...",
                            "key_points": ["模块化设计", "工具链整合"]
                        }
                    },
                    {
                        "from": "hermes",
                        "perspective": "skill_evolution",
                        "content": {
                            "viewpoint": "从技能进化角度，支持动态能力扩展...",
                            "key_points": ["能力声明", "约束验证"]
                        }
                    },
                    {
                        "from": "openhuman",
                        "perspective": "user_experience",
                        "content": {
                            "viewpoint": "从用户体验角度，需要关注配置复杂度...",
                            "key_points": ["学习成本", "文档完善度"]
                        }
                    }
                ],
                "summary": "一致认为：这是一个有价值的框架，建议从小规模试点开始。"
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _api_dispatch(self, request: web.Request) -> web.Response:
        """分发任务"""
        try:
            data = await request.json()
            return web.json_response({
                "task_id": data.get("task_id", "demo-task"),
                "status": "dispatched"
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """处理 WebSocket 连接"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        client_id = f"ws-{len(self._runtimes) + 1}"
        print(f"🔗 WebSocket 连接: {client_id}")

        try:
            # 处理 WebSocket 消息
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        response = await self._process_ws_message(data, client_id, ws)
                        if response:
                            await ws.send_str(json.dumps(response, ensure_ascii=False))
                    except json.JSONDecodeError:
                        await ws.send_str(json.dumps({"error": "Invalid JSON"}))
                elif msg.type == web.WSMsgType.ERROR:
                    print(f"WebSocket 错误: {ws.exception()}")
        except Exception as e:
            print(f"WebSocket 处理错误: {e}")
        finally:
            # Remove runtime by websocket reference
            self._runtimes = [(w, info) for w, info in self._runtimes if w != ws]
            self._task_waiters = {
                task_id: [
                    sender for sender in senders if sender is not ws
                ]
                for task_id, senders in self._task_waiters.items()
                if senders and any(sender is not ws for sender in senders)
            }
            print(f"🔌 WebSocket 断开: {client_id}")

        return ws

    async def _process_ws_message(
        self,
        data: dict,
        client_id: str,
        ws: web.WebSocketResponse,
    ) -> dict | None:
        """处理 WebSocket 消息"""
        msg_type = data.get("type", "")
        protocol = data.get("protocol", "")

        if protocol != "OACP":
            return {"error": "Invalid protocol, expected OACP"}

        # 处理不同类型的消息
        if msg_type == "REGISTER":
            return await self._handle_register(data, client_id, ws)
        elif msg_type == "HEARTBEAT":
            return {"protocol": "OACP", "version": "1.0", "type": "HEARTBEAT_ACK"}
        elif msg_type == "COLLABORATION_REQUEST":
            return await self._handle_collaboration_request(data, client_id, ws)
        elif msg_type == "COLLABORATION_RESPONSE":
            # 辩论响应 - 收集并判断是否进入下一轮
            session_id = data.get("session_id", "")
            from_runtime = data.get("from", client_id)
            content = data.get("content", {})

            if session_id in self._debates:
                debate = self._debates[session_id]

                # 添加到历史
                debate["history"].append({
                    "round": debate["round"],
                    "from": from_runtime,
                    "content": content,
                })

                print(f"📝 {from_runtime} 回应 (第{debate['round']}轮): {str(content)[:80]}...")

                # 检查是否所有 runtime 都已回应（使用 runtime_id 匹配，支持多实例）
                if from_runtime in debate["pending"]:
                    debate["pending"].discard(from_runtime)

                if len(debate["pending"]) == 0:
                    if debate["round"] < debate["max_rounds"]:
                        debate["round"] += 1
                        # 只将 AI agent runtime 加入 pending（使用 runtime_id，支持多实例同类型）
                        debate["pending"] = set(
                            info.get("runtime_id", "") for _, info in self._runtimes
                            if info.get("runtime_kind", "") not in ("web_ui", "client")
                        )
                        print(f"\n🔄 第 {debate['round']} 轮开始...")

                        # 广播下一轮问题给所有 runtime
                        await self._broadcast({
                            "protocol": "OACP",
                            "version": "1.0",
                            "type": "COLLABORATION_REQUEST",
                            "session_id": session_id,
                            "question": debate["question"],
                            "required_perspectives": [],
                            "round": debate["round"],
                            "max_rounds": debate["max_rounds"],
                            "history": debate["history"],
                            "from": "hub",
                            "is_continue": True,
                        }, exclude=None)
                    else:
                        # 辩论结束
                        print(f"\n🏁 辩论结束: {session_id}")
                        # 广播辩论结束给发起者
                        if debate["sender_ws"]:
                            await debate["sender_ws"].send_str(json.dumps({
                                "protocol": "OACP",
                                "version": "1.0",
                                "type": "DEBATE_COMPLETE",
                                "session_id": session_id,
                                "history": debate["history"],
                            }))
                        del self._debates[session_id]
            else:
                # 非辩论模式，直接广播
                await self._broadcast({
                    "protocol": "OACP",
                    "version": "1.0",
                    "type": "COLLABORATION_RESPONSE",
                    "session_id": session_id,
                    "from": from_runtime,
                    "content": content,
                }, exclude=ws)
            return None
        elif msg_type == "TASK_DISPATCH":
            await self._handle_task_dispatch(data, ws)
            return None
        elif msg_type == "RESULT_RETURN":
            await self._handle_task_result(data, ws)
            return None
        elif msg_type == "CAPABILITY_ANNOUNCE":
            return {"protocol": "OACP", "version": "1.0", "type": "ACK"}
        else:
            return {"error": f"Unknown message type: {msg_type}"}

    async def _handle_register(
        self,
        data: dict,
        client_id: str,
        ws: web.WebSocketResponse,
    ) -> dict:
        """处理注册"""
        import hashlib

        runtime_kind = data.get("runtime_kind", "unknown")
        runtime_name = data.get("runtime_name", f"{runtime_kind}-{client_id}")
        capabilities = data.get("capabilities", {})

        # 生成唯一 ID
        peer_id = hashlib.md5(client_id.encode()).hexdigest()[:12]
        runtime_id = f"{runtime_kind}@{peer_id}"

        # Store runtime info alongside websocket
        runtime_info = {
            "runtime_id": runtime_id,
            "runtime_kind": runtime_kind,
            "runtime_name": runtime_name,
            "capabilities": capabilities,
        }
        self._runtimes.append((ws, runtime_info))

        print(f"✅ Runtime 注册: {runtime_id} ({runtime_name})")
        print(f"   能力: {list(capabilities.keys())}")

        # 广播新 Runtime 加入
        await self._broadcast({
            "protocol": "OACP",
            "version": "1.0",
            "type": "RUNTIME_JOINED",
            "runtime_id": runtime_id,
            "runtime_name": runtime_name,
            "online_count": len(self._runtimes),
        }, exclude=ws)

        return {
            "protocol": "OACP",
            "version": "1.0",
            "type": "REGISTER_ACK",
            "runtime_id": runtime_id,
            "message": "Registered successfully",
            "online_runtimes": len(self._runtimes),
        }

    async def _handle_collaboration_request(
        self,
        data: dict,
        client_id: str,
        sender_ws: web.WebSocketResponse,
    ) -> dict:
        """处理协作请求 - 启动多轮辩论"""
        session_id = data.get("session_id", "")
        question = data.get("question", "")
        perspectives = data.get("required_perspectives", [])
        max_rounds = data.get("max_rounds", 3)  # 默认3轮辩论

        # 如果是新一轮辩论请求（由 Hub 内部发起），直接广播
        if data.get("is_continue"):
            print(f"[Hub] Broadcasting continue request")
            await self._broadcast({
                "protocol": "OACP",
                "version": "1.0",
                "type": "COLLABORATION_REQUEST",
                "session_id": session_id,
                "question": question,
                "required_perspectives": perspectives,
                "round": data.get("round", 1),
                "max_rounds": max_rounds,
                "history": data.get("history", []),
                "from": client_id,
                "is_continue": True,
            }, exclude=sender_ws)
            return None

        print(f"\n{'='*60}")
        print(f"📋 新辩论开始: {session_id}")
        print(f"   问题: {question}")
        print(f"   轮次: {max_rounds} 轮")
        print(f"   参与 runtime: {len(self._runtimes)}")

        # 初始化辩论会话
        self._debates[session_id] = {
            "question": question,
            "round": 1,
            "max_rounds": max_rounds,
            "history": [],
            "pending": set(),  # 等待回应的 runtime kind
            "sender_ws": sender_ws,
        }

        # 广播给所有 runtime（包括发起者，让它也参与辩论）
        # 只将 AI agent runtime 加入 pending 集合（使用 runtime_id 支持多实例同类型）
        for ws, info in self._runtimes:
            runtime_kind = info.get("runtime_kind", "")
            if runtime_kind not in ("web_ui", "client"):
                self._debates[session_id]["pending"].add(info.get("runtime_id", ""))

        await self._broadcast({
            "protocol": "OACP",
            "version": "1.0",
            "type": "COLLABORATION_REQUEST",
            "session_id": session_id,
            "question": question,
            "required_perspectives": perspectives,
            "round": 1,
            "max_rounds": max_rounds,
            "history": [],
            "from": client_id,
        }, exclude=None)  # 广播给所有人包括发起者

        return {
            "protocol": "OACP",
            "version": "1.0",
            "type": "COLLABORATION_ACK",
            "session_id": session_id,
            "message": f"辩论开始！共 {max_rounds} 轮",
            "round": 1,
            "max_rounds": max_rounds,
            "target_runtimes": len(self._runtimes),
        }

    async def _handle_task_dispatch(
        self,
        data: dict,
        sender_ws: web.WebSocketResponse,
    ) -> None:
        """处理 TASK_DISPATCH：转发给合适 runtime，并登记返回路径"""
        task_id = data.get("task_id", "")
        if not task_id:
            return

        target_ws = self._select_runtime_for_task(data.get("required_capabilities", []))
        if not target_ws:
            await sender_ws.send_str(json.dumps({
                "protocol": "OACP",
                "version": "1.0",
                "type": "ERROR",
                "error": {
                    "code": "NO_RUNTIME_AVAILABLE",
                    "message": "No runtime available for task dispatch",
                },
                "task_id": task_id,
            }, ensure_ascii=False))
            return

        self._task_waiters.setdefault(task_id, [])
        if sender_ws not in self._task_waiters[task_id]:
            self._task_waiters[task_id].append(sender_ws)
        await target_ws.send_str(json.dumps({
            "protocol": "OACP",
            "version": "1.0",
            "type": "TASK_DISPATCH",
            "from": "openhive-hub",
            "task_id": task_id,
            "payload": data.get("payload", {}),
            "required_capabilities": data.get("required_capabilities", []),
            "required_for": data.get("required_for", ""),
            "required_specialists": data.get("required_specialists", []),
            "required_by": data.get("from", "openhive-client"),
        }, ensure_ascii=False))

    async def _handle_task_result(self, data: dict, sender_ws: web.WebSocketResponse) -> None:
        """处理 RESULT_RETURN：将结果回发给对应发送方"""
        task_id = data.get("task_id", "")
        waiter_ws_list = self._task_waiters.pop(task_id, [])
        if waiter_ws_list:
            for waiter_ws in waiter_ws_list:
                if waiter_ws and not waiter_ws.closed:
                    await waiter_ws.send_str(json.dumps(data, ensure_ascii=False))
        else:
            await self._broadcast(data, exclude=sender_ws)

    def _select_runtime_for_task(self, required_capabilities: Any) -> web.WebSocketResponse | None:
        """按能力匹配 runtime；无匹配则回退第一个在线 runtime"""
        capabilities = required_capabilities
        if not isinstance(capabilities, list):
            capabilities = []

        for cap in capabilities:
            for ws, info in self._runtimes:
                if self._runtime_has_capability(info.get("capabilities", {}), cap):
                    return ws

        return self._runtimes[0][0] if self._runtimes else None

    @staticmethod
    def _runtime_has_capability(
        runtime_capabilities: dict,
        capability: Any,
    ) -> bool:
        """判断某个 runtime 是否包含指定能力"""
        if not isinstance(capability, str):
            return False
        for cap_group in runtime_capabilities.values():
            if isinstance(cap_group, dict):
                tools = cap_group.get("tools", [])
                if isinstance(tools, list) and capability in tools:
                    return True
            elif isinstance(cap_group, list) and capability in cap_group:
                return True
        return False

    async def _broadcast(
        self,
        data: dict,
        exclude: web.WebSocketResponse | None = None,
    ) -> None:
        """广播消息给所有 runtime（除了 exclude）"""
        message = json.dumps(data, ensure_ascii=False)
        for ws, info in self._runtimes:
            if ws != exclude:
                try:
                    await ws.send_str(message)
                except Exception as e:
                    print(f"  ✗ 发送失败 {info.get('runtime_name', 'unknown')}: {e}")

    def _find_runtime_id_by_name(self, name: str) -> str:
        """根据名称查找 runtime ID"""
        for _, info in self._runtimes:
            if info.get("runtime_name", "").lower() in name.lower():
                return info.get("runtime_id", "")
            if info.get("runtime_kind", "").lower() in name.lower():
                return info.get("runtime_id", "")
        return ""

    async def start(self) -> None:
        """启动服务器"""
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()

        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

        print(f"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   AI Agent Club - OACP Hub                                ║
║                                                              ║
║   HTTP Server:  http://{self.host}:{self.port}                       ║
║   WebSocket:   ws://{self.host}:{self.port}/ws                  ║
║                                                              ║
║   Waiting for runtime connections...                       ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
        """)

    async def stop(self) -> None:
        """停止服务器"""
        if self._runner:
            await self._runner.cleanup()


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="AI Agent Club - OACP Hub Server")
    parser.add_argument("--host", default="0.0.0.0", help="Listen address")
    parser.add_argument("--port", type=int, default=9090, help="Listen port")
    args = parser.parse_args()

    server = HubServer(host=args.host, port=args.port)
    await server.start()

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
