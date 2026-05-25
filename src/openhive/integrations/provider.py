"""LLM Provider Manager - 多提供商管理

借鉴 OpenClaw CH16-20 Provider 系统 + Failover 算法

核心特性：
- 多提供商支持：MiniMax / OpenAI / Anthropic
- 故障转移：主提供商失败时自动切换
- 负载均衡：轮询或加权随机选择
- 健康检查：定期检测提供商可用性
"""

import asyncio
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProviderStatus(Enum):
    """提供商状态"""

    HEALTHY = "healthy"  # 健康
    DEGRADED = "degraded"  # 降级（部分失败）
    UNHEALTHY = "unhealthy"  # 不可用


@dataclass
class ProviderConfig:
    """提供商配置"""

    name: str
    provider_type: str  # "minimax", "openai", "anthropic"
    api_key: str
    base_url: str = ""
    model: str = "default"
    max_tokens: int = 8192
    temperature: float = 0.7
    weight: float = 1.0  # 负载均衡权重


@dataclass
class ProviderMetrics:
    """提供商指标"""

    total_requests: int = 0
    failed_requests: int = 0
    total_latency: float = 0.0
    last_success: float | None = None  # 上次成功时间
    last_failure: float | None = None  # 上次失败时间
    consecutive_failures: int = 0

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0
        return 1.0 - (self.failed_requests / self.total_requests)

    @property
    def average_latency(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_latency / self.total_requests

    @property
    def status(self) -> ProviderStatus:
        if self.consecutive_failures >= 5:
            return ProviderStatus.UNHEALTHY
        elif self.consecutive_failures >= 2 or self.success_rate < 0.8:
            return ProviderStatus.DEGRADED
        return ProviderStatus.HEALTHY


class LLMProvider(ABC):
    """LLM 提供商抽象接口"""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """发送补全请求"""
        pass

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """获取文本嵌入"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        pass


class LLMProviderManager:
    """LLM 提供商管理器

    支持：
    - 多提供商注册
    - 自动故障转移
    - 负载均衡（加权轮询）
    - 熔断器模式
    """

    def __init__(self):
        self._providers: dict[str, LLMProvider] = {}
        self._configs: dict[str, ProviderConfig] = {}
        self._metrics: dict[str, ProviderMetrics] = {}
        self._healthy_providers: list[str] = []  # 可用提供商列表
        self._current_index: int = 0  # 轮询索引
        self._lock = asyncio.Lock()

    def register_provider(self, config: ProviderConfig, provider: LLMProvider) -> None:
        """注册提供商"""
        self._providers[config.name] = provider
        self._configs[config.name] = config
        self._metrics[config.name] = ProviderMetrics()
        self._update_healthy_list()

    def get_provider(self, name: str) -> LLMProvider | None:
        """获取指定提供商"""
        return self._providers.get(name)

    def list_providers(self) -> list[str]:
        """列出所有提供商"""
        return list(self._providers.keys())

    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        preferred_provider: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """发送请求，自动故障转移

        Args:
            prompt: 提示词
            system_prompt: 系统提示词
            preferred_provider: 首选提供商（尝试优先）
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            生成的文本
        """
        async with self._lock:
            candidates = self._get_candidate_providers(preferred_provider)

            if not candidates:
                raise RuntimeError("没有可用的 LLM 提供商")

            last_error = None
            for provider_name in candidates:
                provider = self._providers[provider_name]
                metrics = self._metrics[provider_name]

                try:
                    import time
                    start = time.time()

                    result = await provider.complete(
                        prompt=prompt,
                        system_prompt=system_prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )

                    # 记录成功
                    latency = time.time() - start
                    metrics.total_requests += 1
                    metrics.failed_requests = max(0, metrics.failed_requests - 1)  # 成功减1
                    metrics.consecutive_failures = 0
                    metrics.total_latency += latency
                    metrics.last_success = time.time()

                    self._update_healthy_list()
                    return result

                except Exception as e:
                    last_error = e
                    metrics.total_requests += 1
                    metrics.failed_requests += 1
                    metrics.consecutive_failures += 1
                    metrics.last_failure = asyncio.get_event_loop().time()

                    # 熔断：连续失败超过阈值
                    if metrics.consecutive_failures >= 5:
                        self._update_healthy_list()
                    continue

            raise RuntimeError(f"所有提供商都失败: {last_error}")

    def _get_candidate_providers(self, preferred: str | None = None) -> list[str]:
        """获取候选提供商列表（按优先级排序）"""
        if not self._healthy_providers:
            return list(self._providers.keys())

        if preferred and preferred in self._healthy_providers:
            # 优先使用指定的
            candidates = [preferred]
            candidates.extend(p for p in self._healthy_providers if p != preferred)
            return candidates

        return self._healthy_providers.copy()

    def _update_healthy_list(self) -> None:
        """更新可用提供商列表"""
        self._healthy_providers = [
            name
            for name, metrics in self._metrics.items()
            if metrics.status != ProviderStatus.UNHEALTHY
        ]

    def get_metrics(self, provider_name: str) -> ProviderMetrics | None:
        """获取提供商指标"""
        return self._metrics.get(provider_name)

    def get_best_provider(self) -> str | None:
        """获取最优提供商（最高成功率 + 最低延迟）"""
        if not self._healthy_providers:
            return None

        best = None
        best_score = -1.0

        for name in self._healthy_providers:
            metrics = self._metrics[name]
            config = self._configs[name]

            # 综合评分：成功率 × 权重 - 归一化延迟
            success_score = metrics.success_rate
            latency_penalty = metrics.average_latency / 10.0  # 归一化
            score = success_score * config.weight - latency_penalty

            if score > best_score:
                best_score = score
                best = name

        return best

    async def health_check_all(self) -> dict[str, bool]:
        """对所有提供商执行健康检查"""
        results = {}
        for name, provider in self._providers.items():
            try:
                is_healthy = await provider.health_check()
                results[name] = is_healthy
                if is_healthy:
                    self._metrics[name].consecutive_failures = 0
                else:
                    self._metrics[name].consecutive_failures += 1
            except Exception:
                results[name] = False
                self._metrics[name].consecutive_failures += 1

        self._update_healthy_list()
        return results


# 全局提供商管理器
_global_manager: LLMProviderManager | None = None


def get_provider_manager() -> LLMProviderManager:
    """获取全局提供商管理器"""
    global _global_manager
    if _global_manager is None:
        _global_manager = LLMProviderManager()
    return _global_manager


def register_default_providers(configs: list[ProviderConfig]) -> None:
    """注册默认提供商"""
    from openhive.integrations.llm import MiniMaxClient

    manager = get_provider_manager()

    for config in configs:
        if config.provider_type == "minimax":
            provider = MiniMaxClient(
                api_key=config.api_key,
                base_url=config.base_url or "https://api.minimax.chat/v1",
                model=config.model,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
            )
            manager.register_provider(config, provider)


# 导出
__all__ = [
    "LLMProvider",
    "LLMProviderManager",
    "ProviderConfig",
    "ProviderMetrics",
    "ProviderStatus",
    "get_provider_manager",
    "register_default_providers",
]