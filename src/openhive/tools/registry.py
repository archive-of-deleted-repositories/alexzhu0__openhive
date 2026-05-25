"""Tool Registry - 工具注册表

管理所有注册的工具，提供工具查询和可用性判断
"""

from typing import Any

from openhive.tools.descriptor import ToolDescriptor, CoreTools


class ToolRegistry:
    """工具注册表 - 管理所有工具"""

    def __init__(self):
        self._tools: dict[str, ToolDescriptor] = {}

    def register(self, tool: ToolDescriptor) -> None:
        """注册工具"""
        is_valid, errors = tool.validate()
        if not is_valid:
            raise ValueError(f"工具验证失败: {errors}")

        if tool.name in self._tools:
            raise ValueError(f"工具已存在: {tool.name}")

        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDescriptor | None:
        """获取工具"""
        return self._tools.get(name)

    def list_all(self) -> list[ToolDescriptor]:
        """列出所有工具"""
        return list(self._tools.values())

    def list_available(self) -> list[ToolDescriptor]:
        """列出所有可用工具"""
        return [
            t
            for t in self._tools.values()
            if t.availability.value != "unavailable"
        ]

    def find_by_owner(self, owner_kind: str, plugin_id: str | None = None) -> list[ToolDescriptor]:
        """查找特定所有者的工具"""
        return [
            t
            for t in self._tools.values()
            if t.owner and t.owner.kind.value == owner_kind
            and (plugin_id is None or t.owner.plugin_id == plugin_id)
        ]

    def unregister(self, name: str) -> bool:
        """取消注册工具"""
        if name in self._tools:
            del self._tools[name]
            return True
        return False


# 全局注册表实例
_global_registry: ToolRegistry | None = None


def get_global_tool_registry() -> ToolRegistry:
    """获取全局工具注册表"""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
        register_default_tools(_global_registry)
    return _global_registry


def register_default_tools(registry: ToolRegistry) -> None:
    """注册默认工具集"""
    registry.register(CoreTools.web_search())
    registry.register(CoreTools.read_file())
    registry.register(CoreTools.write_file())
    registry.register(CoreTools.bash())
