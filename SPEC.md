# OpenHive - 多智能体协作框架设计草案

> Historical Chinese design draft. The canonical public-facing documentation is `README.md`.

## 1. 项目概述

**Slogan**: 「一群 AI，比一个 AI 更聪明」

**一句话定位**: 开源的多智能体协作框架，通过团队自动组建、共享记忆图谱、任务分解编排，让多个专业化 AI Agent 协同完成复杂任务。

**核心问题**: 前三代（OpenClaw/Hermes/OpenHuman）解决了「单 Agent 能力」问题，但**没有解决「多 Agent 协作 + 记忆共享 + 技能进化」问题。

---

## 2. 核心价值主张

### 2.1 从「一个 Agent」到「一个团队」

| 维度 | 前三代 | OpenHive |
|------|--------|----------|
| Agent 数量 | 1 | N（动态组队） |
| 记忆 | 私有 memory | **团队共享知识图谱** |
| 协作方式 | 无 | **任务分解 + 结果汇总** |
| 决策链 | Agent → 工具 | **Orchestrator → Specialist → Human** |
| 技能 | 固定 | **技能可声明、可进化** |
| 工具扩展 | 硬编码 | **Tool Descriptor 契约体系** |

### 2.2 四大核心创新

#### 1. 团队自动组建（Team Auto-Assembly）

```
用户: "分析电动车市场"
       ↓
Orchestrator 解析目标 → 识别能力需求 [research, analysis, writing]
       ↓
匹配可用 Specialist → 能力评分排序
       ↓
组建团队 → 分配任务 → 执行
```

**借鉴**: OpenClaw 的 Capability Matching + Subagent spawn 机制

#### 2. 共享记忆图谱（Shared Memory Graph）

团队共享知识图谱，**不是每个 Agent 私有记忆**。

**架构设计**（借鉴 OpenClaw CH26）:
```
短时记忆（会话）→ 长时记忆（向量搜索）→ 梦境整理（主动巩固）
```

**核心特性**:
- 混合搜索：向量相似度 × 0.7 + 全文搜索 × 0.3
- MMR（最大边际相关性）：避免重复，增加多样性
- 时间衰减：越老的记忆评分越低
- 梦境机制：定期整理，将有价值记忆晋升到持久化存储

#### 3. 技能契约系统（Skill Contract System）

**借鉴**: OpenClaw 的 ToolDescriptor + Hermes 的 SKILL.md 进化

每个 Specialist 声明自己的能力：

```yaml
specialist:
  name: research
  capabilities:
    - web_search
    - data_analysis
    - document_parsing
  max_concurrent_tasks: 2
  preferred_model: MiniMax
  skill_description: |
    # 研究专家

    ## 何时使用
    当用户需要调研、分析主题背景时调用。

    ## 操作流程
    1. 确定研究范围
    2. 收集信息源
    3. 整理关键发现
```

**技能进化**（借鉴 Hermes 自我进化系统）:
- 约束验证：技能必须满足字符限制、格式要求
- 适应度评分：正确性 × 0.4 + 流程遵循 × 0.3 + 简洁性 × 0.3
- GEPA 进化：基于反馈自动优化技能描述

#### 4. 任务分解编排（Task Decomposition & Orchestration）

**借鉴**: OpenClaw CH06 双层队列 + CH08 子智能体深度限制

```
用户目标
    ↓
Orchestrator 分解任务
    ↓
┌─────────────────────────────────────┐
│         任务队列（双层）              │
│  Session 层：同任务串行               │
│  Global 层：跨任务协调               │
└─────────────────────────────────────┘
    ↓
Specialist A ──┬── Specialist B
    ↑              ↑                     
    └────── 共享记忆 ───────┘
```

---

## 3. 技术架构

### 3.1 系统架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                         OpenHive Core                            │
├────────────────┬────────────────┬────────────────┬──────────────┤
│ Team Assembler │ Memory Graph   │ Task Queue    │ Skill Engine │
│                │ (混合搜索+MMR) │ (双层队列)    │ (契约+进化) │
├────────────────┴────────────────┴────────────────┴──────────────┤
│                     Shared Memory Graph                          │
│     In-Memory (默认) / PostgreSQL + pgvector (可选)            │
├──────────────────────────────────────────────────────────────────┤
│                      Agent Runtime                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Orchestrator │→ │ Specialist A │  │ Specialist B │     │
│  │              │  │ (能力契约)   │  │ (能力契约)   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
├──────────────────────────────────────────────────────────────────┤
│                     Tool Executor Layer                           │
│         (Bash / WebSearch / FileSystem / MCP)                  │
├──────────────────────────────────────────────────────────────────┤
│                    CLI / WebSocket / Tauri                       │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 技术栈

