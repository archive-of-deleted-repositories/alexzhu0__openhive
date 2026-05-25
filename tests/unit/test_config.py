"""Unit tests for enterprise runtime bridge configuration"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openhive.cli.main import MockLLMClient, _create_llm_client
from openhive.core.config import OACPRuntimeConfig, TeamConfig, load_config
from openhive.integrations.llm import MiniMaxClient


class TestRuntimeBridgeConfig(unittest.TestCase):
    """验证企业 runtime_bridge 配置字段"""

    def test_oacp_runtime_defaults(self) -> None:
        cfg = OACPRuntimeConfig()
        assert cfg.enabled is False
        assert cfg.connect_timeout_seconds == 10.0
        assert cfg.request_timeout_seconds == 120.0

    def test_load_config_includes_connect_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "openhive.yaml"
            yaml_path.write_text(
                "name: enterprise-test\n"
                "enterprise:\n"
                "  runtime_bridge:\n"
                "    enabled: true\n"
                "    connect_timeout_seconds: 8.5\n"
                "    request_timeout_seconds: 9\n"
                "    runtimes: [hermes]\n",
                encoding="utf-8",
            )

            cfg = load_config(yaml_path)
            assert cfg.enterprise.runtime_bridge.enabled is True
            assert cfg.enterprise.runtime_bridge.connect_timeout_seconds == 8.5
            assert cfg.enterprise.runtime_bridge.request_timeout_seconds == 9
            assert cfg.enterprise.runtime_bridge.runtimes == ["hermes"]


class TestSwarmPolicyConfig:
    """验证企业蜂群策略配置可持久化与覆盖"""

    def test_swarm_policy_score_fields_have_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "openhive.yaml"
            yaml_path.write_text(
                "name: policy-default-test\n"
                "enterprise:\n"
                "  policy:\n"
                "    name: enterprise-default\n"
                "    scorer_length_weight: 0.6\n"
                "    scorer_evidence_weight: 0.25\n"
                "    scorer_structure_weight: 0.15\n"
                "    winner_confidence_threshold: 0.9\n"
                "    max_retry_rounds: 2\n"
                "    retry_on_low_confidence: false\n"
                "    scorer_evidence_fields: [content, findings]\n",
                encoding="utf-8",
            )

            cfg = load_config(yaml_path)
            policy = cfg.enterprise.policy
            assert policy.scorer_length_weight == 0.6
            assert policy.scorer_evidence_weight == 0.25
            assert policy.scorer_structure_weight == 0.15
            assert policy.winner_confidence_threshold == 0.9
            assert policy.max_retry_rounds == 2
            assert policy.retry_on_low_confidence is False
            assert policy.scorer_evidence_fields == ["content", "findings"]


class TestLLMEnvironmentFallback(unittest.TestCase):
    """Verify API keys can stay out of committed config files."""

    def test_llm_uses_mock_when_no_api_key_is_configured(self) -> None:
        with patch.dict("os.environ", {"MINIMAX_API_KEY": ""}), patch(
            "openhive.cli.main.console.print"
        ):
            client = _create_llm_client(TeamConfig(name="test"))

        assert isinstance(client, MockLLMClient)

    def test_llm_reads_provider_api_key_from_environment(self) -> None:
        with patch.dict("os.environ", {"MINIMAX_API_KEY": "test-key"}):
            client = _create_llm_client(TeamConfig(name="test"))

        assert isinstance(client, MiniMaxClient)
        assert client.api_key == "test-key"
