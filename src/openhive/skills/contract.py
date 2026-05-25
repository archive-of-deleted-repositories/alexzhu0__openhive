"""Skill Contract - 技能契约定义

借鉴 OpenClaw ToolDescriptor 设计理念 + Hermes 技能进化系统

核心思想：
- 技能通过契约声明能力（类似 OpenClaw 的 capability）
- 技能有约束（硬限制）和适应度（软优化）
- 技能可以进化（借鉴 Hermes GEPA）
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Capability:
    """能力描述"""

    name: str  # 能力名称，如 "web_search", "data_analysis"
    description: str = ""  # 能力描述
    level: float = 1.0  # 能力等级 0.0-1.0

    def matches(self, required: "Capability") -> float:
        """计算能力匹配分数"""
        if self.name != required.name:
            return 0.0
        # 精确匹配返回 1.0，否则按等级计算
        return self.level * required.level


@dataclass
class SkillConstraints:
    """技能硬限制（零容忍）"""

    max_chars: int = 15000  # 最大字符数
    required_sections: list[str] = field(
        default_factory=lambda: ["When to Use", "Procedure"]
    )  # 必需章节
    forbidden_patterns: list[str] = field(default_factory=list)  # 禁止模式
    timeout_seconds: int = 300  # 超时时间
    max_concurrent_tasks: int = 2  # 最大并发任务数

    def validate(self, content: str) -> tuple[bool, list[str]]:
        """验证技能内容是否满足约束

        Returns:
            (passed, error_messages)
        """
        errors = []

        # 字符限制
        if len(content) > self.max_chars:
            errors.append(f"内容超长: {len(content)} > {self.max_chars} 字符")

        # 检查禁止模式
        for pattern in self.forbidden_patterns:
            if pattern in content:
                errors.append(f"包含禁止模式: {pattern}")

        # 检查必需章节
        for section in self.required_sections:
            if section not in content:
                errors.append(f"缺少必需章节: {section}")

        return len(errors) == 0, errors


@dataclass
class FitnessWeights:
    """适应度权重（软优化）借鉴 Hermes 适应度函数设计"""

    correctness: float = 0.4  # 正确性
    procedure_following: float = 0.3  # 流程遵循
    conciseness: float = 0.3  # 简洁性

    def validate(self) -> bool:
        """验证权重和是否为 1.0"""
        return abs(self.correctness + self.procedure_following + self.conciseness - 1.0) < 0.001


@dataclass
class SkillContract:
    """技能契约 - Specialist 的能力声明

    借鉴 OpenClaw ToolDescriptor 设计：
    - name: 技能唯一标识
    - description: 人类可读描述（供 LLM 理解）
    - capabilities: 技能具备的能力列表
    - constraints: 硬限制（零容忍）
    - fitness_weights: 软优化权重
    - tools: 技能可使用的工具列表
    """

    name: str  # 技能唯一名称
    description: str = ""  # 技能描述
    capabilities: list[Capability] = field(default_factory=list)  # 能力列表
    constraints: SkillConstraints = field(default_factory=SkillConstraints)  # 硬限制
    fitness_weights: FitnessWeights = field(default_factory=FitnessWeights)  # 软优化权重
    tools: list[str] = field(default_factory=list)  # 可用工具列表
    metadata: dict[str, Any] = field(default_factory=dict)  # 元数据

    def match_score(self, required_capabilities: list[Capability]) -> float:
        """计算与所需能力的匹配分数"""
        if not required_capabilities:
            return 1.0

        total_score = 0.0
        for required in required_capabilities:
            best_match = 0.0
            for capability in self.capabilities:
                match = capability.matches(required)
                if match > best_match:
                    best_match = match
            total_score += best_match

        return total_score / len(required_capabilities)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": [
                {"name": c.name, "description": c.description, "level": c.level}
                for c in self.capabilities
            ],
            "constraints": {
                "max_chars": self.constraints.max_chars,
                "required_sections": self.constraints.required_sections,
                "forbidden_patterns": self.constraints.forbidden_patterns,
                "timeout_seconds": self.constraints.timeout_seconds,
                "max_concurrent_tasks": self.constraints.max_concurrent_tasks,
            },
            "fitness_weights": {
                "correctness": self.fitness_weights.correctness,
                "procedure_following": self.fitness_weights.procedure_following,
                "conciseness": self.fitness_weights.conciseness,
            },
            "tools": self.tools,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillContract":
        """从字典反序列化"""
        capabilities = [
            Capability(name=c["name"], description=c.get("description", ""), level=c.get("level", 1.0))
            for c in data.get("capabilities", [])
        ]
        constraints_data = data.get("constraints", {})
        constraints = SkillConstraints(
            max_chars=constraints_data.get("max_chars", 15000),
            required_sections=constraints_data.get("required_sections", ["When to Use", "Procedure"]),
            forbidden_patterns=constraints_data.get("forbidden_patterns", []),
            timeout_seconds=constraints_data.get("timeout_seconds", 300),
            max_concurrent_tasks=constraints_data.get("max_concurrent_tasks", 2),
        )
        fitness_data = data.get("fitness_weights", {})
        fitness_weights = FitnessWeights(
            correctness=fitness_data.get("correctness", 0.4),
            procedure_following=fitness_data.get("procedure_following", 0.3),
            conciseness=fitness_data.get("conciseness", 0.3),
        )
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            capabilities=capabilities,
            constraints=constraints,
            fitness_weights=fitness_weights,
            tools=data.get("tools", []),
            metadata=data.get("metadata", {}),
        )


# 预定义能力
class CommonCapabilities:
    """常用能力定义"""

    WEB_SEARCH = Capability(name="web_search", description="搜索互联网获取信息", level=1.0)
    DATA_ANALYSIS = Capability(name="data_analysis", description="分析和处理数据", level=1.0)
    DOCUMENT_WRITING = Capability(name="document_writing", description="撰写文档和报告", level=1.0)
    CODE_WRITING = Capability(name="code_writing", description="编写代码", level=1.0)
    RESEARCH = Capability(name="research", description="研究调研能力", level=1.0)
    CRITICAL_THINKING = Capability(name="critical_thinking", description="批判性分析", level=1.0)
