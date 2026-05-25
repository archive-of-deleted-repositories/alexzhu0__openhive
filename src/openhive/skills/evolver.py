"""Skill Evolver - 技能进化器

借鉴 Hermes 自我进化系统 GEPA (Genetic Evolutionary Prompt Adjustment)

核心思想：
- 约束验证：技能必须满足硬限制（零容忍）
- 适应度评分：多维度软优化（正确性 × 0.4 + 流程遵循 × 0.3 + 简洁性 × 0.3）
- 进化迭代：基于反馈自动优化技能描述
"""

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any

from openhive.skills.contract import SkillContract, SkillConstraints, FitnessWeights


@dataclass
class EvalCase:
    """评估用例"""

    input_data: dict[str, Any]  # 输入数据
    expected_output: str  # 期望输出
    evaluation_prompt: str = ""  # 评估提示词


@dataclass
class EvalResult:
    """评估结果"""

    case: EvalCase
    actual_output: str
    fitness_scores: dict[str, float]  # 各维度得分
    total_score: float  # 总分
    feedback: str  # 反馈意见


class SkillEvolver:
    """技能进化器 - 借鉴 Hermes GEPA

    流程：
    1. 初始化种群（多个技能变体）
    2. 评估适应度
    3. 选择优秀个体
    4. 交叉变异生成新个体
    5. 重复直到收敛
    """

    def __init__(
        self,
        constraints: SkillConstraints | None = None,
        weights: FitnessWeights | None = None,
        population_size: int = 5,
        mutation_rate: float = 0.2,
    ):
        self.constraints = constraints or SkillConstraints()
        self.weights = weights or FitnessWeights()
        self.population_size = population_size
        self.mutation_rate = mutation_rate

    async def evolve(
        self,
        skill: SkillContract,
        evaluation_dataset: list[EvalCase],
        iterations: int = 10,
        llm_client: Any | None = None,
    ) -> SkillContract:
        """进化技能，返回优化后的版本

        Args:
            skill: 原始技能
            evaluation_dataset: 评估数据集
            iterations: 进化迭代次数
            llm_client: LLM 客户端用于生成变异

        Returns:
            优化后的技能
        """
        if not evaluation_dataset:
            return skill

        # 初始化种群
        population = [skill]
        for _ in range(self.population_size - 1):
            variant = self._mutate(skill, llm_client)
            population.append(variant)

        best_skill = skill
        best_fitness = 0.0

        for iteration in range(iterations):
            # 评估种群
            scored_population = []
            for variant in population:
                fitness = await self._evaluate(variant, evaluation_dataset, llm_client)
                scored_population.append((variant, fitness))

            # 排序
            scored_population.sort(key=lambda x: x[1], reverse=True)

            # 取最优
            current_best, current_fitness = scored_population[0]
            if current_fitness > best_fitness:
                best_skill = current_best
                best_fitness = current_fitness

            # 选择
            selected = scored_population[: self.population_size // 2]

            # 生成新种群
            new_population = [v for v, _ in selected]
            while len(new_population) < self.population_size:
                parent = random.choice(selected)[0]
                mutant = await self._mutate_async(parent, llm_client)
                new_population.append(mutant)

            population = new_population

        return best_skill

    async def _evaluate(
        self,
        skill: SkillContract,
        dataset: list[EvalCase],
        llm_client: Any | None = None,
    ) -> float:
        """评估技能适应度"""
        if not dataset:
            return 0.0

        results = []
        for case in dataset:
            result = await self._evaluate_case(skill, case, llm_client)
            results.append(result)

        # 计算加权平均
        total_score = 0.0
        for result in results:
            total_score += result.total_score

        return total_score / len(results)

    async def _evaluate_case(
        self,
        skill: SkillContract,
        case: EvalCase,
        llm_client: Any | None = None,
    ) -> EvalResult:
        """评估单个用例"""
        # 检查约束
        constraint_violations = self._check_constraints(skill)

        # 使用 LLM 评估输出质量
        if llm_client:
            feedback, scores = await self._llm_evaluate(skill, case, llm_client)
        else:
            # 简化评估
            feedback = "Mock evaluation"
            scores = {
                "correctness": 0.7,
                "procedure_following": 0.7,
                "conciseness": 0.7,
            }

        # 计算总分
        total_score = (
            scores.get("correctness", 0.0) * self.weights.correctness
            + scores.get("procedure_following", 0.0) * self.weights.procedure_following
            + scores.get("conciseness", 0.0) * self.weights.conciseness
        )

        # 约束违规扣分
        if constraint_violations:
            total_score *= 0.5  # 严重惩罚

        return EvalResult(
            case=case,
            actual_output="",
            fitness_scores=scores,
            total_score=total_score,
            feedback=feedback,
        )

    def _check_constraints(self, skill: SkillContract) -> list[str]:
        """检查约束违规"""
        violations = []

        # 字符限制
        if self.constraints.max_chars > 0:
            if len(skill.description) > self.constraints.max_chars:
                violations.append(
                    f"描述超过限制: {len(skill.description)} > {self.constraints.max_chars}"
                )

        # 必需章节
        for section in self.constraints.required_sections:
            if section.lower() not in skill.description.lower():
                violations.append(f"缺少必需章节: {section}")

        # 禁止模式
        for pattern in self.constraints.forbidden_patterns:
            if pattern in skill.description:
                violations.append(f"包含禁止模式: {pattern}")

        return violations

    async def _llm_evaluate(
        self,
        skill: SkillContract,
        case: EvalCase,
        llm_client: Any,
    ) -> tuple[str, dict[str, float]]:
        """使用 LLM 评估"""
        prompt = f"""评估以下技能描述的质量：

技能名称: {skill.name}
技能描述:
{skill.description}

评估用例输入: {case.input_data}
期望输出: {case.expected_output}

请从以下维度评分（0-1）：
1. correctness（正确性）：输出是否正确、有用
2. procedure_following（流程遵循）：是否遵循指定流程
3. conciseness（简洁性）：是否简洁明了

请返回 JSON 格式：
{{
    "feedback": "详细反馈",
    "scores": {{
        "correctness": 0.0-1.0,
        "procedure_following": 0.0-1.0,
        "conciseness": 0.0-1.0
    }}
}}"""

        try:
            response = await llm_client.complete(prompt)
            return self._parse_llm_response(response)
        except Exception:
            return "评估失败", {
                "correctness": 0.5,
                "procedure_following": 0.5,
                "conciseness": 0.5,
            }

    def _parse_llm_response(self, response: str) -> tuple[str, dict[str, float]]:
        """解析 LLM 响应"""
        import json

        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start != -1 and end != 0:
                data = json.loads(response[start:end])
                feedback = data.get("feedback", "")
                scores = data.get("scores", {})
                return feedback, scores
        except Exception:
            pass

        return response, {
            "correctness": 0.5,
            "procedure_following": 0.5,
            "conciseness": 0.5,
        }

    def _mutate(self, skill: SkillContract, llm_client: Any | None = None) -> SkillContract:
        """变异生成新技能变体"""
        # 简化变异：随机修改描述的一部分
        description = skill.description

        # 随机选择一个变异操作
        mutation_ops = [
            lambda d: d.replace("。", "；"),  # 句号变分号
            lambda d: d.replace("，", "、"),  # 逗号变顿号
            lambda d: d[:100] + "。" if len(d) > 100 else d,  # 截断
            lambda d: d + "。",  # 添加句号
        ]

        mutated_description = random.choice(mutation_ops)(description)

        return SkillContract(
            name=f"{skill.name}_v{random.randint(1, 100)}",
            description=mutated_description,
            capabilities=skill.capabilities.copy(),
            constraints=skill.constraints,
            fitness_weights=skill.fitness_weights,
        )

    async def _mutate_async(
        self,
        skill: SkillContract,
        llm_client: Any | None = None,
    ) -> SkillContract:
        """异步变异（使用 LLM 生成更智能的变异）"""
        if not llm_client:
            return self._mutate(skill, llm_client)

        prompt = f"""基于以下技能描述，生成一个轻微变异的版本：

原始描述:
{skill.description}

要求：
1. 保持相同的结构和长度
2. 只修改 1-2 个地方
3. 使描述更清晰或更简洁

直接返回变异后的描述，不要有其他文字。"""

        try:
            response = await llm_client.complete(prompt)
            return SkillContract(
                name=f"{skill.name}_v{random.randint(1, 100)}",
                description=response.strip(),
                capabilities=skill.capabilities.copy(),
                constraints=skill.constraints,
                fitness_weights=skill.fitness_weights,
            )
        except Exception:
            return self._mutate(skill, llm_client)