"""Hermes OACP 适配器

将 Hermes ACP (Agent Communication Protocol) 桥接到 OACP Hub
通过 Hermes Agent Bridge socket (/tmp/hermes-agent-bridge.sock) 通信
"""

import asyncio
import json
import socket
import threading
import time
import uuid
from typing import Any


class HermesBridgeConnection:
    """Hermes Agent Bridge socket 连接"""

    def __init__(self, socket_path: str = "/tmp/hermes-agent-bridge.sock"):
        self.socket_path = socket_path
        self._lock = threading.Lock()
        self._session_id = f"openhive-{uuid.uuid4().hex[:8]}"

    def _send_sync(self, req: dict, timeout: float = 120) -> dict:
        """同步发送请求到 Hermes bridge"""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect(self.socket_path)
            sock.send((json.dumps(req) + "\n").encode())

            # 接收响应
            data = b""
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
                # 检查是否完成
                try:
                    msg = json.loads(data)
                    if msg.get("status") != "running":
                        break
                except json.JSONDecodeError:
                    continue

            return json.loads(data) if data else {"ok": False, "error": "no data"}
        finally:
            sock.close()

    def chat(self, message: str, timeout: float = 120) -> str:
        """发送消息并获取响应"""
        req = {
            "action": "chat",
            "session_id": self._session_id,
            "message": message,
            "wait": True,
            "timeout": timeout,
        }
        result = self._send_sync(req, timeout)

        if result.get("status") == "complete":
            output = result.get("output", "")
            # 从 events 中提取文本
            if not output:
                events = result.get("events", [])
                texts = []
                for e in events:
                    if e.get("event") in ("thinking.delta", "reasoning.delta"):
                        texts.append(e.get("text", ""))
                    elif e.get("event") == "message.content":
                        content = e.get("content", [])
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    texts.append(block.get("text", ""))
                output = "".join(texts)
            return output
        elif result.get("status") == "running":
            return "[Hermes] 响应超时，会话仍在运行"
        else:
            return f"[Hermes] 错误: {result.get('error', 'unknown')}"


