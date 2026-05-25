"""Unit tests for 企业级蜂群配置与调度"""

import asyncio

from unittest.mock import MagicMock

from openhive.agent.orchestrator import OrchestratorAgent
from openhive.core.assembler import TeamAssembler, TaskSpec
from openhive.core.swarm import SwarmExecutionPolicy, SwarmResponseScorer
from openhive.skills.contract import Capability
from openhive.skills.contract import SkillContract
from openhive.skills.registry import SkillRegistry
from openhive.core.team import Agent, AgentRole, Team


def test_swarm_policy_responders_and_defaults():
    """测试企业蜂群策略对候选响应者的选择"""
    policy = SwarmExecutionPolicy.from_mapping(
        {
            "parallelism": 3,
            "redundancy": 3,
            "high_risk_threshold": "high",
        }
    )

    assert policy.parallelism == 3
    assert policy.redundancy == 3
    assert policy.requires_redundancy_for("critical") is True
    assert policy.responders("research", ["analysis", "writing"], "low") == ["research"]
    assert policy.responders("research", ["analysis", "writing"], "critical") == [
        "research",
        "analysis",
        "writing",
    ]


def test_swarm_policy_from_mapping_parses_scoring_settings() -> None:
    """测试 policy.from_mapping 支持评分配置下发"""
    policy = SwarmExecutionPolicy.from_mapping(
        {
            "min_result_chars": 20,
            "scorer_length_weight": 0,
            "scorer_evidence_weight": 1,
            "scorer_structure_weight": 2,
            "scorer_length_target_factor": 4.0,
            "scorer_duplicate_similarity_threshold": 0.5,
            "winner_confidence_threshold": 0.9,
            "max_retry_rounds": 2,
            "retry_on_low_confidence": False,
            "scorer_evidence_fields": "content,analysis",
        }
    )

    assert policy.min_result_chars == 20
    assert policy.scorer_length_weight == 0
    assert policy.scorer_evidence_weight == 1
    assert policy.scorer_structure_weight == 2
    assert policy.scorer_length_target_factor == 4.0
    assert policy.scorer_duplicate_similarity_threshold == 0.5
    assert policy.winner_confidence_threshold == 0.9
    assert policy.max_retry_rounds == 2
    assert policy.retry_on_low_confidence is False
    assert policy.scorer_evidence_fields == ("content", "analysis")


def test_assembler_uses_department_weight_for_candidate_count():
    """测试部门权重会影响候选专家数"""
    registry = SkillRegistry()
    registry.register(
        SkillContract(
            name="skill_a",
            capabilities=[Capability(name="research")],
        )
    )
    registry.register(
        SkillContract(
            name="skill_b",
            capabilities=[Capability(name="research")],
        )
    )
    registry.register(
        SkillContract(
            name="skill_c",
            capabilities=[Capability(name="analysis")],
        )
    )

    task = TaskSpec(
        name="t",
        description="demo",
        specialist_name="research",
        required_capabilities=[Capability(name="research")],
        risk_level="medium",
        department="finance",
    )

    # 默认部门权重不放大候选
    assembler_default = TeamAssembler(skill_registry=registry, candidate_count=1)
    _, candidates_default = assembler_default._assign_tasks([task])
    assert len(candidates_default["t"]) == 1

    # finance 部门配置权重后可放大候选数量
    assembler_weighted = TeamAssembler(
        skill_registry=registry,
        candidate_count=1,
        department_priorities={"finance": 2.0},
    )
    _, candidates_weighted = assembler_weighted._assign_tasks([task])
    assert len(candidates_weighted["t"]) >= 2


def test_orchestrator_resolve_conflicts_prefers_longer_and_valid_responses():
    """测试仲裁器优先选择长度更长的有效响应"""
    team = Team(name="test-team")
    team.add_agent(Agent(name="orch", role=AgentRole.ORCHESTRATOR))
    orchestrator = OrchestratorAgent(
        agent_def=team.get_agent("orch"),
        team=team,
        memory=MagicMock(),
        message_bus=MagicMock(),
        llm_client=MagicMock(),
    )

    policy = SwarmExecutionPolicy(min_result_chars=8)
    result = orchestrator._resolve_conflicts(
        responses=[
            {"status": "done", "specialist": "a", "result": {"content": "short"}},
            {"status": "done", "specialist": "b", "result": {"content": "a much longer result"}},
        ],
        task_id="task1",
        subtask={
            "name": "task1",
            "risk_level": "medium",
            "responders": ["a", "b"],
        },
        policy=policy,
    )

    assert result.chosen == "b"
    assert result.winner_confidence > 0.5


