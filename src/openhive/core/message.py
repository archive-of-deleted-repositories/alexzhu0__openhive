"""Message Bus - 实时消息总线

支持两种后端:
- MessageBusLocal: 本地开发用（asyncio.Queue）
- MessageBusRedis: 生产环境用（Redis Pub/Sub）
"""

import asyncio
import json
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """消息类型"""

    TASK = "task"
    RESULT = "result"
    ERROR = "error"
    EVENT = "event"
    COMMAND = "command"
    HEARTBEAT = "heartbeat"


class Message(BaseModel):
    """消息模型"""

    id: UUID = Field(default_factory=uuid4)
    type: MessageType
    sender_id: UUID | None = None
    sender_name: str | None = None
    receiver_id: UUID | None = None
    team_id: UUID
    channel: str = "general"
    content: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    reply_to: UUID | None = None


class AbstractMessageBus(ABC):
    """消息总线抽象接口"""

    async def connect(self) -> None:
        raise NotImplementedError

    async def disconnect(self) -> None:
        raise NotImplementedError

    async def publish(self, message: Message) -> int:
        raise NotImplementedError

    async def subscribe(
        self,
        team_id: UUID,
        channel: str,
        handler: Callable[[Message], None],
    ) -> None:
        raise NotImplementedError

    async def unsubscribe(self, team_id: UUID, channel: str) -> None:
        raise NotImplementedError


class MessageBusLocal(AbstractMessageBus):
    """本地开发用内存消息总线（基于 asyncio.Queue）"""

    def __init__(self):
        self._channels: dict[str, list[tuple[UUID, str, Callable[[Message], None]]]] = (
            {}
        )
        self._queues: dict[str, asyncio.Queue[Message]] = {}
        self._listener_tasks: dict[str, asyncio.Task] = {}

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        for task in self._listener_tasks.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._listener_tasks.clear()
        self._channels.clear()
        self._queues.clear()

    async def publish(self, message: Message) -> int:
        channel_key = f"openhive:{message.team_id}:{message.channel}"
        if channel_key not in self._queues:
            self._queues[channel_key] = asyncio.Queue()

        await self._queues[channel_key].put(message)

        # 触发该 channel 的所有 handler
        count = 0
        for team_id, channel, handler in self._channels.get(channel_key, []):
            count += 1
            asyncio.create_task(self._safe_handler(handler, message))

        return count

    async def subscribe(
        self,
        team_id: UUID,
        channel: str,
        handler: Callable[[Message], None],
    ) -> None:
        channel_key = f"openhive:{team_id}:{channel}"

        if channel_key not in self._queues:
            self._queues[channel_key] = asyncio.Queue()

        if channel_key not in self._channels:
            self._channels[channel_key] = []

        self._channels[channel_key].append((team_id, channel, handler))

        if channel_key not in self._listener_tasks:
            self._listener_tasks[channel_key] = asyncio.create_task(
                self._listen(channel_key)
            )

    async def unsubscribe(self, team_id: UUID, channel: str) -> None:
        channel_key = f"openhive:{team_id}:{channel}"
        if channel_key in self._channels:
            self._channels[channel_key] = [
                (tid, ch, h)
                for tid, ch, h in self._channels[channel_key]
                if not (tid == team_id and ch == channel)
            ]

    async def _listen(self, channel_key: str) -> None:
        queue = self._queues.get(channel_key)
        if not queue:
            return

        try:
            while True:
                message = await queue.get()
                for team_id, channel, handler in self._channels.get(channel_key, []):
                    asyncio.create_task(self._safe_handler(handler, message))
        except asyncio.CancelledError:
            pass

    async def _safe_handler(self, handler: Callable[[Message], None], message: Message) -> None:
        try:
            import inspect
            if inspect.iscoroutinefunction(handler):
                await handler(message)
            else:
                handler(message)
        except Exception:
            pass

    # === 高级 API ===

    async def send_task(
        self,
        sender_id: UUID,
        sender_name: str,
        receiver_id: UUID,
        team_id: UUID,
        task_data: dict[str, Any],
    ) -> Message:
        message = Message(
            type=MessageType.TASK,
            sender_id=sender_id,
            sender_name=sender_name,
            receiver_id=receiver_id,
            team_id=team_id,
            content=task_data,
        )
        await self.publish(message)
        return message

    async def broadcast_event(
        self,
        sender_id: UUID,
        sender_name: str,
        team_id: UUID,
        event_type: str,
        event_data: dict[str, Any],
    ) -> Message:
        message = Message(
            type=MessageType.EVENT,
            sender_id=sender_id,
            sender_name=sender_name,
            team_id=team_id,
            channel="events",
            content={"event_type": event_type, **event_data},
        )
        await self.publish(message)
        return message

    async def send_command(
        self,
        human_id: UUID,
        team_id: UUID,
        target_agent_id: UUID | None,
        command: str,
        params: dict[str, Any] | None = None,
    ) -> Message:
        message = Message(
            type=MessageType.COMMAND,
            sender_id=human_id,
            sender_name="human",
            receiver_id=target_agent_id,
            team_id=team_id,
            channel="commands",
            content={"command": command, "params": params or {}},
        )
        await self.publish(message)
        return message

    async def reply(
        self,
        original: Message,
        content: dict[str, Any],
    ) -> Message:
        message = Message(
            type=MessageType.RESULT,
            sender_id=original.receiver_id,
            sender_name=None,
            receiver_id=original.sender_id,
            team_id=original.team_id,
            channel=original.channel,
            content=content,
            reply_to=original.id,
        )
        await self.publish(message)
        return message