```
核心语言:    Python 3.10+ + TypeScript (Web UI)
Agent 框架:  自研（借鉴 OpenClaw pi-embedded-runner）
记忆/图谱:   PostgreSQL 17 + pgvector（可选）
              JSON 文件持久化（默认，无需 Docker）
实时通信:    asyncio.Queue（默认）/ Redis Pub/Sub（可选）
LLM:        MiniMax / OpenAI / Anthropic（多提供商支持）
技能进化:    DSPy + GEPA（借鉴 Hermes 自我进化系统）
许可证:     Apache-2.0
```

---

## 4. 核心模块设计

### 4.1 Team Assembler（团队自动组建）

**职责**: 根据用户目标，动态组建最合适的 Agent 团队

**流程**:
```
1. 解析用户目标 → 识别所需能力
2. 查询可用 Specialist → 按能力匹配度排序
3. 组建团队 → 分配角色和任务
4. 监控执行 → 汇总结果
```

**核心类型**:
```python
class TeamAssembler:
    async def assemble_team(self, goal: str) -> Team:
        """根据目标组建团队"""

    async def match_specialists(
        self,
        required_capabilities: list[Capability]
    ) -> list[tuple[Specialist, float]]:
        """匹配 Specialist，返回 (Specialist, 匹配分数)"""
```

### 4.2 Memory Graph（共享记忆图谱）

**借鉴**: OpenClaw CH26 混合搜索 + Hermes 梦境机制

**核心类型**:
```python
class MemoryNode:
    id: UUID
    type: str  # "fact", "task", "result", "dream"
    content: str
    embedding: list[float] | None  # 向量
    metadata: dict[str, Any]
    agent_id: UUID
    team_id: UUID
    created_at: datetime
    # 元信息
    relevance_score: float  # 混合搜索评分
    access_count: int  # 访问次数（用于重要性判断）
    last_accessed: datetime

class MemoryGraph:
    async def search(
        self,
        query: str,
        team_id: UUID,
        hybrid: bool = True,  # 向量 + 全文混合
        mmr: bool = True,  # 最大边际相关性
        temporal_decay: bool = True,  # 时间衰减
    ) -> list[MemoryNode]: ...

    async def dreaming(self) -> None:
        """梦境整理：定期将短期记忆晋升到长期"""
```

### 4.3 Task Queue（任务队列）

**借鉴**: OpenClaw CH06 双层队列编排

```python
class TaskQueue:
    """双层任务队列"""

    async def enqueue_session(self, task: Task, session_id: UUID) -> None:
        """Session 层：同 session 内任务串行"""

    async def enqueue_global(self, task: Task) -> None:
        """Global 层：跨 session 任务协调"""

class Task:
    id: UUID
    name: str
    status: TaskStatus  # pending/running/done/failed
    priority: TaskPriority
    assigned_agent_id: UUID | None
    parent_id: UUID | None  # 父任务（任务分解树）
    result: dict[str, Any] | None
```

### 4.4 Skill Engine（技能契约 + 进化）

**借鉴**: OpenClaw ToolDescriptor + Hermes 技能进化

**核心类型**:
```python
class SkillContract:
    """技能契约 - Specialist 的能力声明"""

    name: str
    description: str  # 人类可读描述
    capabilities: list[str]  # 能力列表
    input_schema: dict  # JSON Schema
    output_schema: dict
    constraints: SkillConstraints  # 硬限制
    fitness_weights: FitnessWeights  # 软优化权重

class SkillConstraints:
    """技能硬限制（零容忍）"""
    max_chars: int = 15000
    required_sections: list[str] = []
   禁止_patterns: list[str] = []

class FitnessWeights:
    """适应度权重（软优化）"""
    correctness: float = 0.4
    procedure_following: float = 0.3
    conciseness: float = 0.3

class SkillEvolver:
    """技能进化器 - 借鉴 Hermes GEPA"""

    async def evolve(
        self,
        skill: SkillContract,
        evaluation_dataset: list[EvalCase],
        iterations: int = 10,
    ) -> SkillContract:
        """进化技能，返回优化后的版本"""
```

### 4.5 LLM Provider（多提供商支持）

**借鉴**: OpenClaw CH16-20 Provider 系统 + Failover 算法

```python
class LLMProvider:
    """LLM 提供商接口"""

    async def complete(
        self,
        prompt: str,
        model: str | None = None,
    ) -> str: ...

    async def embed(self, text: str) -> list[float]: ...

class MiniMaxProvider(LLMProvider): ...
class OpenAIProvider(LLMProvider): ...
class AnthropicProvider(LLMProvider): ...

class ProviderManager:
    """多提供商管理 + Failover"""

    def __init__(self):
        self.providers: dict[str, LLMProvider] = {}
        self.fallback_chain: list[str] = []

    async def complete_with_failover(
        self,
        prompt: str,
        preferred: str | None = None,
    ) -> str:
        """Failover：主提供商失败自动切换到备用"""
```

---

## 5. Agent 系统设计

### 5.1 Agent 类型

