"""Enterprise Swarm - 企业级蜂群编排规则与审计"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any


RISK_ORDER = ["low", "medium", "high", "critical"]


DEFAULT_EVIDENCE_FIELDS = (
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
)


def normalize_risk_level(risk_level: str) -> str:
    """将风险等级标准化到已知集合"""
    if not risk_level:
        return "medium"
    level = risk_level.strip().lower()
    if level in ("critical", "high", "medium", "low"):
        return level
    return "medium"


def _risk_rank(level: str) -> int:
    try:
        return RISK_ORDER.index(normalize_risk_level(level))
    except ValueError:
        return RISK_ORDER.index("medium")


@dataclass
class SwarmExecutionPolicy:
    """企业级蜂群执行策略"""

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
    scorer_evidence_fields: tuple[str, ...] = field(default_factory=lambda: DEFAULT_EVIDENCE_FIELDS)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "SwarmExecutionPolicy":
        if not data:
            return cls()
        return cls(
            name=data.get("name", cls.name),
            parallelism=cls._parse_positive_int(data.get("parallelism"), cls.parallelism),
            redundancy=cls._parse_positive_int(data.get("redundancy"), cls.redundancy),
            candidate_count=cls._parse_positive_int(
                data.get("candidate_count"), cls.candidate_count
            ),
            high_risk_threshold=normalize_risk_level(
                data.get("high_risk_threshold", cls.high_risk_threshold)
            ),
            min_result_chars=cls._parse_positive_int(
                data.get("min_result_chars"), cls.min_result_chars
            ),
            audit_enabled=bool(data.get("audit_enabled", cls.audit_enabled)),
            scorer_length_weight=cls._parse_positive_float(
                data.get("scorer_length_weight"),
                cls.scorer_length_weight,
            ),
            scorer_evidence_weight=cls._parse_positive_float(
                data.get("scorer_evidence_weight"),
                cls.scorer_evidence_weight,
            ),
            scorer_structure_weight=cls._parse_positive_float(
                data.get("scorer_structure_weight"),
                cls.scorer_structure_weight,
            ),
            scorer_length_target_factor=cls._parse_positive_float(
                data.get("scorer_length_target_factor"),
                cls.scorer_length_target_factor,
                min_value=0.1,
            ),
            scorer_duplicate_similarity_threshold=cls._parse_positive_float(
                data.get("scorer_duplicate_similarity_threshold"),
                cls.scorer_duplicate_similarity_threshold,
                min_value=0.0,
                max_value=1.0,
            ),
            winner_confidence_threshold=cls._parse_positive_float(
                data.get("winner_confidence_threshold"),
                cls.winner_confidence_threshold,
                min_value=0.0,
                max_value=1.0,
            ),
            max_retry_rounds=cls._parse_positive_int(
                data.get("max_retry_rounds"),
                cls.max_retry_rounds,
                min_value=0,
            ),
            retry_on_low_confidence=bool(
                data.get("retry_on_low_confidence", cls.retry_on_low_confidence)
            ),
            scorer_evidence_fields=cls._parse_evidence_fields(
                data.get("scorer_evidence_fields", DEFAULT_EVIDENCE_FIELDS),
                DEFAULT_EVIDENCE_FIELDS,
            ),
        )

    @property
    def requires_redundancy(self) -> bool:
        """高风险任务是否需要冗余执行"""
        return self._requires_redundancy_for_risk("high")

    def requires_redundancy_for(self, risk_level: str) -> bool:
        """给定风险等级是否应启用冗余执行"""
        return self._requires_redundancy_for_risk(risk_level)

    def _requires_redundancy_for_risk(self, risk_level: str) -> bool:
        return _risk_rank(risk_level) >= _risk_rank(self.high_risk_threshold)

    def should_retry(self, decision: Any, risk_level: str) -> bool:
        """根据决策与风险级别判断是否需要重试"""
        if self.max_retry_rounds <= 0:
            return False
        if not self._requires_redundancy_for_risk(risk_level):
            return False
        if not decision:
            return False

        if not decision.chosen:
            return True
        if not self.retry_on_low_confidence:
            return False
        return decision.winner_confidence < self.winner_confidence_threshold

    def responders(self, primary: str, candidates: list[str] | None, risk_level: str) -> list[str]:
        """返回本任务建议的执行者列表"""
        responders = [primary]
        risk_level = normalize_risk_level(risk_level)

        if self.redundancy > 1 and self._requires_redundancy_for_risk(risk_level):
            if not candidates:
                return responders
            for name in candidates[: self.redundancy - 1]:
                if name != primary and name not in responders:
                    responders.append(name)
        return responders[: self.redundancy]

    def to_dict(self) -> dict[str, Any]:
        """用于记忆落库/审计的数据表示"""
        return {
            "name": self.name,
            "parallelism": self.parallelism,
            "redundancy": self.redundancy,
            "candidate_count": self.candidate_count,
            "high_risk_threshold": self.high_risk_threshold,
            "min_result_chars": self.min_result_chars,
            "audit_enabled": self.audit_enabled,
            "scorer_length_weight": self.scorer_length_weight,
            "scorer_evidence_weight": self.scorer_evidence_weight,
            "scorer_structure_weight": self.scorer_structure_weight,
            "scorer_length_target_factor": self.scorer_length_target_factor,
            "scorer_duplicate_similarity_threshold": self.scorer_duplicate_similarity_threshold,
            "winner_confidence_threshold": self.winner_confidence_threshold,
            "max_retry_rounds": self.max_retry_rounds,
            "retry_on_low_confidence": self.retry_on_low_confidence,
            "scorer_evidence_fields": list(self.scorer_evidence_fields),
        }

    @staticmethod
    def _parse_positive_float(
        value: Any,
        default: float,
        min_value: float = 0.0,
        max_value: float | None = None,
    ) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if parsed < min_value:
            return default
        if max_value is not None and parsed > max_value:
            return max_value
        return parsed

    @staticmethod
    def _parse_positive_int(value: Any, default: int, min_value: int = 1) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed >= min_value else default

    @staticmethod
    def _parse_evidence_fields(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
        if isinstance(value, str):
            return tuple(
                field.strip()
                for field in value.split(",")
                if field and field.strip()
            )
        if isinstance(value, (list, tuple)):
            return tuple(
                str(field).strip()
                for field in value
                if isinstance(field, (str, int, float, bool)) and str(field).strip()
            )
        return default


@dataclass
class SwarmDecision:
    """任务决策记录（用于审计）"""

    task_name: str
    chosen: str
    responders: list[str] = field(default_factory=list)
    winner_confidence: float = 0.0
    risk_level: str = "medium"
    notes: list[str] = field(default_factory=list)
    routing_notes: list[str] = field(default_factory=list)
    attempts: int = 1
    retry_reason: str | None = None


@dataclass
class SwarmResponseQuality:
    """外部/内部执行结果的仲裁得分"""

    total: float
    length_score: float
    evidence_score: float
    structure_score: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class SwarmResponseScorer:
    """多源执行结果仲裁评分器（可复用）"""

    min_result_chars: int = 120
    evidence_fields: tuple[str, ...] = field(default_factory=lambda: DEFAULT_EVIDENCE_FIELDS)
    length_target_factor: float = 2.0
    duplicate_similarity_threshold: float = 0.92
    max_signature_chars: int = 220
    length_weight: float = 0.55
    evidence_weight: float = 0.30
    structure_weight: float = 0.15

    def evaluate(self, response_item: dict[str, Any]) -> SwarmResponseQuality:
        text = self.extract_result_text(response_item)
        payload = self._response_payload(response_item)
        weight_total = self.length_weight + self.evidence_weight + self.structure_weight
        if weight_total <= 0:
            weight_total = 1.0
            normalized_length_weight = 1.0
            normalized_evidence_weight = 0.0
            normalized_structure_weight = 0.0
        else:
            normalized_length_weight = self.length_weight / weight_total
            normalized_evidence_weight = self.evidence_weight / weight_total
            normalized_structure_weight = self.structure_weight / weight_total

        length_score = min(
            1.0,
            len(text) / max(self.min_result_chars * self.length_target_factor, 1.0),
        )

        evidence_hits = 0
        for field_name in self.evidence_fields:
            if self._is_non_empty(payload.get(field_name)):
                evidence_hits += 1
        evidence_denominator = len(self.evidence_fields)
        evidence_score = evidence_hits / evidence_denominator if evidence_denominator > 0 else 0.0

        structure_score = 0.0
        if isinstance(payload, dict) and payload:
            structure_score = min(
                1.0,
                len(payload.keys()) / max(3, len(self.evidence_fields) / 2),
            )

        reasons = [
            f"长度得分={length_score:.2f}",
            f"证据字段命中={evidence_hits}",
            f"结构字段数={len(payload) if isinstance(payload, dict) else 0}",
        ]

        total = (
            normalized_length_weight * length_score
            + normalized_evidence_weight * evidence_score
            + normalized_structure_weight * structure_score
        )
        return SwarmResponseQuality(
            total=round(total, 3),
            length_score=round(length_score, 3),
            evidence_score=round(evidence_score, 3),
            structure_score=round(structure_score, 3),
            reasons=reasons,
        )

    def response_signature(self, response_item: dict[str, Any]) -> str:
        """用于去重的结果签名（归一化文本）"""
        text = self.extract_result_text(response_item)
        normalized = text.strip().lower()
        normalized = re.sub(r"\s+", "", normalized)
        normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", normalized)
        return normalized[: self.max_signature_chars]

    def is_duplicate(self, left_signature: str, right_signature: str) -> bool:
        if not left_signature or not right_signature:
            return False
        if left_signature == right_signature:
            return True
        return (
            SequenceMatcher(None, left_signature, right_signature).ratio()
            >= self.duplicate_similarity_threshold
        )

    @staticmethod
    def extract_result_text(response_item: dict[str, Any]) -> str:
        payload = response_item.get("result", {})
        if not isinstance(payload, dict):
            return str(payload)

        for field in ("content", "findings", "insights", "result", "summary"):
            value = payload.get(field)
            if isinstance(value, str) and value.strip():
                return value

        if "result" in payload and isinstance(payload["result"], str):
            return payload["result"]
        return str(payload)

    @staticmethod
    def _response_payload(response_item: dict[str, Any]) -> dict[str, Any]:
        result_payload = response_item.get("result", {})
        if isinstance(result_payload, dict):
            return result_payload
        return {"result": str(result_payload)}

    @staticmethod
    def _is_non_empty(value: Any) -> bool:
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, dict, set)):
            return len(value) > 0
        return value is not None
