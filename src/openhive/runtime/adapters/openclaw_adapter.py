"""OpenClaw OACP 适配器

将 OpenClaw gateway 桥接到 OACP Hub
"""

import asyncio
import json
import os
from typing import Any

import websockets


class OpenClawOACPAdapter:
    """OpenClaw 到 OACP 的适配器

    连接 OpenClaw gateway，接收其事件并转换为 OACP 格式
    """

    def __init__(
        self,
        openclaw_gateway_url: str = "ws://localhost:18789",
        oacp_hub_url: str = "ws://localhost:9090/ws",
        runtime_name: str = "OpenClaw Gateway",
        openclaw_token: str | None = None,
    ):
        self.openclaw_url = openclaw_gateway_url
        self.oacp_url = oacp_hub_url
        self.runtime_name = runtime_name
        self.openclaw_token = (
            openclaw_token
            or os.getenv("OPENHIVE_OPENCLAW_TOKEN")
            or os.getenv("OPENCLAW_TOKEN")
        )
        self._openclaw_ws = None
        self._oacp_ws = None
        self._running = False
        self._gateway_conn_id = None
        self._runtime_id = None  # Hub分配的runtime_id
        # 等待中的协作请求: runId -> (session_id, question)
        self._pending_collabs: dict[str, tuple] = {}

    async def start(self) -> None:
        """启动适配器"""
        self._running = True
        await self._oacp_connect()
        await self._openclaw_connect()

    async def stop(self) -> None:
        """停止适配器"""
        self._running = False
        if self._openclaw_ws:
            await self._openclaw_ws.close()
        if self._oacp_ws:
            await self._oacp_ws.close()

    async def _oacp_connect(self) -> None:
        """连接到 OACP Hub"""
        try:
            self._oacp_ws = await websockets.connect(self.oacp_url)

            register_msg = {
                "protocol": "OACP",
                "version": "1.0",
                "type": "REGISTER",
                "runtime_kind": "openclaw",
                "runtime_name": self.runtime_name,
                "capabilities": {
                    "tool_execution": {"enabled": True, "tools": ["bash", "read", "write", "edit"]},
                    "subagent_spawn": {"enabled": True, "max_depth": 3},
                    "channel_protocol": {"enabled": True},
                    "specialists": ["research", "analysis", "technical"],
                }
            }
            await self._oacp_ws.send(json.dumps(register_msg))
            print(f"[OpenClaw→OACP] 已连接到 Hub")

            asyncio.create_task(self._oacp_receive_loop())

        except Exception as e:
            print(f"[OpenClaw→OACP] 连接 OACP Hub 失败: {e}")

    async def _openclaw_connect(self) -> None:
        """连接到 OpenClaw gateway (带 challenge-response 认证)"""
        if not self.openclaw_token:
            print(
                "[OpenClaw→OACP] OpenClaw token 未配置，请设置 "
                "OPENHIVE_OPENCLAW_TOKEN"
            )
            return

        try:
            self._openclaw_ws = await websockets.connect(self.openclaw_url)

            # 1. 接收 challenge
            msg = json.loads(await self._openclaw_ws.recv())
            if msg.get("event") != "connect.challenge":
                print(f"[OpenClaw→OACP] 期望 challenge，实际: {msg}")
                return

            # 2. 发送 connect 请求 (backend 模式，可跳过 device 公钥)
            await self._openclaw_ws.send(json.dumps({
                "type": "req",
                "id": "conn-1",
                "method": "connect",
                "params": {
                    "minProtocol": 3,
                    "maxProtocol": 4,
                    "client": {
                        "id": "gateway-client",
                        "version": "1.0.0",
                        "platform": "linux",
                        "mode": "backend"
                    },
                    "role": "operator",
                    "scopes": ["operator.read", "operator.write"],
                    "caps": [],
                    "commands": [],
                    "permissions": {},
                    "auth": {"token": self.openclaw_token},
                    "locale": "en-US",
                    "userAgent": "openhive-bridge/1.0"
                }
            }))

            # 3. 等待连接响应
            resp = json.loads(await self._openclaw_ws.recv())
            if not resp.get("ok"):
                print(f"[OpenClaw→OACP] OpenClaw 连接失败: {resp}")
                return

            self._gateway_conn_id = resp.get("payload", {}).get("server", {}).get("connId")
            print(f"[OpenClaw→OACP] 已连接到 OpenClaw gateway (conn_id: {self._gateway_conn_id})")

            # 4. 启动消息接收循环
            asyncio.create_task(self._openclaw_receive_loop())

        except Exception as e:
            print(f"[OpenClaw→OACP] 连接 OpenClaw gateway 失败: {e}")

    async def _oacp_receive_loop(self) -> None:
        """接收 OACP Hub 消息"""
        print(f"[OpenClaw→OACP] OACP receive loop started, websocket={self._oacp_ws}")
        try:
            async for msg in self._oacp_ws:
                data = json.loads(msg)
                print(f"[OpenClaw→OACP] Received from Hub: type={data.get('type')}, session={data.get('session_id', '')[:20]}")
                try:
                    await self._handle_oacp_message(data)
                except Exception as e:
                    import traceback
                    print(f"[OpenClaw→OACP] _handle_oacp_message ERROR: {e}")
                    traceback.print_exc()
        except Exception as e:
            print(f"[OpenClaw→OACP] OACP 接收错误: {e}")

    async def _openclaw_receive_loop(self) -> None:
        """接收 OpenClaw gateway 消息"""
        print(f"[OpenClaw→OACP] OpenClaw receive loop started, websocket={self._openclaw_ws}")
        try:
            async for msg in self._openclaw_ws:
                data = json.loads(msg)
                event = data.get("event", "")
                payload = data.get("payload", {})
                run_id = payload.get("runId", "")
                state = payload.get("state", "")
                print(f"[OpenClaw→OACP] From OpenClaw: event={event}, runId={run_id}, state={state}")
                await self._handle_openclaw_event(data)
        except Exception as e:
            print(f"[OpenClaw→OACP] OpenClaw 接收错误: {e}")

    async def _handle_oacp_message(self, data: dict) -> None:
        """处理来自 OACP Hub 的消息"""
        msg_type = data.get("type", "")
        print(f"[OpenClaw→OACP] _handle_oacp_message: type={msg_type}")

        if msg_type == "REGISTER_ACK":
            self._runtime_id = data.get("runtime_id", "")
            print(f"[OpenClaw→OACP] 已注册，runtime_id={self._runtime_id}")

        elif msg_type == "COLLABORATION_REQUEST":
            question = data.get("question", "")
            session_id = data.get("session_id", "")
            round_num = data.get("round", 1)
            max_rounds = data.get("max_rounds", 3)
            history = data.get("history", [])
            is_continue = data.get("is_continue", False)

            print(f"[OpenClaw→OACP] COLLABORATION_REQUEST handler: session={session_id}, round={round_num}")

            if self._openclaw_ws is None:
                print(f"[OpenClaw→OACP] OpenClaw gateway 未连接")
                if self._oacp_ws:
                    response = {
                        "protocol": "OACP",
                        "version": "1.0",
                        "type": "COLLABORATION_RESPONSE",
                        "session_id": session_id,
                        "from": self._runtime_id or "openclaw",
                        "content": {
                            "perspective": "技术架构",
                            "viewpoint": f"[OpenClaw 离线] {question[:50]}...",
                            "key_points": []
                        }
                    }
                    await self._oacp_ws.send(json.dumps(response))
                return

            # 构建辩论 prompt（包含历史讨论）
            if history:
                history_text = self._format_debate_history(history)
                full_prompt = f"""你正在参与一场多智能体辩论。

【辩题】{question}

【其他参与者的观点】
{history_text}

【你的任务】
作为技术架构专家，请针对上述讨论：
1. 评价其他人的观点（同意或反对，并说明理由）
2. 提出你的独到见解
3. 如果觉得讨论已经充分，可以总结并呼吁达成共识

请用简洁、有说服力的语言回应。"""
            else:
                full_prompt = question

            # 生成唯一的 runId 用于跟踪这个请求
            run_id = f"collab-{session_id}-r{round_num}"
            self._pending_collabs[run_id] = (session_id, question, round_num)

            # 发送 chat.send 到 OpenClaw gateway
            await self._openclaw_ws.send(json.dumps({
                "type": "req",
                "id": run_id,
                "method": "chat.send",
                "params": {
                    "sessionKey": "agent:main:main",
                    "idempotencyKey": run_id,
                    "message": full_prompt
                }
            }))
            print(f"[OpenClaw→OACP] 第{round_num}轮: 发送问题到 OpenClaw (run_id={run_id})")

        elif msg_type == "TASK_DISPATCH":
            if self._oacp_ws:
                task_id = data.get("task_id", "")
                payload = data.get("payload", {})
                description = payload.get("description", "")
                specialist = payload.get("specialist", "analysis")

                await self._oacp_ws.send(json.dumps({
                    "protocol": "OACP",
                    "version": "1.0",
                    "type": "RESULT_RETURN",
                    "from": self._runtime_id or "openclaw",
                    "task_id": task_id,
                    "status": "success",
                    "result": {
                        "type": "external_openclaw",
                        "specialist": specialist,
                        "summary": "[OpenClaw] 执行了技术分析任务",
                        "findings": [
                            f"专长 {specialist}",
                            f"任务描述: {description}",
                        ],
                    },
                }))

    def _format_debate_history(self, history: list) -> str:
        """格式化辩论历史"""
        lines = []
        for entry in history:
            round_num = entry.get("round", "?")
            from_agent = entry.get("from", "unknown")
            content = entry.get("content", {})
            viewpoint = content.get("viewpoint", str(content))[:200]
            lines.append(f"--- 第{round_num}轮 [{from_agent}] ---\n{viewpoint}")
        return "\n".join(lines)

    async def _handle_openclaw_event(self, data: dict) -> None:
        """处理来自 OpenClaw gateway 的事件"""
        event_type = data.get("event", "")
        msg_type = data.get("type", "")

        # 处理 chat 事件 (AI 响应)
        # chat 事件结构: {"type": "event", "event": "chat", "payload": {"state": "final", "runId": "...", "message": {"content": [{"type": "text", "text": "..."}]}}}
        if event_type == "chat" or msg_type == "event":
            payload = data.get("payload", {})
            run_id = payload.get("runId", "")
            state = payload.get("state")  # "delta" or "final"

            # 只处理 final 状态的响应
            if state != "final":
                return

            # 提取消息内容 - 在 payload.message.content 中
            message = payload.get("message", {})
            content = message.get("content", [])

            print(f"[OpenClaw→OACP] Chat final: run_id={run_id}, content len={len(content) if content else 0}, pending={list(self._pending_collabs.keys())}")

            if run_id in self._pending_collabs:
                session_id, question, round_num = self._pending_collabs.pop(run_id)
                response_text = self._extract_text(content)
                print(f"[OpenClaw→OACP] Response extracted: '{response_text[:100] if response_text else '(empty)'}...'")

                if self._oacp_ws:
                    viewpoint = response_text if response_text else "[无响应内容]"
                    response = {
                        "protocol": "OACP",
                        "version": "1.0",
                        "type": "COLLABORATION_RESPONSE",
                        "session_id": session_id,
                        "from": self._runtime_id or "openclaw",
                        "content": {
                            "perspective": "技术架构",
                            "viewpoint": f"[OpenClaw] {viewpoint[:500]}",
                            "key_points": []
                        }
                    }
                    await self._oacp_ws.send(json.dumps(response))
                    print(f"[OpenClaw→OACP] 发送响应到 Hub: {viewpoint[:50]}...")

    def _extract_text(self, content: list) -> str:
        """从 OpenClaw content blocks 提取文本"""
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    elif block.get("type") == "thinking":
                        texts.append(f"[思考] {block.get('text', '')[:100]}...")
            return "\n".join(texts)
        return str(content) if content else ""

    async def run(self) -> None:
        """运行适配器"""
        print(f"[OpenClaw→OACP] 启动适配器...")
        print(f"   OpenClaw gateway: {self.openclaw_url}")
        print(f"   OACP Hub: {self.oacp_url}")
        await self.start()
        await asyncio.Event().wait()
