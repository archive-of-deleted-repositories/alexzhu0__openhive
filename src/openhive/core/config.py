"""配置管理 - 从 YAML 文件加载配置"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    """PostgreSQL 数据库配置"""

    host: str = "localhost"
    port: int = 5432
    database: str = "openhive"
    user: str = "postgres"
    password: str = ""


class RedisConfig(BaseModel):
    """Redis 配置"""

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None


class LLMConfig(BaseModel):
    """LLM 提供商配置（MiniMax）"""

    provider: str = "minimax"
    api_key: str = ""
    base_url: str = "https://api.minimaxi.com/anthropic/v1"  # Anthropic 兼容 API
    model: str = "MiniMax-M2.7-highspeed"
    max_tokens: int = 8192
    temperature: float = 0.7


class SwarmPolicyConfig(BaseModel):
    """企业蜂群策略配置"""

    name: str = "enterprise-default"
    parallelism: int = 2
    redundancy: int = 1
    candidate_count: int = 2
    high_risk_threshold: str = "high"
    min_result_chars: int = 120
    audit_enabled: bool = True
    scorer_length_weight: float = 0.55
    scorer_evidence_weight: float = 0.30
    scorer_structure_weight: float = 0.15
    scorer_length_target_factor: float = 2.0
    scorer_duplicate_similarity_threshold: float = 0.92
    winner_confidence_threshold: float = 0.75
    max_retry_rounds: int = 0
    retry_on_low_confidence: bool = True
    scorer_evidence_fields: list[str] = Field(
        default_factory=lambda: [
            "content",
            "findings",
            "insights",
            "analysis",
            "evidence",
            "sources",
            "links",
            "recommendations",
            "conclusion",
            "summary",
        ]
    )


class OACPRuntimeConfig(BaseModel):
    """企业蜂群外部 runtime 集成配置"""

    enabled: bool = False
    hub_url: str = "ws://localhost:9090/ws"
    connect_timeout_seconds: float = 10.0
    request_timeout_seconds: float = 120.0
    runtimes: list[str] = Field(default_factory=lambda: ["openclaw", "hermes"])


class EnterpriseConfig(BaseModel):
    """企业维度的运行时策略配置"""

    policy: SwarmPolicyConfig = Field(default_factory=SwarmPolicyConfig)
    department_pricing: dict[str, float] = Field(default_factory=dict)
    runtime_bridge: OACPRuntimeConfig = Field(default_factory=OACPRuntimeConfig)


class AgentConfig(BaseModel):
    """Agent 默认配置"""

    name: str
    role: str = "specialist"
    description: str = ""
    max_iterations: int = 10
    timeout_seconds: int = 300


class TeamConfig(BaseModel):
    """团队配置"""

    name: str
    description: str = ""
    agents: list[AgentConfig] = Field(default_factory=list)
    enterprise: EnterpriseConfig = Field(default_factory=EnterpriseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)


def load_config(config_path: str | Path) -> TeamConfig:
    """从 YAML 文件加载团队配置"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return TeamConfig(**data)


def save_config(config: TeamConfig, config_path: str | Path) -> None:
    """保存团队配置到 YAML 文件"""
    path = Path(config_path)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config.model_dump(), f, allow_unicode=True, sort_keys=False)
