"""Team 管理 - 团队生命周期、Agent 角色分配"""

from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    """Agent 角色枚举"""

    ORCHESTRATOR = "orchestrator"  # 规划者：分解任务、协调其他 Agent
    SPECIALIST = "specialist"  # 专家：执行特定领域任务
    HUMAN = "human"  # 人类：审批关键决策


class AgentState(str, Enum):
    """Agent 状态"""

    IDLE = "idle"  # 空闲，等待任务
    RUNNING = "running"  # 执行中
    WAITING = "waiting"  # 等待其他 Agent
    BLOCKED = "blocked"  # 被阻塞
    DONE = "done"  # 完成任务


class Agent(BaseModel):
    """Agent 模型"""

    id: UUID = Field(default_factory=uuid4)
    name: str
    role: AgentRole
    description: str = ""
    state: AgentState = AgentState.IDLE
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, *args: Any, **kwargs: Any) -> None:
        if not self.description:
            self.description = f"{self.role.value} agent: {self.name}"


class Team(BaseModel):
    """Team 模型"""

    id: UUID = Field(default_factory=uuid4)
    name: str
    description: str = ""
    agents: list[Agent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_agent(self, agent: Agent) -> None:
        """添加 Agent 到团队"""
        if any(a.id == agent.id for a in self.agents):
            raise ValueError(f"Agent {agent.id} already in team")
        self.agents.append(agent)

    def remove_agent(self, agent_id: UUID) -> None:
        """从团队移除 Agent"""
        self.agents = [a for a in self.agents if a.id != agent_id]

    def get_agent(self, name: str) -> Agent | None:
        """按名称查找 Agent"""
        for agent in self.agents:
            if agent.name == name:
                return agent
        return None

    def get_agents_by_role(self, role: AgentRole) -> list[Agent]:
        """按角色查找 Agent"""
        return [a for a in self.agents if a.role == role]

    @property
    def orchestrator(self) -> Agent | None:
        """获取编排器 Agent"""
        orchestrators = self.get_agents_by_role(AgentRole.ORCHESTRATOR)
        return orchestrators[0] if orchestrators else None

    @property
    def specialists(self) -> list[Agent]:
        """获取所有专家 Agent"""
        return self.get_agents_by_role(AgentRole.SPECIALIST)
