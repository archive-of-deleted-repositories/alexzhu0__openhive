"""Task Scheduler - 任务调度器"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """任务状态"""

    PENDING = "pending"  # 等待执行
    RUNNING = "running"  # 执行中
    WAITING = "waiting"  # 等待其他任务完成
    DONE = "done"  # 已完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消


class TaskPriority(int, Enum):
    """任务优先级"""

    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class Task(BaseModel):
    """任务模型"""

    id: UUID = Field(default_factory=uuid4)
    name: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    assigned_agent_id: UUID | None = None  # 分配的 Agent
    team_id: UUID
    parent_id: UUID | None = None  # 父任务 ID（用于任务分解）
    result: dict[str, Any] | None = None  # 任务结果
    error: str | None = None  # 错误信息
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def model_post_init(self, *args: Any, **kwargs: Any) -> None:
        if not self.description:
            self.description = self.name


class TaskResult(BaseModel):
    """任务结果"""

    task_id: UUID
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_seconds: float | None = None
