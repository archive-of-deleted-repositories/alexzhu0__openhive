"""External runtime routing policy - 企业级外部专家路由"""

from __future__ import annotations

from typing import Any


RUNTIME_CAPABILITY_HINTS: dict[str, tuple[str, ...]] = {
    "openclaw": (
        "web_search",
        "tool_execution",
        "code_writing",
        "subagent_spawn",
        "data_analysis",
    ),
    "hermes": (
        "research",
        "critical_thinking",
        "capability_assessment",
        "fitness_scoring",
        "data_analysis",
    ),
    "openhuman": (
        "human_feedback",
        "document_writing",
        "ux_analysis",
        "user_proxy",
    ),
}

ROLE_CAPABILITY_HINTS: dict[str, tuple[str, ...]] = {
    "research": ("web_search", "research", "data_analysis"),
    "analysis": ("data_analysis", "critical_thinking", "research"),
    "writing": ("document_writing",),
    "coding": ("code_writing",),
}


def _normalize_runtime_name(name: str) -> str:
    return str(name or "").strip().lower()


def _extract_required_capabilities(required_capabilities: list[Any]) -> set[str]:
    required: set[str] = set()
    for raw in required_capabilities:
        if hasattr(raw, "name"):
            required.add(str(raw.name).strip().lower())
        elif isinstance(raw, str):
            required.add(raw.strip().lower())
    return required


def select_external_runtimes(
    required_capabilities: list[Any],
    specialist_name: str = "",
    risk_level: str = "medium",
    runtime_names: list[str] | None = None,
    max_candidates: int | None = None,
) -> list[str]:
    """根据任务特征为外部 runtime 选择候选执行者。

    Returns:
        按入参顺序过滤后的 runtime 名称列表
    """
    if not runtime_names:
        return []

    requested = [_normalize_runtime_name(name) for name in runtime_names]
    requested = [name for name in requested if name]
    if not requested:
        return []

    required = _extract_required_capabilities(required_capabilities)
    specialist_key = str(specialist_name or "").strip().lower()
    risk_key = str(risk_level or "").strip().lower()
    candidates: list[str] = []
    role_hints = set(ROLE_CAPABILITY_HINTS.get(specialist_key, ()))

    # 风险高的任务默认允许更广泛地接入外部专家
    high_risk = risk_key in {"high", "critical"}

    for runtime in requested:
        hints = set(RUNTIME_CAPABILITY_HINTS.get(runtime, ()))
        if not hints:
            continue

        has_direct_match = bool(required.intersection(hints))
        has_role_match = bool(role_hints.intersection(hints))
        if has_direct_match or has_role_match or (high_risk and not required):
            candidates.append(runtime)

    if high_risk and not candidates and requested:
        candidates = requested[:]

    if max_candidates and max_candidates > 0:
        candidates = candidates[: max_candidates]

    # 去重保持稳定顺序
    deduped: list[str] = []
    for item in candidates:
        if item not in deduped:
            deduped.append(item)
    return deduped
