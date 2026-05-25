"""Skill Registry - 技能注册表

管理所有注册的技能，提供能力匹配查询
"""

from typing import Any

from openhive.skills.contract import Capability, SkillContract


class SkillRegistry:
    """技能注册表 - 管理所有技能"""

    def __init__(self):
        self._skills: dict[str, SkillContract] = {}

    def register(self, skill: SkillContract) -> None:
        """注册技能"""
        if skill.name in self._skills:
            raise ValueError(f"技能已存在: {skill.name}")
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillContract | None:
        """获取技能"""
        return self._skills.get(name)

    def list_all(self) -> list[SkillContract]:
        """列出所有技能"""
        return list(self._skills.values())

    def match_capabilities(
        self,
        required: list[Capability],
        limit: int = 10,
    ) -> list[tuple[SkillContract, float]]:
        """根据所需能力匹配技能

        Returns:
            [(skill, match_score), ...] 按匹配分数降序排列
        """
        results = []
        for skill in self._skills.values():
            score = skill.match_score(required)
            if score > 0:
                results.append((skill, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def find_by_capability(self, capability_name: str) -> list[SkillContract]:
        """查找具有特定能力的技能"""
        return [
            s
            for s in self._skills.values()
            if any(c.name == capability_name for c in s.capabilities)
        ]

    def unregister(self, name: str) -> bool:
        """取消注册技能"""
        if name in self._skills:
            del self._skills[name]
            return True
        return False


# 全局注册表实例
_global_registry: SkillRegistry | None = None


def get_global_registry() -> SkillRegistry:
    """获取全局技能注册表"""
    global _global_registry
    if _global_registry is None:
        _global_registry = SkillRegistry()
        register_default_skills()
    return _global_registry


def register_default_skills() -> None:
    """注册默认技能集"""
    registry = get_global_registry()

    # 研究技能
    registry.register(
        SkillContract(
            name="research",
            description="研究专家 - 擅长信息收集、调研分析",
            capabilities=[
                Capability(name="web_search", description="搜索互联网", level=1.0),
                Capability(name="research", description="研究调研", level=1.0),
                Capability(name="data_analysis", description="数据分析", level=0.8),
            ],
            tools=["web_search", "read_file"],
        )
    )

    # 分析技能
    registry.register(
        SkillContract(
            name="analysis",
            description="分析专家 - 擅长数据分析、洞察提炼",
            capabilities=[
                Capability(name="data_analysis", description="数据分析", level=1.0),
                Capability(name="critical_thinking", description="批判性分析", level=1.0),
                Capability(name="research", description="研究能力", level=0.7),
            ],
            tools=["data_analysis"],
        )
    )

    # 写作技能
    registry.register(
        SkillContract(
            name="writing",
            description="写作专家 - 擅长撰写报告、文档、内容创作",
            capabilities=[
                Capability(name="document_writing", description="文档撰写", level=1.0),
                Capability(name="research", description="研究能力", level=0.6),
            ],
            tools=["write_file"],
        )
    )

    # 编码技能
    registry.register(
        SkillContract(
            name="coding",
            description="编码专家 - 擅长代码编写、调试、重构",
            capabilities=[
                Capability(name="code_writing", description="代码编写", level=1.0),
                Capability(name="data_analysis", description="数据分析", level=0.5),
            ],
            tools=["bash", "write_file", "read_file"],
        )
    )