class MessageBusRedis(AbstractMessageBus):
    """Redis Pub/Sub 生产环境消息总线"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
    ):
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self._redis: Any = None
        self._pubsub: Any = None
        self._subscriptions: dict[str, Callable[[Message], None]] = {}
        self._listener_task: asyncio.Task | None = None

    async def connect(self) -> None:
        import redis.asyncio as redis

        self._redis = redis.Redis(
            host=self.host,
            port=self.port,
            db=self.db,
            password=self.password,
            decode_responses=False,
        )
        self._pubsub = self._redis.pubsub()

    async def disconnect(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        if self._pubsub:
            await self._pubsub.close()

        if self._redis:
            await self._redis.close()

    async def publish(self, message: Message) -> int:
        if not self._redis:
            raise RuntimeError("Not connected to Redis")

        channel = f"openhive:{message.team_id}:{message.channel}"
        payload = message.model_dump_json()
        return await self._redis.publish(channel, payload)

    async def subscribe(
        self,
        team_id: UUID,
        channel: str,
        handler: Callable[[Message], None],
    ) -> None:
        if not self._pubsub:
            raise RuntimeError("Not connected to Redis")

        full_channel = f"openhive:{team_id}:{channel}"
        await self._pubsub.subscribe(full_channel)
        self._subscriptions[full_channel] = handler

        if not self._listener_task:
            self._listener_task = asyncio.create_task(self._listen())

    async def unsubscribe(self, team_id: UUID, channel: str) -> None:
        if not self._pubsub:
            raise RuntimeError("Not connected to Redis")

        full_channel = f"openhive:{team_id}:{channel}"
        await self._pubsub.unsubscribe(full_channel)
        self._subscriptions.pop(full_channel, None)

    async def _listen(self) -> None:
        if not self._pubsub:
            return

        try:
            async for message in self._pubsub.listen():
                if message["type"] == "message":
                    channel = message["channel"]
                    if channel in self._subscriptions:
                        try:
                            data = json.loads(message["data"])
                            msg = Message(**data)
                            self._subscriptions[channel](msg)
                        except Exception:
                            pass
        except asyncio.CancelledError:
            pass

    async def send_task(
        self,
        sender_id: UUID,
        sender_name: str,
        receiver_id: UUID,
        team_id: UUID,
        task_data: dict[str, Any],
    ) -> Message:
        message = Message(
            type=MessageType.TASK,
            sender_id=sender_id,
            sender_name=sender_name,
            receiver_id=receiver_id,
            team_id=team_id,
            content=task_data,
        )
        await self.publish(message)
        return message

    async def broadcast_event(
        self,
        sender_id: UUID,
        sender_name: str,
        team_id: UUID,
        event_type: str,
        event_data: dict[str, Any],
    ) -> Message:
        message = Message(
            type=MessageType.EVENT,
            sender_id=sender_id,
            sender_name=sender_name,
            team_id=team_id,
            channel="events",
            content={"event_type": event_type, **event_data},
        )
        await self.publish(message)
        return message

    async def send_command(
        self,
        human_id: UUID,
        team_id: UUID,
        target_agent_id: UUID | None,
        command: str,
        params: dict[str, Any] | None = None,
    ) -> Message:
        message = Message(
            type=MessageType.COMMAND,
            sender_id=human_id,
            sender_name="human",
            receiver_id=target_agent_id,
            team_id=team_id,
            channel="commands",
            content={"command": command, "params": params or {}},
        )
        await self.publish(message)
        return message

    async def reply(
        self,
        original: Message,
        content: dict[str, Any],
    ) -> Message:
        message = Message(
            type=MessageType.RESULT,
            sender_id=original.receiver_id,
            sender_name=None,
            receiver_id=original.sender_id,
            team_id=original.team_id,
            channel=original.channel,
            content=content,
            reply_to=original.id,
        )
        await self.publish(message)
        return message


# 向后兼容别名
MessageBus = MessageBusLocal