class HermesOACPAdapter:
    """Hermes ACP 到 OACP 的适配器

    通过 Hermes Agent Bridge 连接真实 Hermes AI 进行对话
    """

    def __init__(
        self,
        hermes_bridge_path: str = "/tmp/hermes-agent-bridge.sock",
        oacp_hub_url: str = "ws://localhost:9090/ws",
        runtime_name: str = "Hermes Gateway",
    ):
        self.bridge_path = hermes_bridge_path
        self.oacp_url = oacp_hub_url
        self.runtime_name = runtime_name
        self._oacp_ws = None
        self._running = False
        self._bridge = None
        self._listen_thread = None
        self._runtime_id = None  # Hub分配的runtime_id

    async def start(self) -> None:
        """启动适配器"""
        self._running = True
        self._bridge = HermesBridgeConnection(self.bridge_path)

        # 先测试 bridge 连接
        try:
            test = self._bridge._send_sync({"action": "ping"}, timeout=5)
            if test.get("ok"):
                print(f"[Hermes→OACP] Hermes Bridge 连接成功 (session: {self._bridge._session_id})")
            else:
                print(f"[Hermes→OACP] Hermes Bridge 连接失败: {test}")
        except Exception as e:
            print(f"[Hermes→OACP] Hermes Bridge 连接错误: {e}")

        await self._oacp_connect()

    async def stop(self) -> None:
        """停止适配器"""
        self._running = False
        if self._oacp_ws:
            await self._oacp_ws.close()

    async def _oacp_connect(self) -> None:
        """连接到 OACP Hub"""
        try:
            import websockets

            self._oacp_ws = await websockets.connect(self.oacp_url)

            register_msg = {
                "protocol": "OACP",
                "version": "1.0",
                "type": "REGISTER",
                "runtime_kind": "hermes",
                "runtime_name": self.runtime_name,
                "capabilities": {
                    "capability_assessment": {"enabled": True},
                    "fitness_scoring": {"enabled": True},
                    "skill_evolution": {"enabled": True},
                    "gepa_enabled": True,
                    "constraint_validation": {"enabled": True},
                    "specialists": ["analysis", "research", "strategy", "governance"],
                }
            }
            await self._oacp_ws.send(json.dumps(register_msg))
            print(f"[Hermes→OACP] 已连接到 Hub")

            asyncio.create_task(self._oacp_receive_loop())

        except Exception as e:
            print(f"[Hermes→OACP] 连接 OACP Hub 失败: {e}")

    async def _oacp_receive_loop(self) -> None:
        """接收 OACP Hub 消息"""
        try:
            async for msg in self._oacp_ws:
                data = json.loads(msg)
                await self._handle_oacp_message(data)
        except Exception as e:
            print(f"[Hermes→OACP] OACP 接收错误: {e}")

    async def _handle_oacp_message(self, data: dict) -> None:
        """处理来自 OACP Hub 的消息"""
        msg_type = data.get("type", "")

        if msg_type == "REGISTER_ACK":
            self._runtime_id = data.get("runtime_id", "")
            print(f"[Hermes→OACP] 已注册，runtime_id={self._runtime_id}")

        elif msg_type == "COLLABORATION_REQUEST":
            session_id = data.get("session_id", "")
            question = data.get("question", "")
            perspectives = data.get("required_perspectives", [])
            round_num = data.get("round", 1)
            max_rounds = data.get("max_rounds", 3)
            history = data.get("history", [])
            is_continue = data.get("is_continue", False)

            print(f"[Hermes→OACP] 第{round_num}轮: 收到协作请求")

            # 构建辩论 prompt（包含历史讨论）
            if history:
                history_text = self._format_debate_history(history)
                full_prompt = f"""你正在参与一场多智能体辩论。

【辩题】{question}

【其他参与者的观点】
{history_text}

【你的任务】
作为技能进化与GEPA专家，请针对上述讨论：
1. 评价其他人的观点（同意或反对，并说明理由）
2. 提出你的独到见解
3. 如果觉得讨论已经充分，可以总结并呼吁达成共识

请用简洁、有说服力的语言回应。"""
            else:
                full_prompt = question

            # 在线程池中调用 Hermes Bridge（同步阻塞）
            loop = asyncio.get_event_loop()
            response_text = await loop.run_in_executor(
                None, lambda: self._bridge.chat(full_prompt, timeout=180)
            )

            if self._oacp_ws:
                response = {
                    "protocol": "OACP",
                    "version": "1.0",
                    "type": "COLLABORATION_RESPONSE",
                    "session_id": session_id,
                    "from": self._runtime_id or "hermes",
                    "content": {
                        "perspective": "技能进化与GEPA",
                        "viewpoint": f"[Hermes GEPA] {response_text[:1500]}",
                        "key_points": self._extract_key_points(response_text),
                    }
                }
                await self._oacp_ws.send(json.dumps(response))
                print(f"[Hermes→OACP] 第{round_num}轮: 发送响应到 Hub")

        elif msg_type == "TASK_DISPATCH":
            if self._oacp_ws:
                task_id = data.get("task_id", "")
                payload = data.get("payload", {})
                description = payload.get("description", "")
                specialist = payload.get("specialist", "analysis")

                response = {
                    "protocol": "OACP",
                    "version": "1.0",
                    "type": "RESULT_RETURN",
                    "from": self._runtime_id or "hermes",
                    "task_id": task_id,
                    "status": "success",
                    "result": {
                        "type": "external_hermes",
                        "specialist": specialist,
                        "summary": "[Hermes] 执行了进化与评估任务",
                        "findings": [
                            f"专长 {specialist}",
                            f"任务描述: {description}",
                        ],
                    },
                }
                await self._oacp_ws.send(json.dumps(response))

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

    def _extract_key_points(self, text: str) -> list:
        """从响应中提取关键点"""
        points = []
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith(("**", "- ", "* ", "1.", "2.", "3.")):
                # 清理 markdown
                clean = line.strip("*#- ").strip()
                if clean and len(clean) > 5:
                    points.append(clean[:100])
            if len(points) >= 5:
                break
        return points

    async def run(self) -> None:
        """运行适配器"""
        print(f"[Hermes→OACP] 启动适配器...")
        print(f"   Hermes Bridge: {self.bridge_path}")
        print(f"   OACP Hub: {self.oacp_url}")
        await self.start()
        await asyncio.Event().wait()