def test_orchestrator_resolve_conflicts_rejects_short_outputs():
    """测试内容过短时不会进入有效候选"""
    team = Team(name="test-team")
    team.add_agent(Agent(name="orch", role=AgentRole.ORCHESTRATOR))
    orchestrator = OrchestratorAgent(
        agent_def=team.get_agent("orch"),
        team=team,
        memory=MagicMock(),
        message_bus=MagicMock(),
        llm_client=MagicMock(),
    )

    policy = SwarmExecutionPolicy(min_result_chars=20)
    result = orchestrator._resolve_conflicts(
        responses=[
            {"status": "done", "specialist": "a", "result": {"content": "too short"}},
            {"status": "done", "specialist": "b", "result": {"content": "also short"}},
        ],
        task_id="task1",
        subtask={"name": "task1", "risk_level": "high", "responders": ["a", "b"]},
        policy=policy,
    )

    assert result.chosen == ""
    assert "No successful responder" in result.notes[0]


def test_orchestrator_redundancy_retries_low_confidence_for_high_risk() -> None:
    """高风险任务低置信度时会触发重试并继续采集结果"""
    team = Team(name="test-team")
    team.add_agent(Agent(name="orch", role=AgentRole.ORCHESTRATOR))
    orchestrator = OrchestratorAgent(
        agent_def=team.get_agent("orch"),
        team=team,
        memory=MagicMock(),
        message_bus=MagicMock(),
        llm_client=MagicMock(),
    )

    async def fake_assign(_responder_name: str, _subtask: dict) -> dict:
        fake_assign.call_count += 1
        if fake_assign.call_count == 1:
            return {
                "status": "done",
                "specialist": "a",
                "result": {"content": "x"},
            }
        return {
            "status": "done",
            "specialist": "a",
            "result": {
                "content": "高质量完整论述，包含可验证依据与结论。",
                "analysis": "清晰的推理链",
                "findings": ["证据A", "证据B"],
                "sources": ["https://example.com"],
                "recommendations": ["落地一套分阶段执行方案"],
                "summary": "给出结论与依据",
            },
        }

    fake_assign.call_count = 0
    orchestrator._assign_and_wait = fake_assign  # type: ignore[method-assign]

    policy = SwarmExecutionPolicy(
        min_result_chars=1,
        winner_confidence_threshold=0.85,
        max_retry_rounds=1,
        audit_enabled=False,
    )

    result = asyncio.run(
        orchestrator._run_with_redundancy(
            task_id="task_retry",
            responders=["a"],
            subtask={"name": "task_retry", "risk_level": "critical", "responders": ["a"]},
            policy=policy,
        )
    )

    assert result["status"] == "done"
    assert result["decision"]["chosen"] == "a"
    assert result["decision"]["attempts"] == 2
    assert result["decision"]["retry_reason"] is None
    assert fake_assign.call_count == 2


def test_orchestrator_low_risk_no_retry_when_threshold_not_met() -> None:
    """低风险任务即使低置信度也不触发重试"""
    team = Team(name="test-team")
    team.add_agent(Agent(name="orch", role=AgentRole.ORCHESTRATOR))
    orchestrator = OrchestratorAgent(
        agent_def=team.get_agent("orch"),
        team=team,
        memory=MagicMock(),
        message_bus=MagicMock(),
        llm_client=MagicMock(),
    )

    async def fake_assign(_responder_name: str, _subtask: dict) -> dict:
        fake_assign.call_count += 1
        return {
            "status": "done",
            "specialist": "a",
            "result": {"content": "x"},
        }

    fake_assign.call_count = 0
    orchestrator._assign_and_wait = fake_assign  # type: ignore[method-assign]

    policy = SwarmExecutionPolicy(
        min_result_chars=1,
        winner_confidence_threshold=0.99,
        max_retry_rounds=1,
        audit_enabled=False,
    )

    result = asyncio.run(
        orchestrator._run_with_redundancy(
            task_id="task_low_risk",
            responders=["a"],
            subtask={"name": "task_low_risk", "risk_level": "low", "responders": ["a"]},
            policy=policy,
        )
    )

    assert result["status"] == "done"
    assert result["decision"]["attempts"] == 1
    assert fake_assign.call_count == 1


