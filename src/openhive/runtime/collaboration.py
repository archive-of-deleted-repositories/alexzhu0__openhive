"""Multi-Agent Collaboration - 多智能体协作讨论

场景：用户提出问题 → 多个来自不同 runtime 的智能体讨论 → 最终综合回答

架构：
┌─────────────────────────────────────────────────────────────┐
│                    OpenHive Session                          │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Shared Memory Graph                       │  │
│  │  - 讨论记录                                           │  │
│  │  - 共识结论                                           │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐       │
│  │ OpenClaw  │◄─►│   Hermes   │◄─►│ OpenHuman  │       │
│  │  Agent    │   │   Agent    │   │   Agent    │       │
│  └────────────┘   └────────────┘   └────────────┘       │
│         │                 │                 │              │
│         └─────────────────┼─────────────────┘              │
│                           │                                │
│              ┌────────────▼────────────┐                  │
│              │    Discussion Manager    │                  │
│              │  - 轮次控制              │                  │
│              │  - 话题引导              │                  │
│              │  - 共识形成              │                  │
│              └─────────────────────────┘                  │
└─────────────────────────────────────────────────────────────┘
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from openhive.core.message import MessageBus, MessageType


class AgentSource(Enum):
    """智能体来源"""

    OPENCLAW = "openclaw"
    HERMES = "hermes"
    OPENHUMAN = "openhuman"
    OPENHIVE = "openhive"


@dataclass
class DiscussionTurn:
    """讨论轮次"""

    turn_id: UUID
    agent_name: str
    agent_source: AgentSource
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    is_final: bool = False  # 是否是最终结论


@dataclass
class DiscussionResult:
    """讨论结果"""

    question: str
    turns: list[DiscussionTurn]
    consensus: str  # 共识结论
    agreements: list[str]  # 达成一致的点
    disagreements: list[str]  # 分歧点


class DiscussionManager:
    """讨论管理器

    协调多个智能体围绕问题进行讨论
    """

    def __init__(
        self,
        question: str,
        agent_configs: list[dict[str, Any]] | None = None,
    ):
        self.question = question
        self.turns: list[DiscussionTurn] = []
        self._current_turn = 0
        self._max_turns = 6  # 最多讨论 6 轮

        # 初始化参与者
        self._agents: list[dict[str, Any]] = agent_configs or [
            {
                "name": "技术分析师",
                "source": AgentSource.OPENCLAW,
                "prompt": "你是一个技术架构专家，从技术角度分析问题。",
                "specialty": "技术架构",
            },
            {
                "name": "技能评估师",
                "source": AgentSource.HERMES,
                "prompt": "你是一个AI技能评估专家，从能力进化角度分析问题。",
                "specialty": "技能评估",
            },
            {
                "name": "用户体验官",
                "source": AgentSource.OPENHUMAN,
                "prompt": "你是一个用户体验专家，从人类视角分析问题。",
                "specialty": "用户体验",
            },
        ]

    def get_participants(self) -> list[dict[str, Any]]:
        """获取讨论参与者"""
        return self._agents

    def get_next_agent(self) -> dict[str, Any] | None:
        """获取下一个发言的智能体（轮询）"""
        if self._current_turn >= len(self._agents):
            return None
        agent = self._agents[self._current_turn % len(self._agents)]
        self._current_turn += 1
        return agent

    def add_turn(self, turn: DiscussionTurn) -> None:
        """添加一轮讨论"""
        self.turns.append(turn)

    def is_complete(self) -> bool:
        """讨论是否完成"""
        return self._current_turn >= self._max_turns

    def generate_summary(
        self,
        question: str,
        responses: list[str],
    ) -> DiscussionResult:
        """生成讨论总结"""
        agreements = []
        disagreements = []

        # 简化的共识检测：提取共同关键词
        if len(responses) >= 2:
            # 找出都提到的关键词
            first_terms = set(responses[0])
            for r in responses[1:]:
                first_terms &= set(r)

            if first_terms:
                agreements.append(f"共同关注: {', '.join(first_terms)}")

        consensus = responses[-1] if responses else ""

        return DiscussionResult(
            question=question,
            turns=self.turns,
            consensus=consensus,
            agreements=agreements,
            disagreements=disagreements,
        )


class MultiAgentCollaboration:
    """多智能体协作系统

    统一的协作接口，连接不同来源的智能体进行讨论
    """

    def __init__(self, question: str):
        self.question = question
        self.manager = DiscussionManager(question)
        self._llm_client: Any = None

    def set_llm_client(self, client: Any) -> None:
        """设置 LLM 客户端"""
        self._llm_client = client

    async def discuss(self) -> DiscussionResult:
        """执行多智能体讨论

        流程：
        1. 初始化问题背景
        2. 轮流让每个智能体发言
        3. 智能体可以回应其他人的观点
        4. N 轮后生成共识结论
        """
        if not self._llm_client:
            raise RuntimeError("需要先设置 LLM 客户端")

        print(f"\n=== 开始多智能体讨论 ===")
        print(f"问题: {self.question}\n")

        # 收集所有智能体的回复
        all_responses: list[str] = []

        # 第一轮：各自独立发表观点
        print("【第一轮：各自发表观点】\n")

        for agent in self.manager.get_participants():
            response = await self._get_agent_response(
                agent=agent,
                context="这是第一轮讨论，请独立发表你的专业观点。",
                history=[],
            )
            all_responses.append(response)

            turn = DiscussionTurn(
                turn_id=uuid4(),
                agent_name=agent["name"],
                agent_source=agent["source"],
                content=response,
            )
            self.manager.add_turn(turn)

            print(f"{agent['name']}: {response[:150]}...\n")

        # 第二轮：针对彼此观点进行讨论
        print("【第二轮：互相讨论】\n")

        for i, agent in enumerate(self.manager.get_participants()):
            other_responses = [
                r for j, r in enumerate(all_responses) if j != i
            ]

            response = await self._get_agent_response(
                agent=agent,
                context="这是第二轮讨论，请回应其他人的观点并补充你的看法。",
                history=other_responses,
            )
            all_responses[i] += f"\n\n【回应他人】{response}"

            turn = DiscussionTurn(
                turn_id=uuid4(),
                agent_name=agent["name"],
                agent_source=agent["source"],
                content=response,
            )
            self.manager.add_turn(turn)

            print(f"{agent['name']} 回应: {response[:150]}...\n")

        # 生成最终结论
        print("【最终结论】\n")

        final_prompt = f"""基于以下多智能体讨论，生成一个综合结论：

问题: {self.question}

各方观点：
{chr(10).join([f'- {r[:200]}' for r in all_responses])}

请生成一个综合各方观点的最终结论，200字以内。"""

        final_conclusion = await self._llm_client.complete(final_prompt)

        print(f"综合结论: {final_conclusion}\n")
        print("=== 讨论结束 ===\n")

        return self.manager.generate_summary(
            self.question,
            all_responses,
        )

    async def _get_agent_response(
        self,
        agent: dict[str, Any],
        context: str,
        history: list[str],
    ) -> str:
        """获取智能体回复"""
        history_text = ""
        if history:
            history_text = f"\n\n其他人的观点：\n" + "\n".join([
                f"- {h[:200]}..." for h in history
            ])

        prompt = f"""{agent['prompt']}

问题: {self.question}
{context}
{history_text}

请用 100-150 字回答，突出你的专业视角。"""

        return await self._llm_client.complete(prompt)
