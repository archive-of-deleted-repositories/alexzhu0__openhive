"""MiniMax LLM 客户端

支持两种 API 风格:
1. OpenAI 风格: /chat/completions (旧版 MiniMax-Text-01)
2. Anthropic 风格: /messages (新版 MiniMax-M2.7)
"""

from typing import Any

import httpx

from openhive.integrations.provider import LLMProvider


class MiniMaxClient(LLMProvider):
    """MiniMax API 客户端

    自动检测 API 风格:
    - 如果 base_url 包含 /anthropic/，使用 Anthropic 风格 /messages 接口
    - 否则使用 OpenAI 风格 /chat/completions 接口
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.minimaxi.com/anthropic/v1",
        model: str = "MiniMax-M2.7-highspeed",
        max_tokens: int = 8192,
        temperature: float = 0.7,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = httpx.AsyncClient(timeout=120.0)

        # 检测 API 风格
        self._is_anthropic = "/anthropic/" in base_url.lower()

    async def close(self) -> None:
        """关闭客户端"""
        await self._client.aclose()

    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """发送补全请求"""
        if self._is_anthropic:
            return await self._complete_anthropic(prompt, system_prompt, temperature, max_tokens)
        else:
            return await self._complete_openai(prompt, system_prompt, temperature, max_tokens)

    async def _complete_anthropic(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Anthropic 风格请求"""
        messages = []
        if system_prompt:
            messages.append({"role": "user", "content": f"[System] {system_prompt}"})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
        }

        response = await self._client.post(
            f"{self.base_url}/messages",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()

        data = response.json()
        # 解析 Anthropic 格式的响应
        # content 是数组，通常 [0] 是 thinking，[1] 是 text
        content = data.get("content", [])
        for item in content:
            if item.get("type") == "text":
                return item.get("text", "")

        # Fallback: 直接返回第一个 text 类型
        return content[0].get("text", str(content)) if content else ""

    async def _complete_openai(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """OpenAI 风格请求"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        response = await self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def embed(
        self,
        text: str,
    ) -> list[float]:
        """获取文本嵌入向量"""
        # MiniMax 嵌入 API
        payload = {
            "model": "embo-01",
            "text": text,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            # 尝试使用嵌入 API
            embed_url = self.base_url.replace("/anthropic/v1", "/embeddings")
            response = await self._client.post(
                f"{embed_url}/embeddings",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]
        except Exception:
            # Fallback：返回零向量
            return [0.0] * 1536

    async def health_check(self) -> bool:
        """健康检查"""
        try:
            test_prompt = "ping"
            response = await self.complete(
                prompt=test_prompt,
                max_tokens=10,
            )
            return len(response) > 0
        except Exception:
            return False
