"""Unit tests for runtime bridge integration"""

import asyncio
import unittest
from unittest.mock import MagicMock

from openhive.agent.orchestrator import OrchestratorAgent
from openhive.core.swarm import SwarmExecutionPolicy
from openhive.core.message import Message, MessageType
from openhive.core.team import Agent, AgentRole, Team
from openhive.runtime.oacp_client import OACPClient


class OACPClientBridgeTest(unittest.IsolatedAsyncioTestCase):
    """验证 OACPClient 的任务派发与等待逻辑"""

    def _build_client(self) -> OACPClient:
        client = OACPClient(
            runtime_kind="openclaw",
            runtime_name="OpenClaw Test Runtime",
            hub_url="ws://localhost:9090/ws",
        )
        client._connected = True
        client._runtime_id = "openclaw@test"

        sent_messages: list[dict] = []

        async def fake_send(message: dict) -> None:
            sent_messages.append(message)

        client._send = fake_send
        client._sent_messages = sent_messages
        return client

    async def test_dispatch_task_returns_result(self) -> None:
        client = self._build_client()

        dispatch_task = asyncio.create_task(
            client.dispatch_task(
                task_id="task-1",
                payload={"goal": "run-test"},
                required_capabilities=["analysis"],
                timeout_seconds=1.0,
            )
        )

        await asyncio.sleep(0)
        await client._handle_result_return({
            "task_id": "task-1",
            "status": "success",
            "result": {"content": "ok"},
        })

        result = await dispatch_task
        assert result["task_id"] == "task-1"
        assert result["status"] == "success"
        assert result["result"] == {"content": "ok"}
        assert len(client._sent_messages) == 1
        assert client._sent_messages[0]["type"] == "TASK_DISPATCH"
        assert client._sent_messages[0]["required_capabilities"] == ["analysis"]

    async def test_dispatch_task_error_payload_maps_to_error(self) -> None:
        client = self._build_client()

        dispatch_task = asyncio.create_task(
            client.dispatch_task(
                task_id="task-err",
                payload={"goal": "run-error"},
                required_capabilities=["analysis"],
                timeout_seconds=1.0,
            )
        )

        await asyncio.sleep(0)
        await client._handle_result_return({
            "task_id": "task-err",
            "type": "ERROR",
            "error": {
                "code": "NO_RUNTIME_AVAILABLE",
                "message": "No runtime available",
            },
        })

        result = await dispatch_task
        assert result["status"] == "error"
        assert result["task_id"] == "task-err"
        assert result["error"] == "No runtime available"

    async def test_dispatch_task_timeout(self) -> None:
        client = self._build_client()
        result = await client.dispatch_task(
            task_id="task-timeout",
            payload={"goal": "run-timeout"},
            timeout_seconds=0.01,
        )
        assert result["status"] == "timeout"
        assert result["task_id"] == "task-timeout"

    async def test_dispatch_task_not_connected(self) -> None:
        client = self._build_client()
        client._connected = False
        result = await client.dispatch_task(task_id="task-offline", payload={})
        assert result["status"] == "error"
        assert result["error"] == "OACP client not connected"


