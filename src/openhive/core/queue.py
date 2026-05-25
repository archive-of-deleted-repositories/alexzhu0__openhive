"""Dual-Layer Task Queue - 双层任务队列

借鉴 OpenClaw CH06 的双层队列编排设计:
- Session 层：同 session 内任务串行
- Global 层：跨 session 任务协调
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from openhive.core.task import Task, TaskStatus


class QueuePriority(int, Enum):
    """队列优先级"""

    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class QueueEntry:
    """队列条目"""

    task: Task
    priority: QueuePriority = QueuePriority.NORMAL
    session_id: UUID | None = None  # Session 层需要
    enqueued_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())


class DualLayerTaskQueue:
    """双层任务队列

    Session 层：同 session 内任务串行执行
    Global 层：跨 session 任务协调执行
    """

    def __init__(self):
        # Session 层队列：session_id -> [tasks]（串行）
        self._session_queues: dict[UUID, asyncio.Queue] = defaultdict(asyncio.Queue)
        self._session_locks: dict[UUID, asyncio.Lock] = defaultdict(asyncio.Lock)

        # Global 层队列：（并行）
        self._global_queue: asyncio.Queue = asyncio.Queue()

        # 全局锁（用于任务分配）
        self._global_lock = asyncio.Lock()

        # 任务注册表
        self._tasks: dict[UUID, Task] = {}

        # 运行中的任务
        self._running: dict[UUID, asyncio.Task] = {}

        # 回调
        self._task_callbacks: dict[UUID, asyncio.Future] = {}

        # 是否在运行
        self._running_mode = False
        self._dispatcher_task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动队列"""
        if self._running_mode:
            return
        self._running_mode = True
        self._dispatcher_task = asyncio.create_task(self._dispatch_loop())

    async def stop(self) -> None:
        """停止队列"""
        self._running_mode = False
        if self._dispatcher_task:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass

    async def enqueue_session(
        self,
        task: Task,
        session_id: UUID,
        priority: QueuePriority = QueuePriority.NORMAL,
    ) -> None:
        """Session 层入队：同 session 内任务串行

        Args:
            task: 任务
            session_id: Session ID
            priority: 优先级
        """
        task.status = TaskStatus.PENDING
        self._tasks[task.id] = task

        entry = QueueEntry(
            task=task,
            priority=priority,
            session_id=session_id,
        )

        await self._session_queues[session_id].put(entry)

    async def enqueue_global(
        self,
        task: Task,
        priority: QueuePriority = QueuePriority.NORMAL,
    ) -> None:
        """Global 层入队：跨 session 任务协调

        Args:
            task: 任务
            priority: 优先级
        """
        task.status = TaskStatus.PENDING
        self._tasks[task.id] = task

        entry = QueueEntry(
            task=task,
            priority=priority,
            session_id=None,
        )

        await self._global_queue.put(entry)

    async def get_result(self, task_id: UUID, timeout: float = 300.0) -> Task | None:
        """获取任务结果（等待任务完成）

        Args:
            task_id: 任务 ID
            timeout: 超时时间（秒）

        Returns:
            完成的 Task 或 None（超时）
        """
        if task_id not in self._tasks:
            return None

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._task_callbacks[task_id] = future

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._task_callbacks.pop(task_id, None)

    async def _dispatch_loop(self) -> None:
        """分发循环"""
        while self._running_mode:
            try:
                # 从 global 队列获取任务
                entry = await asyncio.wait_for(
                    self._global_queue.get(),
                    timeout=1.0,
                )
                asyncio.create_task(self._run_task(entry))

            except asyncio.TimeoutError:
                continue
            except Exception:
                if self._running_mode:
                    continue

    async def _run_task(self, entry: QueueEntry) -> None:
        """执行任务"""
        task = entry.task

        if entry.session_id:
            # Session 层：需要获取 session 锁
            async with self._session_locks[entry.session_id]:
                await self._execute_task(task)
        else:
            # Global 层：直接执行
            await self._execute_task(task)

    async def _execute_task(self, task: Task) -> None:
        """执行单个任务"""
        task.status = TaskStatus.RUNNING
        task.started_at = task.started_at or None  # 会由调用者设置

        # 这里调用外部的执行器
        # 实际执行由 Agent 或外部调度器处理
        # 这里只负责状态管理和结果通知

        # 通知等待者
        if task.id in self._task_callbacks:
            future = self._task_callbacks[task.id]
            if not future.done():
                future.set_result(task)

    def get_task(self, task_id: UUID) -> Task | None:
        """获取任务"""
        return self._tasks.get(task_id)

    def list_tasks(
        self,
        team_id: UUID | None = None,
        status: TaskStatus | None = None,
    ) -> list[Task]:
        """列出任务"""
        tasks = list(self._tasks.values())
        if team_id:
            tasks = [t for t in tasks if t.team_id == team_id]
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    def get_session_queue_size(self, session_id: UUID) -> int:
        """获取 Session 队列大小"""
        return self._session_queues[session_id].qsize()

    def get_global_queue_size(self) -> int:
        """获取 Global 队列大小"""
        return self._global_queue.qsize()

    async def cancel_task(self, task_id: UUID) -> bool:
        """取消任务"""
        if task_id not in self._tasks:
            return False

        task = self._tasks[task_id]
        if task.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False

        task.status = TaskStatus.CANCELLED
        task.completed_at = task.completed_at or None

        # 通知等待者
        if task_id in self._task_callbacks:
            future = self._task_callbacks[task_id]
            if not future.done():
                future.set_result(task)

        return True