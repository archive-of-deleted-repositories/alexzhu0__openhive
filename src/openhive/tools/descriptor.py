"""Tool Descriptor - 工具描述符

借鉴 OpenClaw CH33 工具系统设计

核心思想：
- 工具通过描述符声明接口（名称、描述、参数模式）
- 工具的所有权和执行位置分离
- 工具可用性可配置、可判断
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class ToolOwnerKind(str, Enum):
    """工具所有者类型"""

    CORE = "core"  # 核心内置工具
    PLUGIN = "plugin"  # 插件提供的工具
    CHANNEL = "channel"  # 通道提供的工具
    MCP = "mcp"  # MCP 服务器提供的工具


class ToolExecutorKind(str, Enum):
    """工具执行器类型"""

    CORE = "core"  # 核心执行器
    PLUGIN = "plugin"  # 插件执行器
    CHANNEL = "channel"  # 通道执行器
    MCP = "mcp"  # MCP 执行器


class ToolAvailability(str, Enum):
    """工具可用性状态"""

    ALWAYS = "always"  # 始终可用
    CONFIGURABLE = "configurable"  # 可配置
    RUNTIME = "runtime"  # 运行时决定
    UNAVAILABLE = "unavailable"  # 不可用


@dataclass
class ToolOwnerRef:
    """工具所有者引用"""

    kind: ToolOwnerKind
    plugin_id: str | None = None
    channel_id: str | None = None
    server_id: str | None = None


@dataclass
class ToolExecutorRef:
    """工具执行器引用"""

    kind: ToolExecutorKind
    executor_id: str | None = None  # core 执行器 ID
    plugin_id: str | None = None  # 插件 ID
    tool_name: str | None = None  # 工具名称
    channel_id: str | None = None  # 通道 ID
    action_id: str | None = None  # 动作 ID
    server_id: str | None = None  # MCP 服务器 ID


@dataclass
class ToolDescriptor:
    """工具描述符

    借鉴 OpenClaw ToolDescriptor 设计
    """

    name: str  # 工具唯一标识
    description: str = ""  # 工具描述，供 LLM 理解用途
    title: str = ""  # 可读标题
    input_schema: dict[str, Any] = field(default_factory=dict)  # 输入参数 JSON Schema
    output_schema: dict[str, Any] = field(default_factory=dict)  # 输出结果 JSON Schema
    owner: ToolOwnerRef | None = None  # 工具所有者
    executor: ToolExecutorRef | None = None  # 执行器引用
    availability: ToolAvailability = ToolAvailability.ALWAYS  # 可用性
    availability_config: dict[str, Any] = field(default_factory=dict)  # 可用性配置
    annotations: dict[str, Any] = field(default_factory=dict)  # 额外注解
    sort_key: str = ""  # 排序键

    def validate(self) -> tuple[bool, list[str]]:
        """验证工具描述符完整性

        Returns:
            (is_valid, error_messages)
        """
        errors = []

        if not self.name:
            errors.append("工具名称不能为空")

        # 名称唯一性检查（需要 registry）
        if " " in self.name:
            errors.append("工具名称不能包含空格")

        if not self.description:
            errors.append("工具描述不能为空")

        # 如果是可见工具，必须有执行器
        if self.availability != ToolAvailability.UNAVAILABLE:
            if not self.executor:
                errors.append("可用工具必须指定执行器")

        return len(errors) == 0, errors

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "name": self.name,
            "title": self.title or self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "owner": (
                {"kind": self.owner.kind.value, "plugin_id": self.owner.plugin_id}
                if self.owner
                else None
            ),
            "executor": (
                {
                    "kind": self.executor.kind.value,
                    "executor_id": self.executor.executor_id,
                    "plugin_id": self.executor.plugin_id,
                    "tool_name": self.executor.tool_name,
                }
                if self.executor
                else None
            ),
            "availability": self.availability.value,
            "annotations": self.annotations,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolDescriptor":
        """从字典反序列化"""
        owner = None
        if data.get("owner"):
            owner = ToolOwnerRef(kind=ToolOwnerKind(data["owner"]["kind"]))

        executor = None
        if data.get("executor"):
            executor = ToolExecutorRef(kind=ToolExecutorKind(data["executor"]["kind"]))

        return cls(
            name=data["name"],
            description=data.get("description", ""),
            title=data.get("title", ""),
            input_schema=data.get("input_schema", {}),
            output_schema=data.get("output_schema", {}),
            owner=owner,
            executor=executor,
            availability=ToolAvailability(data.get("availability", "always")),
            annotations=data.get("annotations", {}),
        )


# 预定义核心工具
class CoreTools:
    """核心内置工具"""

    @staticmethod
    def web_search() -> ToolDescriptor:
        return ToolDescriptor(
            name="web_search",
            title="网络搜索",
            description="搜索互联网获取最新信息。输入查询词，返回搜索结果列表。",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询词",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回结果数",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
            owner=ToolOwnerRef(kind=ToolOwnerKind.CORE),
            executor=ToolExecutorRef(kind=ToolExecutorKind.CORE, executor_id="web_search"),
        )

    @staticmethod
    def read_file() -> ToolDescriptor:
        return ToolDescriptor(
            name="read_file",
            title="读取文件",
            description="读取本地文件内容。输入文件路径，返回文件内容。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径",
                    },
                    "encoding": {
                        "type": "string",
                        "description": "文件编码",
                        "default": "utf-8",
                    },
                },
                "required": ["path"],
            },
            owner=ToolOwnerRef(kind=ToolOwnerKind.CORE),
            executor=ToolExecutorRef(kind=ToolExecutorKind.CORE, executor_id="read_file"),
        )

    @staticmethod
    def write_file() -> ToolDescriptor:
        return ToolDescriptor(
            name="write_file",
            title="写入文件",
            description="写入内容到本地文件。输入文件路径和内容，写入文件。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "文件内容",
                    },
                },
                "required": ["path", "content"],
            },
            owner=ToolOwnerRef(kind=ToolOwnerKind.CORE),
            executor=ToolExecutorRef(kind=ToolExecutorKind.CORE, executor_id="write_file"),
        )

    @staticmethod
    def bash() -> ToolDescriptor:
        return ToolDescriptor(
            name="bash",
            title="执行命令",
            description="在终端执行 bash 命令。输入命令字符串，返回命令输出。",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的命令",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "超时时间（秒）",
                        "default": 60,
                    },
                },
                "required": ["command"],
            },
            owner=ToolOwnerRef(kind=ToolOwnerKind.CORE),
            executor=ToolExecutorRef(kind=ToolExecutorKind.CORE, executor_id="bash"),
            annotations={"dangerous": True},
        )
