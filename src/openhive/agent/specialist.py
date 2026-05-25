"""Specialist Agent - 专家 Agent，执行特定领域任务"""

from typing import Any

from openhive.agent.base import BaseAgent


class SpecialistAgent(BaseAgent):
    """专家 Agent - 在特定领域执行任务"""

    def __init__(
        self,
        agent_def: Any,
        team: Any,
        memory: Any,
        message_bus: Any,
        llm_client: Any,
        specialty: str = "general",
        skills: list[str] | None = None,
    ):
        super().__init__(agent_def, team, memory, message_bus, llm_client)
        self.specialty = specialty
        self.skills = skills or []

    async def execute_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        """执行专家任务"""
        task_name = task_data.get("name", "unnamed")
        task_description = task_data.get("description", "")

        # 写记忆：开始任务
        await self.write_memory(
            type="task_start",
            content=f"{self.name} 开始执行任务: {task_name}",
            metadata={
                "task_name": task_name,
                "specialty": self.specialty,
            },
        )

        # 根据专长执行不同的处理逻辑
        if self.specialty == "research":
            result = await self._do_research(task_description)
        elif self.specialty == "analysis":
            result = await self._do_analysis(task_description)
        elif self.specialty == "writing":
            result = await self._do_writing(task_description)
        else:
            result = await self._do_general(task_description)

        # 写记忆：完成任务
        await self.write_memory(
            type="task_result",
            content=f"{self.name} 完成任务: {task_name}",
            metadata={
                "task_name": task_name,
                "result_summary": str(result)[:200],
            },
        )

        return {
            "task_name": task_name,
            "specialty": self.specialty,
            **result,
        }

    async def _do_research(self, description: str) -> dict[str, Any]:
        """执行研究任务"""
        prompt = f"""你是一个研究专家。请对以下主题进行深入研究：

{description}

提供：
1. 关键发现
2. 信息来源
3. 初步结论"""

        response = await self.llm.complete(prompt)
        return {
            "type": "research",
            "description": description,
            "findings": response,
        }

    async def _do_analysis(self, description: str) -> dict[str, Any]:
        """执行分析任务"""
        prompt = f"""你是一个分析专家。请分析以下内容：

{description}

提供：
1. 核心问题
2. 关键洞察
3. 建议行动"""

        response = await self.llm.complete(prompt)
        return {
            "type": "analysis",
            "description": description,
            "insights": response,
        }

    async def _do_writing(self, description: str) -> dict[str, Any]:
        """执行写作任务"""
        prompt = f"""你是一个专业写作专家。请根据以下要求撰写内容：

{description}

要求：
1. 结构清晰
2. 语言专业
3. 实用性强"""

        response = await self.llm.complete(prompt)
        return {
            "type": "writing",
            "description": description,
            "content": response,
        }

    async def _do_general(self, description: str) -> dict[str, Any]:
        """执行通用任务"""
        prompt = f"""{description}"""
        response = await self.llm.complete(prompt)
        return {
            "type": "general",
            "description": description,
            "result": response,
        }

    async def handle_command(self, command: str, params: dict[str, Any]) -> None:
        """处理自定义命令"""
        if command == "report":
            # 上报状态
            await self.broadcast(
                "agent_status",
                {
                    "agent": self.name,
                    "specialty": self.specialty,
                    "skills": self.skills,
                },
            )
