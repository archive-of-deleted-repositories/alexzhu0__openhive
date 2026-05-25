"""Team Assembler - 团队自动组建

根据用户目标，动态组建最合适的 Agent 团队

借鉴 OpenClaw Subagent spawn + Capability matching 机制
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from openhive.core.swarm import normalize_risk_level
from openhive.skills.contract import Capability, SkillContract
from openhive.skills.registry import SkillRegistry, get_global_registry


@dataclass
class TaskSpec:
    """任务规格 - 从目标分解出的子任务"""

    name: str  # 任务名称
    description: str  # 任务描述
    specialist_name: str  # 需要的 Specialist 类型
    required_capabilities: list[Capability] = field(default_factory=list)  # 所需能力
    priority: int = 1  # 优先级
    parent_goal: str = ""  # 父目标
    risk_level: str = "medium"  # 风险等级: low/medium/high/critical
    department: str = ""  # 业务归属部门标签


@dataclass
class TeamFormation:
    """团队组建结果"""

    team_id: UUID
    tasks: list[TaskSpec]  # 分解出的任务
    assignments: dict[str, str]  # {task_name: specialist_name}
    candidate_assignments: dict[str, list[str]]  # {task_name: [specialist candidates]}
    reasoning: str  # 组建理由


class TeamAssembler:
    """团队自动组建器

    流程：
    1. 解析用户目标 → 识别所需能力
    2. 匹配 Specialist → 按能力评分排序
    3. 组建团队 → 分配任务
    """

    def __init__(
        self,
        skill_registry: SkillRegistry | None = None,
        candidate_count: int = 2,
        department_priorities: dict[str, float] | None = None,
    ):
        self.skill_registry = skill_registry or get_global_registry()
        self.candidate_count = max(1, int(candidate_count))
        self.department_priorities = {}
        for name, weight in (department_priorities or {}).items():
            try:
                self.department_priorities[(str(name) or "").strip().lower()] = float(weight)
            except (TypeError, ValueError):
                continue

    async def assemble_from_goal(
        self,
        goal: str,
        llm_client: Any | None = None,
    ) -> TeamFormation:
        """从用户目标自动组建团队"""

        team_id = uuid4()

        # 分解任务
        tasks = await self._decompose_goal(goal, llm_client)

        # 匹配 Specialist 并分配任务
        assignments, candidates = self._assign_tasks(tasks)

        reasoning = self._build_reasoning(tasks, assignments, candidates)

        return TeamFormation(
            team_id=team_id,
            tasks=tasks,
            assignments=assignments,
            candidate_assignments=candidates,
            reasoning=reasoning,
        )

    async def _decompose_goal(
        self,
        goal: str,
        llm_client: Any | None = None,
    ) -> list[TaskSpec]:
        """分解目标为任务列表"""
        if llm_client:
            return await self._llm_decompose(goal, llm_client)
        return self._keyword_decompose(goal)

    async def _llm_decompose(
        self,
        goal: str,
        llm_client: Any,
    ) -> list[TaskSpec]:
        """使用 LLM 智能分解目标"""
        prompt = f"""你是一个任务分解专家。用户的目标是：

{goal}

请将这个目标分解成 2-5 个具体的子任务。每个子任务需包含：
- name: 任务名称（英文，简短，用下划线连接）
- description: 任务描述（中文）
- specialist: 适合执行此任务的 Specialist 类型（research/analysis/writing/coding）
- risk_level: low/medium/high/critical
- department: 业务标签（如 strategy / product / engineering）
- capabilities: 完成任务所需能力列表（字符串或对象）