def test_orchestrator_resolve_conflicts_prefers_quality_signals() -> None:
    """测试仲裁更偏好结构化、证据完整的响应，而不只是长度"""
    team = Team(name="test-team")
    team.add_agent(Agent(name="orch", role=AgentRole.ORCHESTRATOR))
    orchestrator = OrchestratorAgent(
        agent_def=team.get_agent("orch"),
        team=team,
        memory=MagicMock(),
        message_bus=MagicMock(),
        llm_client=MagicMock(),
    )

    policy = SwarmExecutionPolicy(min_result_chars=8)
    result = orchestrator._resolve_conflicts(
        responses=[
            {
                "status": "done",
                "specialist": "a",
                "result": {"content": "相同长度的简要摘要", "result": "A"},
            },
            {
                "status": "done",
                "specialist": "b",
                "result": {
                    "content": "证据驱动的结论摘要",
                    "result": "B",
                    "findings": ["第一条证据", "第二条证据"],
                    "analysis": "基于可验证事实的推理过程",
                },
            },
        ],
        task_id="task1",
        subtask={"name": "task1", "risk_level": "medium", "responders": ["a", "b"]},
        policy=policy,
    )

    assert result.chosen == "b"


def test_orchestrator_resolve_conflicts_uses_policy_scoring_weights() -> None:
    """测试策略权重会影响仲裁结果"""
    team = Team(name="test-team")
    team.add_agent(Agent(name="orch", role=AgentRole.ORCHESTRATOR))
    orchestrator = OrchestratorAgent(
        agent_def=team.get_agent("orch"),
        team=team,
        memory=MagicMock(),
        message_bus=MagicMock(),
        llm_client=MagicMock(),
    )

    policy = SwarmExecutionPolicy(
        min_result_chars=5,
        scorer_length_weight=0.0,
        scorer_evidence_weight=1.0,
        scorer_structure_weight=0.0,
        scorer_length_target_factor=5.0,
    )
    result = orchestrator._resolve_conflicts(
        responses=[
            {
                "status": "done",
                "specialist": "length-first",
                "result": {
                    "content": "这是一个非常长且详细的回答，给出完整框架和建议。",
                    "result": "冗长文本",
                },
            },
            {
                "status": "done",
                "specialist": "evidence-first",
                "result": {
                    "content": "简要结论与建议",
                    "findings": ["依据1", "依据2", "依据3"],
                    "analysis": "有明确推理链条",
                    "sources": ["https://example.com"],
                },
            },
        ],
        task_id="task3",
        subtask={
            "name": "task3",
            "risk_level": "medium",
            "responders": ["length-first", "evidence-first"],
        },
        policy=policy,
    )

    assert result.chosen == "evidence-first"


def test_orchestrator_resolve_conflicts_removes_duplicate_results() -> None:
    """测试重复响应会被去重，避免重复路由抢答偏差"""
    team = Team(name="test-team")
    team.add_agent(Agent(name="orch", role=AgentRole.ORCHESTRATOR))
    orchestrator = OrchestratorAgent(
        agent_def=team.get_agent("orch"),
        team=team,
        memory=MagicMock(),
        message_bus=MagicMock(),
        llm_client=MagicMock(),
    )

    policy = SwarmExecutionPolicy(min_result_chars=6)
    result = orchestrator._resolve_conflicts(
        responses=[
            {
                "status": "done",
                "specialist": "a",
                "result": {"content": "结论一致: 市场规模 10X"},
            },
            {
                "status": "done",
                "specialist": "b",
                "result": {"content": "结论一致: 市场规模 10X"},
            },
            {
                "status": "done",
                "specialist": "c",
                "result": {"content": "不同观点: 风险在于技术迁移"},
            },
        ],
        task_id="task2",
        subtask={"name": "task2", "risk_level": "medium", "responders": ["a", "b", "c"]},
        policy=policy,
    )

    assert result.chosen in {"a", "c"}
    assert any("去重后候选" in note for note in result.notes)


def test_scorer_extracts_result_text_and_score() -> None:
    """测试评分器可复用的结果文本提取与打分"""
    scorer = SwarmResponseScorer(min_result_chars=10)
    item = {
        "status": "done",
        "result": {
            "content": "这是结构化结论",
            "findings": ["依据 1", "依据 2"],
            "analysis": "推理步骤",
            "sources": ["https://example.com"],
        },
    }

    text = scorer.extract_result_text(item)
    quality = scorer.evaluate(item)

    assert text == "这是结构化结论"
    assert quality.total > 0.4
    assert quality.structure_score > 0.0
