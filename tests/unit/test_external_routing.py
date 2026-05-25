"""Unit tests for external runtime routing policy"""

from openhive.core.external_routing import select_external_runtimes


def test_select_external_runtimes_prefers_capability_match() -> None:
    selected = select_external_runtimes(
        required_capabilities=["document_writing", "analysis"],
        specialist_name="writing",
        risk_level="medium",
        runtime_names=["openclaw", "hermes", "openhuman"],
    )

    assert selected == ["openhuman"]


def test_select_external_runtimes_uses_specialist_hint_when_no_direct_capability() -> None:
    selected = select_external_runtimes(
        required_capabilities=["unknown_cap"],
        specialist_name="analysis",
        risk_level="medium",
        runtime_names=["openclaw", "hermes"],
    )

    assert set(selected) == {"openclaw", "hermes"}


def test_select_external_runtimes_falls_back_for_high_risk() -> None:
    selected = select_external_runtimes(
        required_capabilities=["unknown_cap"],
        specialist_name="unknown",
        risk_level="critical",
        runtime_names=["openclaw", "hermes", "openhuman"],
    )

    assert selected == ["openclaw", "hermes", "openhuman"]


def test_select_external_runtimes_no_match_returns_empty_for_low_risk() -> None:
    selected = select_external_runtimes(
        required_capabilities=["unknown_cap"],
        specialist_name="unknown",
        risk_level="low",
        runtime_names=["openclaw", "hermes", "openhuman"],
    )

    assert selected == []

