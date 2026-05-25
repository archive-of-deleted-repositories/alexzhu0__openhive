"""Base Agent - 所有 Agent 的基类"""

import asyncio
from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from pydantic import Field

from openhive.core.memory import MemoryGraph, MemoryNode
from openhive.core.message import Message, MessageBus, MessageType
from openhive.core.team import Agent, AgentRole, AgentState, Team
from openhive.core.task import Task, TaskStatus


class BaseAgent(ABC):
    """Agent 基类"""

    def __init__(
        self,
        agent_def: Agent,
        team: Team,
        memory: MemoryGraph,
        message_bus: MessageBus,
        llm_client: Any,  # LLM client 接口
    ):
        self.agent_def = agent_def
        self.team = team
        self.memory = memory
        self.message_bus = message_bus
        self.llm = llm_client

        self._running_task: Task | None = None
        self._message_handler: asyncio.Task | None = None

    @property
    def id(self) -> UUID:
        return self.agent_def.id

    @property
    def name(self) -> str:
        return self.agent_def.name

    @property
    def role(self) -> AgentRole:
        return self.agent_def.role

    @property
    def state(self) -> AgentState:
        return self.agent_def.state

    async def start(self) -> None:
        """启动 Agent（订阅消息、开始工作循环）"""
        await self.message_bus.subscribe(
            self.team.id,
            "general",
            self._handle_message,
        )
        # 也订阅 direct 频道（发给此 Agent 的私信）
        await self.message_bus.subscribe(
            self.team.id,
            f"agent:{self.id}",
            self._handle_direct_message,
        )
        self._message_handler = asyncio.create_task(self._work_loop())

    async def stop(self) -> None:
        """停止 Agent"""
        if self._message_handler:
            self._message_handler.cancel()
            try:
                await self._message_handler
            except asyncio.CancelledError:
                pass

    async def _work_loop(self) -> None:
        """工作循环（可被子类重写）"""
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    async def _handle_message(self, message: Message) -> None:
        """处理收到的消息"""
        # 跳过自己发的消息
        if message.sender_id == self.id:
            return

        # 处理不同类型的消息
        if message.type == MessageType.TASK:
            await self._handle_task(message)
        elif message.type == MessageType.COMMAND:
            await self._handle_command(message)
        elif message.type == MessageType.EVENT:
            await self._handle_event(message)
        elif message.type == MessageType.RESULT:
            await self._handle_result(message)

    async def _handle_direct_message(self, message: Message) -> None:
        """处理直接发送的消息（发给此 Agent 的私信）"""
        if message.receiver_id == self.id or message.receiver_id is None:
            await self._handle_message(message)

    async def _handle_task(self, message: Message) -> None:
        """处理任务消息（子类可重写）"""
        task_data = message.content
        task = Task(
            name=task_data.get("name", "unnamed"),
            description=task_data.get("description", ""),
            team_id=self.team.id,
            assigned_agent_id=self.id,
        )

        self._running_task = task
        self.agent_def.state = AgentState.RUNNING

        try:
            result = await self.execute_task(task_data)
            task.status = TaskStatus.DONE
            task.result = result

            # 写记忆
            await self.write_memory(
                type="task_result",
                content=f"Task '{task.name}' completed by {self.name}",
                metadata={"task_id": str(task.id), "result": result},
            )

            # 回复结果
            await self.message_bus.reply(
                message,
                {
                    "status": "done",
                    "task_name": task.name,
                    "execution_id": message.content.get("execution_id"),
                    "task_id": message.content.get("task_id"),
                    "result": result,
                },
            )

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            self.agent_def.state = AgentState.IDLE
            await self.message_bus.reply(
                message,
                {
                    "status": "error",
                    "task_name": task.name,
                    "execution_id": message.content.get("execution_id"),
                    "task_id": message.content.get("task_id"),
                    "error": str(e),
                },
            )

        self._running_task = None
        self.agent_def.state = AgentState.IDLE

    async def _handle_command(self, message: Message) -> None:
        """处理命令消息（用户插入的指令）"""
        command = message.content.get("command")
        params = message.content.get("params", {})

        if command == "stop":
            await self.stop()
        elif command == "status":
            await self.message_bus.reply(
                message,
                {
                    "status": "ok",
                    "agent_id": str(self.id),
                    "state": self.state.value,
                    "running_task": (
                        str(self._running_task.id) if self._running_task else None
                    ),
                },
            )
        else:
            await self.handle_command(command, params)

    async def _handle_event(self, message: Message) -> None:
        """处理事件消息（子类可重写）"""
        pass

    async def _handle_result(self, message: Message) -> None:
        """处理结果消息（子类可重写）"""
        pass

    @abstractmethod
    async def execute_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        """执行任务（子类必须实现）"""
        raise NotImplementedError

    async def handle_command(self, command: str, params: dict[str, Any]) -> None:
        """处理自定义命令（子类可重写）"""
        pass

    async def write_memory(
        self,
        type: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
    ) -> MemoryNode:
        """写入共享记忆"""
        node = MemoryNode(
            type=type,
            content=content,
            metadata=metadata or {},
            embedding=embedding,
            agent_id=self.id,
            team_id=self.team.id,
        )
        return await self.memory.write(node)

    async def read_memory(
        self,
        type_filter: str | None = None,
        limit: int = 50,
    ) -> list[MemoryNode]:
        """读取共享记忆"""
        return await self.memory.query(
            self.team.id,
            type_filter=type_filter,
            limit=limit,
        )

    async def search_memory(
        self,
        query_embedding: list[float],
        type_filter: str | None = None,
        limit: int = 10,
    ) -> list[MemoryNode]:
        """语义搜索记忆"""
        return await self.memory.search(
            self.team.id,
            query_embedding,
            type_filter=type_filter,
            limit=limit,
        )

    async def broadcast(
        self,
        event_type: str,
        event_data: dict[str, Any],
    ) -> None:
        """广播事件"""
        await self.message_bus.broadcast_event(
            self.id,
            self.name,
            self.team.id,
            event_type,
            event_data,
        )

    async def send_to(
        self,
        receiver_name: str,
        message_type: MessageType,
        content: dict[str, Any],
    ) -> None:
        """向指定 Agent 发送消息"""
        receiver = self.team.get_agent(receiver_name)
        if not receiver:
            raise ValueError(f"Agent '{receiver_name}' not found in team")

        message = Message(
            type=message_type,
            sender_id=self.id,
            sender_name=self.name,
            receiver_id=receiver.id,
            team_id=self.team.id,
            content=content,
        )
        await self.message_bus.publish(message)