| 类型 | 职责 | 关键特性 |
|------|------|---------|
| `Orchestrator` | 目标分解、团队协调 | 任务分解引擎、结果汇总 |
| `Specialist` | 执行特定领域任务 | 能力契约、工具集 |
| `Human` | 审批关键决策 | 确认点机制 |

### 5.2 Specialist 能力契约示例

```yaml
# research_specialist.yaml
name: research
role: specialist
description: 研究专家 - 擅长信息收集和分析

capabilities:
  - web_search
  - document_parsing
  - data_analysis

tools:
  - name: web_search
    description: 搜索互联网获取信息
  - name: read_file
    description: 读取本地文件

constraints:
  max_concurrent_tasks: 2
  timeout_seconds: 300

preferred_models:
  - MiniMax-Text-01
  - gpt-4o-mini
```

### 5.3 任务分解流程

```
用户目标: "分析电动车市场竞争格局"

1. Orchestrator 接收目标
2. 调用 LLM 分解任务:
   [
     {
       "name": "research_market",
       "description": "调研市场规模和主要玩家",
       "specialist": "research",
       "capabilities_needed": ["web_search", "data_analysis"]
     },
     {
       "name": "analyze_competitors",
       "description": "分析比亚迪、特斯拉等竞争对手",
       "specialist": "analysis",
       "capabilities_needed": ["data_analysis"]
     }
   ]

3. Team Assembler 匹配 Specialist
   - research → research_specialist (100% 匹配)
   - analysis → analysis_specialist (100% 匹配)

4. 并行执行子任务
   - research_specialist 执行 "research_market"
   - analysis_specialist 执行 "analyze_competitors"

5. Orchestrator 汇总结果
6. Human 审批（如配置了确认点）
```

---

## 6. 目录结构

```
openhive/
├── src/openhive/
│   ├── __init__.py
│   ├── core/                    # 核心模块
│   │   ├── __init__.py
│   │   ├── config.py           # YAML 配置加载
│   │   ├── team.py             # Team / Agent 模型
│   │   ├── memory.py           # 记忆图谱（混合搜索）
│   │   ├── message.py          # 消息总线
│   │   ├── task.py            # 任务队列（双层）
│   │   └── assembler.py        # 团队自动组建
│   ├── agent/                  # Agent 实现
│   │   ├── __init__.py
│   │   ├── base.py            # BaseAgent（状态机）
│   │   ├── orchestrator.py    # Orchestrator Agent
│   │   ├── specialist.py      # Specialist Agent
│   │   └── human.py           # Human Agent（审批）
│   ├── skills/                # 技能系统
│   │   ├── __init__.py
│   │   ├── contract.py        # SkillContract 定义
│   │   ├── registry.py        # 技能注册表
│   │   └── evolver.py         # 技能进化（GEPA）
│   ├── tools/                 # 工具系统
│   │   ├── __init__.py
│   │   ├── descriptor.py       # ToolDescriptor
│   │   ├── executor.py         # 工具执行器
│   │   ├── availability.py     # 可用性判断
│   │   └── registry.py         # 工具注册表
│   ├── llm/                   # LLM 提供商
│   │   ├── __init__.py
│   │   ├── base.py            # Provider 接口
│   │   ├── minimax.py         # MiniMax
│   │   ├── openai.py          # OpenAI
│   │   ├── anthropic.py       # Anthropic
│   │   └── manager.py         # 提供商管理 + Failover
│   ├── integrations/          # 第三方集成
│   │   └── llm.py
│   └── cli/                   # CLI
│       ├── __init__.py
│       └── main.py
├── tests/
│   ├── unit/
│   └── integration/
├── skills/                    # 内置技能库
│   ├── research.yaml
│   ├── analysis.yaml
│   └── writing.yaml
├── pyproject.toml
├── SPEC.md
└── README.md
```

---

## 7. 已确认决策

- **LLM 提供商**: MiniMax（默认）+ 多提供商 Failover
- **Redis 依赖**: 可选（默认用 asyncio.Queue）
- **PostgreSQL 依赖**: 可选（默认用 JSON 文件持久化）
- **团队配置格式**: YAML
- **授权协议**: Apache-2.0
- **目标用户**: 与 OpenClaw/Hermes/OpenHuman 相同

---

## 8. 开发路线图

### v0.1.0（已完成）
- [x] 团队创建和配置
- [x] Orchestrator 任务分解
- [x] Specialist Agent 执行
- [x] 共享记忆写入（基础）
- [x] CLI 基本命令

### v0.2.0（设计参考）
- [x] 能力契约系统（SkillContract）
- [x] 团队自动组建（Team Assembler）
- [x] 记忆图谱增强（混合搜索 + MMR）
- [x] 双层任务队列
- [x] CLI 增强（任务监控）

### v0.3.0
- [ ] 技能进化系统（GEPA）
- [ ] Human Agent 审批流程
- [ ] 多提供商 Failover
- [ ] Web UI 界面

### v0.4.0
- [ ] MCP 工具集成
- [ ] Docker 部署支持
- [ ] 多团队管理