请只返回 JSON 数组，不要有其他文字。"""

        try:
            response = await llm_client.complete(prompt)
            return self._parse_tasks(response, goal)
        except Exception:
            return self._keyword_decompose(goal)

    def _keyword_decompose(self, goal: str) -> list[TaskSpec]:
        """基于关键词的简单分解"""
        tasks = []
        goal_lower = goal.lower()

        # 关键词匹配
        if any(k in goal_lower for k in ["分析", "研究", "调研", "市场", "竞品"]):
            tasks.append(
                TaskSpec(
                    name="research_topic",
                    description=f"深入研究主题：{goal}",
                    specialist_name="research",
                    risk_level="medium",
                    department="strategy",
                    required_capabilities=[
                        Capability(name="research", description="研究能力"),
                        Capability(name="web_search", description="搜索能力"),
                    ],
                )
            )

        if any(k in goal_lower for k in ["分析", "数据", "对比", "评估"]):
            tasks.append(
                TaskSpec(
                    name="analyze_content",
                    description=f"分析内容：{goal}",
                    specialist_name="analysis",
                    risk_level="medium",
                    department="product",
                    required_capabilities=[
                        Capability(name="data_analysis", description="数据分析"),
                        Capability(name="critical_thinking", description="批判性分析"),
                    ],
                )
            )

        if any(k in goal_lower for k in ["写", "报告", "文档", "文章", "博客"]):
            tasks.append(
                TaskSpec(
                    name="write_content",
                    description=f"撰写内容：{goal}",
                    specialist_name="writing",
                    risk_level="low",
                    department="content",
                    required_capabilities=[
                        Capability(name="document_writing", description="文档撰写"),
                    ],
                )
            )

        # 默认至少一个任务
        if not tasks:
            tasks.append(
                TaskSpec(
                    name="general_task",
                    description=goal,
                    specialist_name="research",
                    risk_level="low",
                    department="general",
                    required_capabilities=[
                        Capability(name="research", description="研究能力"),
                    ],
                )
            )

        return tasks

    def _parse_tasks(self, response: str, parent_goal: str) -> list[TaskSpec]:
        """解析 LLM 返回的任务列表"""
        import json

        try:
            start = response.find("[")
            end = response.rfind("]") + 1
            if start != -1 and end != 0:
                items = json.loads(response[start:end])
                tasks = []
                for item in items:
                    tasks.append(
                        TaskSpec(
                            name=item.get("name", "unnamed"),
                            description=item.get("description", ""),
                            specialist_name=item.get("specialist", "research"),
                            risk_level=normalize_risk_level(item.get("risk_level", "medium")),
                            department=item.get("department", ""),
                            required_capabilities=self._parse_capabilities(item.get("capabilities", [])),
                            parent_goal=parent_goal,
                        )
                    )
                return tasks
        except Exception:
            pass

        return self._keyword_decompose(parent_goal)

    @staticmethod
    def _parse_capabilities(raw: list[Any]) -> list[Capability]:
        caps = []
        for item in raw:
            if isinstance(item, dict):
                caps.append(
                    Capability(
                        name=item.get("name", ""),
                        description=item.get("description", ""),
                        level=item.get("level", 1.0),
                    )
                )
            elif isinstance(item, str) and item:
                caps.append(Capability(name=item))
        return caps

    def _assign_tasks(
        self,
        tasks: list[TaskSpec],
    ) -> tuple[dict[str, str], dict[str, list[str]]]:
        """为每个任务分配最合适的 Specialist"""
        assignments = {}
        candidates: dict[str, list[str]] = {}

        for task in tasks:
            # 查找具有所需能力的 Specialist
            matches = self.skill_registry.match_capabilities(task.required_capabilities)

            if matches:
                best_skill, _score = matches[0]
                assignments[task.name] = best_skill.name
                candidates[task.name] = [
                    skill.name
                    for skill, _ in matches[: self._max_candidates(task)]
                ]
            else:
                # 没有精确匹配，使用请求的默认类型
                assignments[task.name] = task.specialist_name
                candidates[task.name] = [task.specialist_name]

        return assignments, candidates

    def _department_weight(self, department: str) -> float:
        """部门权重（未配置为 1.0）"""
        if not isinstance(department, str):
            return 1.0
        return self.department_priorities.get(department.strip().lower(), 1.0)

    def _max_candidates(self, task: TaskSpec) -> int:
        """基于风险决定候选数量"""
        base = self.candidate_count
        if task.risk_level == "critical":
            return max(base, 3)
        if task.risk_level == "high":
            return max(base, 2)
        base_candidate = max(base, 1)

        # 部门权重作为候选扩展/收紧策略（>1 增大候选范围，<1 收窄）
        weight = self._department_weight(task.department)
        adjusted = max(1, round(base_candidate * weight))
        return max(base_candidate, adjusted)

    def _build_reasoning(
        self,
        tasks: list[TaskSpec],
        assignments: dict[str, str],
        candidates: dict[str, list[str]],
    ) -> str:
        """构建组建理由"""
        lines = [f"目标分解为 {len(tasks)} 个子任务："]
        for task in tasks:
            specialist = assignments.get(task.name, "unknown")
            candidate_list = candidates.get(task.name, [specialist])
            lines.append(
                "  • {name} → {specialist} (候选: {cands}, 风险: {risk}, 部门: {dept})".format(
                    name=task.name,
                    specialist=specialist,
                    cands=",".join(candidate_list),
                    risk=task.risk_level,
                    dept=task.department or "general",
                )
            )
        return "\n".join(lines)

    def match_specialists_for_task(
        self,
        required_capabilities: list[Capability],
    ) -> list[tuple[SkillContract, float]]:
        """查找最适合某任务的 Specialist"""
        return self.skill_registry.match_capabilities(required_capabilities)
