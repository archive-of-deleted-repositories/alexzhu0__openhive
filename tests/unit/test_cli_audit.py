"""Unit tests for swarm audit helper"""

from uuid import UUID

from openhive.cli.main import _build_swarm_audit_rows
from openhive.core.memory import MemoryNode


def _make_node(task: str, decision: dict) -> MemoryNode:
    return MemoryNode(
        type="swarm_decision",
        content=f"子任务 {task} 决策完成: {decision.get('chosen', '')}",
        metadata={"task": task, "decision": decision},
        team_id=UUID(int=0),
    )


def test_audit_rows_filters_by_risk_and_confidence() -> None:
    nodes = [
        _make_node(
            "task_high",
            {
                "task_name": "task_high",
                "chosen": "openclaw",
                "risk_level": "high",
                "winner_confidence": 0.9,
                "attempts": 1,
                "retry_reason": None,
            },
        ),
        _make_node(
            "task_low_conf",
            {
                "task_name": "task_low_conf",
                "chosen": "hermes",
                "risk_level": "low",
                "winner_confidence": 0.62,
                "attempts": 2,
                "retry_reason": None,
            },
        ),
    ]

    high_rows = _build_swarm_audit_rows(nodes, risk_level="high")
    assert len(high_rows) == 1
    assert high_rows[0]["task"] == "task_high"

    low_conf_rows = _build_swarm_audit_rows(nodes, max_confidence=0.8)
    assert len(low_conf_rows) == 1
    assert low_conf_rows[0]["task"] == "task_low_conf"
    assert low_conf_rows[0]["routing_notes"] == []


def test_audit_rows_marks_retry_and_success() -> None:
    nodes = [
        _make_node(
            "task_retry",
            {
                "task_name": "task_retry",
                "chosen": "openclaw",
                "risk_level": "critical",
                "winner_confidence": 0.56,
                "attempts": 3,
                "retry_reason": "高风险任务超过重试上限，仍未通过仲裁阈值",
            },
        ),
        _make_node(
            "task_done",
            {
                "task_name": "task_done",
                "chosen": "hermes",
                "risk_level": "critical",
                "winner_confidence": 0.97,
                "attempts": 1,
                "retry_reason": None,
            },
        ),
    ]

    rows = _build_swarm_audit_rows(nodes)
    attempts = {row["task"]: row for row in rows}
    assert attempts["task_retry"]["is_retry"] is True
    assert attempts["task_retry"]["is_success"] is False
    assert attempts["task_done"]["is_retry"] is False
    assert attempts["task_done"]["is_success"] is True


def test_audit_rows_includes_routing_notes() -> None:
    nodes = [
        _make_node(
            "task_route",
            {
                "task_name": "task_route",
                "chosen": "openclaw",
                "risk_level": "low",
                "winner_confidence": 0.88,
                "attempts": 1,
                "routing_notes": ["按路由能力剔除外部执行者: openclaw"],
            },
        )
    ]

    rows = _build_swarm_audit_rows(nodes)
    assert rows[0]["routing_notes"] == ["按路由能力剔除外部执行者: openclaw"]