class OrchestratorRuntimeBridgeTest(unittest.IsolatedAsyncioTestCase):
    """验证外部执行器在 orchestrator 中的调用路径"""

    def setUp(self) -> None:
        team = Team(name="runtime-bridge-team")
        team.add_agent(Agent(name="orchestrator", role=AgentRole.ORCHESTRATOR))
        self.orchestrator = OrchestratorAgent(
            agent_def=team.get_agent("orchestrator"),
            team=team,
            memory=MagicMock(),
            message_bus=MagicMock(),
            llm_client=MagicMock(),
            external_executors={
                "openclaw": self._mock_openclaw_executor,
            },
        )
        self.executor_calls: list[dict] = []

    async def _mock_openclaw_executor(self, payload: dict) -> dict:
        self.executor_calls.append(payload)
        return {
            "status": "done",
            "result": {"content": "x" * 20},
            "specialist": "openclaw",
        }

    async def _mock_runtime_executor(self, name: str, _payload: dict) -> dict:
        self.executor_calls.append(name)
        return {
            "status": "done",
            "result": {"content": "x" * 20},
            "specialist": name,
        }

    async def test_run_with_redundancy_selects_external_runtimes_by_capability(
        self,
    ) -> None:
        self.orchestrator.external_executors = {
            "openclaw": lambda payload: self._mock_runtime_executor("openclaw", payload),
            "hermes": lambda payload: self._mock_runtime_executor("hermes", payload),
            "openhuman": lambda payload: self._mock_runtime_executor("openhuman", payload),
        }

        result = await self.orchestrator._run_with_redundancy(
            task_id="task-ext-route",
            responders=["openclaw", "hermes", "openhuman"],
            subtask={
                "name": "task-ext-route",
                "risk_level": "critical",
                "specialist": "writing",
                "required_capabilities": ["document_writing"],
            },
            policy=SwarmExecutionPolicy(
                min_result_chars=1,
                parallelism=3,
                audit_enabled=False,
            ),
        )

        assert result["decision"]["chosen"] == "openhuman"
        assert result["decision"]["responders"] == ["openhuman"]
        assert self.executor_calls == ["openhuman"]

    async def test_run_with_redundancy_records_routing_notes_and_filters_external_low_risk(
        self,
    ) -> None:
        self.orchestrator.external_executors = {
            "openclaw": lambda payload: self._mock_runtime_executor("openclaw", payload),
            "hermes": lambda payload: self._mock_runtime_executor("hermes", payload),
        }
        self.executor_calls = []

        async def _mock_local_assign(_responder_name: str, _subtask: dict) -> dict:
            self.executor_calls.append(_responder_name)
            return {
                "name": _subtask.get("name", "task"),
                "execution_id": _subtask.get("execution_id", "execution-id"),
                "status": "done",
                "specialist": _responder_name,
                "result": {"content": "x" * 20},
            }

        self.orchestrator._assign_and_wait = _mock_local_assign  # type: ignore[method-assign]

        result = await self.orchestrator._run_with_redundancy(
            task_id="task-route-note",
            responders=["openclaw", "hermes", "local"],
            subtask={
                "name": "task-route-note",
                "risk_level": "low",
                "specialist": "unknown",
                "required_capabilities": ["unknown_cap"],
            },
            policy=SwarmExecutionPolicy(
                min_result_chars=1,
                parallelism=3,
                audit_enabled=False,
            ),
        )

        assert result["decision"]["chosen"] == "local"
        assert result["decision"]["routing_notes"] == [
            "按路由能力剔除外部执行者: openclaw, hermes",
        ]
        assert self.executor_calls == ["local"]

    async def test_run_with_redundancy_records_routing_notes_on_high_risk_fallback(
        self,
    ) -> None:
        self.orchestrator.external_executors = {
            "openclaw": lambda payload: self._mock_runtime_executor("openclaw", payload),
            "hermes": lambda payload: self._mock_runtime_executor("hermes", payload),
        }
        self.executor_calls = []

        result = await self.orchestrator._run_with_redundancy(
            task_id="task-route-fallback",
            responders=["openclaw", "hermes"],
            subtask={
                "name": "task-route-fallback",
                "risk_level": "critical",
                "specialist": "unknown",
                "required_capabilities": ["unknown_cap"],
                "parallelism": 2,
            },
            policy=SwarmExecutionPolicy(
                min_result_chars=1,
                parallelism=2,
                audit_enabled=False,
            ),
        )

        assert result["decision"]["chosen"] in {"openclaw", "hermes"}
        assert any("路由保留外部执行者: " in note for note in result["decision"]["routing_notes"])
        assert set(self.executor_calls) == {"openclaw", "hermes"}

    async def test_assign_external_and_wait_success(self) -> None:
        result = await self.orchestrator._assign_external_and_wait(
            responder_name="openclaw",
            subtask={
                "name": "task-demo",
                "description": "external test",
                "required_capabilities": ["analysis"],
            },
        )

        assert result["status"] == "done"
        assert result["name"] == "task-demo"
        assert result["specialist"] == "openclaw"
        assert len(self.executor_calls) == 1
        assert self.executor_calls[0]["required_capabilities"] == ["analysis"]
        assert "result" in result

    async def test_assign_external_and_wait_error_status(self) -> None:
        async def _error_executor(_: dict) -> dict:
            return {
                "status": "error",
                "error": "runtime overloaded",
            }

        self.orchestrator.external_executors["openclaw"] = _error_executor
        result = await self.orchestrator._assign_external_and_wait(
            responder_name="openclaw",
            subtask={"name": "task-demo", "description": "external failed"},
        )

        assert result["status"] == "error"
        assert result["error"] == "runtime overloaded"

    async def test_assign_external_and_wait_timeout(self) -> None:
        async def _timeout_executor(_: dict) -> dict:
            await asyncio.sleep(0)
            raise asyncio.TimeoutError()

        self.orchestrator.external_executors["openclaw"] = _timeout_executor
        result = await self.orchestrator._assign_external_and_wait(
            responder_name="openclaw",
            subtask={"name": "task-demo", "description": "external timeout"},
        )

        assert result["status"] == "timeout"
        assert "任务执行超时" in result["error"]

    async def test_assign_external_and_wait_dispatch_uses_execution_id(self) -> None:
        async def _capture_task_id(payload: dict) -> dict:
            self.executor_calls.append(payload)
            return {
                "status": "done",
                "result": {"content": "captured"},
            }

        self.orchestrator.external_executors["openclaw"] = _capture_task_id
        await self.orchestrator._assign_external_and_wait(
            responder_name="openclaw",
            subtask={
                "name": "task-disp",
                "description": "dispatch id",
                "execution_id": "task-disp::openclaw::000",
            },
        )

        assert self.executor_calls
        payload = self.executor_calls[0]
        assert payload["task_id"] == "task-disp::openclaw::000"
        assert payload["dispatch_task_id"] == "task-disp::openclaw::000"
        assert payload["task_name"] == "task-disp"

    async def test_handle_result_routes_redundant_task_name_waiters(self) -> None:
        orchestrator = self.orchestrator
        loop = asyncio.get_running_loop()
        f1 = loop.create_future()
        f2 = loop.create_future()
        orchestrator._register_legacy_waiter("task-dup", f1)
        orchestrator._register_legacy_waiter("task-dup", f2)

        msg_1 = Message(
            type=MessageType.RESULT,
            team_id=orchestrator.team.id,
            content={"task_name": "task-dup", "execution_id": "task-dup::a", "result": 1},
        )
        await orchestrator._handle_result(msg_1)
        assert f1.done() and f1.result()["execution_id"] == "task-dup::a"
        assert not f2.done()

        msg_2 = Message(
            type=MessageType.RESULT,
            team_id=orchestrator.team.id,
            content={"task_name": "task-dup", "execution_id": "task-dup::b", "result": 2},
        )
        await orchestrator._handle_result(msg_2)
        assert f2.done() and f2.result()["execution_id"] == "task-dup::b"

    def test_parse_subtasks_keeps_required_capabilities(self) -> None:
        parsed = self.orchestrator._parse_subtasks(
            '[{"name":"topic","description":"desc","specialist":"research",'
            '"required_capabilities":["analysis","research"]}]'
        )

        assert len(parsed) == 1
        assert parsed[0]["required_capabilities"] == ["analysis", "research"]
