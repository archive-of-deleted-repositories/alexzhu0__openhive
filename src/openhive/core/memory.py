"""Shared Memory Graph - 共享记忆图谱

支持两种后端:
- MemoryGraphInMemory: 本地开发用（dict 存储，无持久化）
- MemoryGraphPostgres: 生产环境用（PostgreSQL + pgvector 向量搜索）

混合搜索特性（借鉴 OpenClaw CH26）:
- 向量相似度搜索 × 0.7
- 全文搜索 × 0.3
- MMR（最大边际相关性）
- 时间衰减
"""

import json
import math
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MemoryNode(BaseModel):
    """记忆节点"""

    id: UUID = Field(default_factory=uuid4)
    type: str  # e.g., "fact", "task", "result", "decision"
    content: str
    embedding: list[float] | None = None  # 向量嵌入
    metadata: dict[str, Any] = Field(default_factory=dict)
    agent_id: UUID | None = None  # 创建此记忆的 Agent
    team_id: UUID | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    links: list[UUID] = Field(default_factory=list)  # 关联的节点 ID

    # 混合搜索元信息
    relevance_score: float = 0.0  # 混合搜索评分
    access_count: int = 0  # 访问次数
    last_accessed: datetime | None = None  # 上次访问时间


class AbstractMemoryGraph(ABC):
    """记忆图谱抽象接口"""

    async def connect(self) -> None:
        """建立连接"""
        raise NotImplementedError

    async def disconnect(self) -> None:
        """关闭连接"""
        raise NotImplementedError

    async def write(self, node: MemoryNode) -> MemoryNode:
        """写入记忆节点"""
        raise NotImplementedError

    async def read(self, node_id: UUID) -> MemoryNode | None:
        """读取单个记忆节点"""
        raise NotImplementedError

    async def search(
        self,
        team_id: UUID,
        query_embedding: list[float],
        limit: int = 10,
        type_filter: str | None = None,
    ) -> list[MemoryNode]:
        """向量相似度搜索"""
        raise NotImplementedError

    async def hybrid_search(
        self,
        team_id: UUID,
        query: str,
        query_embedding: list[float] | None = None,
        limit: int = 10,
        type_filter: str | None = None,
        hybrid: bool = True,
        mmr: bool = True,
        temporal_decay: bool = True,
    ) -> list[MemoryNode]:
        """混合搜索

        Args:
            team_id: 团队 ID
            query: 文本查询
            query_embedding: 向量嵌入（可选）
            limit: 返回数量
            type_filter: 类型过滤
            hybrid: 是否使用混合搜索
            mmr: 是否使用 MMR（最大边际相关性）
            temporal_decay: 是否使用时间衰减
        """
        raise NotImplementedError

    async def query(
        self,
        team_id: UUID,
        type_filter: str | None = None,
        agent_id: UUID | None = None,
        limit: int = 100,
    ) -> list[MemoryNode]:
        """结构化查询"""
        raise NotImplementedError

    async def update(self, node: MemoryNode) -> MemoryNode:
        """更新记忆节点"""
        raise NotImplementedError

    async def delete(self, node_id: UUID) -> bool:
        """删除记忆节点"""
        raise NotImplementedError


class MemoryGraphInMemory(AbstractMemoryGraph):
    """本地开发用内存记忆图谱"""

    def __init__(self, persist_path: str | None = None):
        """
        Args:
            persist_path: 可选，JSON 文件路径用于持久化
        """
        self.persist_path = Path(persist_path) if persist_path else None
        self._nodes: dict[UUID, MemoryNode] = {}
        self._index_by_team: dict[UUID, list[UUID]] = {}  # team_id -> [node_ids]
        self._index_by_type: dict[str, list[UUID]] = {}  # type -> [node_ids]

        if self.persist_path and self.persist_path.exists():
            self._load()

    async def connect(self) -> None:
        pass  # 无需连接

    async def disconnect(self) -> None:
        if self.persist_path:
            self._save()

    async def write(self, node: MemoryNode) -> MemoryNode:
        self._nodes[node.id] = node

        # 更新索引
        if node.team_id not in self._index_by_team:
            self._index_by_team[node.team_id] = []
        if node.id not in self._index_by_team[node.team_id]:
            self._index_by_team[node.team_id].append(node.id)

        if node.type:
            if node.type not in self._index_by_type:
                self._index_by_type[node.type] = []
            if node.id not in self._index_by_type[node.type]:
                self._index_by_type[node.type].append(node.id)

        if self.persist_path:
            self._save()

        return node

    async def read(self, node_id: UUID) -> MemoryNode | None:
        return self._nodes.get(node_id)

    async def search(
        self,
        team_id: UUID,
        query_embedding: list[float],
        limit: int = 10,
        type_filter: str | None = None,
    ) -> list[MemoryNode]:
        # 内存版本：按 type 过滤后返回全部（无向量搜索）
        node_ids = self._index_by_team.get(team_id, [])
        results = []
        for nid in node_ids:
            node = self._nodes.get(nid)
            if node and (type_filter is None or node.type == type_filter):
                results.append(node)
        return results[:limit]

    async def hybrid_search(
        self,
        team_id: UUID,
        query: str,
        query_embedding: list[float] | None = None,
        limit: int = 10,
        type_filter: str | None = None,
        hybrid: bool = True,
        mmr: bool = True,
        temporal_decay: bool = True,
    ) -> list[MemoryNode]:
        """混合搜索实现

        结合向量相似度 × 0.7 + 全文搜索 × 0.3
        支持 MMR 和时间衰减
        """
        node_ids = self._index_by_team.get(team_id, [])
        candidates: list[tuple[MemoryNode, float]] = []

        for nid in node_ids:
            node = self._nodes.get(nid)
            if not node:
                continue
            if type_filter and node.type != type_filter:
                continue

            # 更新访问信息
            node.access_count += 1
            node.last_accessed = datetime.utcnow()

            # 计算各维度得分
            vector_score = 0.0
            text_score = 0.0

            # 向量相似度
            if query_embedding and node.embedding:
                vector_score = self._cosine_similarity(query_embedding, node.embedding)

            # 全文搜索得分
            text_score = self._text_match_score(query, node.content)

            # 混合得分
            if hybrid:
                hybrid_score = vector_score * 0.7 + text_score * 0.3
            else:
                hybrid_score = vector_score if vector_score > 0 else text_score

            # 时间衰减
            if temporal_decay:
                age_hours = (datetime.utcnow() - node.created_at).total_seconds() / 3600
                decay_factor = math.exp(-age_hours / (24 * 7))  # 7天半衰期
                hybrid_score *= (0.5 + 0.5 * decay_factor)

            # 访问次数加权（热门记忆略微提升）
            access_boost = 1.0 + math.log1p(node.access_count) * 0.05
            hybrid_score *= access_boost

            node.relevance_score = hybrid_score
            candidates.append((node, hybrid_score))

        # 排序
        candidates.sort(key=lambda x: x[1], reverse=True)

        # MMR（最大边际相关性）去重
        if mmr and len(candidates) > 1:
            candidates = self._mmr_diversity(candidates, lambda n: n.content, limit=limit)

        # 返回结果
        return [node for node, _ in candidates[:limit]]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """计算余弦相似度"""
        if len(a) != len(b) or not a or not b:
            return 0.0

        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    def _text_match_score(self, query: str, content: str) -> float:
        """计算文本匹配得分（TF-IDF 简化版）"""
        if not query or not content:
            return 0.0

        query_terms = self._tokenize(query.lower())
        content_lower = content.lower()

        if not query_terms:
            return 0.0

        matches = sum(1 for term in query_terms if term in content_lower)
        term_count = len(query_terms)

        # 基础匹配率
        base_score = matches / term_count if term_count > 0 else 0.0

        # 词频加权
        term_frequency = sum(content_lower.count(term) for term in query_terms)
        tf_score = min(term_frequency / len(content.split()), 1.0)  # 归一化

        # 综合得分
        return base_score * 0.6 + tf_score * 0.4

    def _tokenize(self, text: str) -> list[str]:
        """简单分词"""
        return re.findall(r'\w+', text)

    def _mmr_diversity(
        self,
        candidates: list[tuple[MemoryNode, float]],
        get_text: callable,
        limit: int,
        lambda_param: float = 0.5,
    ) -> list[tuple[MemoryNode, float]]:
        """MMR（最大边际相关性）去重

        MMR = argmax [λ * relevance - (1-λ) * max_similarity(selected, candidate)]
        """
        if not candidates or limit <= 0:
            return []

        selected: list[MemoryNode] = []
        remaining = list(candidates)

        while len(selected) < limit and remaining:
            best_score = float('-inf')
            best_idx = 0

            for i, (node, relevance) in enumerate(remaining):
                # 计算与已选节点的最大相似度
                max_sim = 0.0
                for sel_node in selected:
                    sim = self._text_match_score(
                        get_text(sel_node)[:100],
                        get_text(node)[:100]
                    )
                    max_sim = max(max_sim, sim)

                # MMR 公式
                mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim

                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = i

            sel_node, sel_score = remaining.pop(best_idx)
            selected.append(sel_node)

        return [(node, score) for node, score in candidates if node in selected]

    async def query(
        self,
        team_id: UUID,
        type_filter: str | None = None,
        agent_id: UUID | None = None,
        limit: int = 100,
    ) -> list[MemoryNode]:
        node_ids = self._index_by_team.get(team_id, [])
        results = []
        for nid in node_ids:
            node = self._nodes.get(nid)
            if node:
                if type_filter and node.type != type_filter:
                    continue
                if agent_id and node.agent_id != agent_id:
                    continue
                results.append(node)
        # 按时间倒序
        results.sort(key=lambda n: n.created_at, reverse=True)
        return results[:limit]

    async def update(self, node: MemoryNode) -> MemoryNode:
        node.updated_at = datetime.utcnow()
        self._nodes[node.id] = node
        if self.persist_path:
            self._save()
        return node

    async def delete(self, node_id: UUID) -> bool:
        if node_id in self._nodes:
            node = self._nodes.pop(node_id)
            # 从索引移除
            if node.team_id in self._index_by_team:
                self._index_by_team[node.team_id].remove(node_id)
            if node.type and node.type in self._index_by_type:
                self._index_by_type[node.type].remove(node_id)
            if self.persist_path:
                self._save()
            return True
        return False

    def _save(self) -> None:
        if not self.persist_path:
            return
        data = {
            str(k): v.model_dump(mode="json") for k, v in self._nodes.items()
        }
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.persist_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    def _load(self) -> None:
        if not self.persist_path or not self.persist_path.exists():
            return
        with open(self.persist_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in data.items():
            node = MemoryNode(**v)
            self._nodes[node.id] = node

        # 重建索引
        for node in self._nodes.values():
            if node.team_id:
                if node.team_id not in self._index_by_team:
                    self._index_by_team[node.team_id] = []
                if node.id not in self._index_by_team[node.team_id]:
                    self._index_by_team[node.team_id].append(node.id)

            if node.type:
                if node.type not in self._index_by_type:
                    self._index_by_type[node.type] = []
                if node.id not in self._index_by_type[node.type]:
                    self._index_by_type[node.type].append(node.id)


class MemoryGraphPostgres(AbstractMemoryGraph):
    """PostgreSQL + pgvector 生产环境记忆图谱"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "openhive",
        user: str = "postgres",
        password: str = "",
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self._pool: Any = None

    async def connect(self) -> None:
        import asyncpg

        self._pool = await asyncpg.create_pool(
            host=self.host,
            port=self.port,
            database=self.database,
            user=self.user,
            password=self.password,
            min_size=5,
            max_size=20,
        )

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def init_schema(self) -> None:
        """初始化数据库 schema（包含 pgvector 扩展）"""
        if not self._pool:
            raise RuntimeError("Not connected to database")

        async with self._pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_nodes (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    type VARCHAR(50) NOT NULL,
                    content TEXT NOT NULL,
                    embedding VECTOR(1536),
                    metadata JSONB DEFAULT '{}',
                    agent_id UUID,
                    team_id UUID,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)

            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_nodes_team ON memory_nodes(team_id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_nodes_agent ON memory_nodes(agent_id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_nodes_type ON memory_nodes(type)"
            )
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_nodes_embedding
                ON memory_nodes USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
            """)

    async def write(self, node: MemoryNode) -> MemoryNode:
        if not self._pool:
            raise RuntimeError("Not connected to database")

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO memory_nodes (id, type, content, embedding, metadata, agent_id, team_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id, created_at, updated_at
                """,
                node.id,
                node.type,
                node.content,
                node.embedding,
                json.dumps(node.metadata),
                node.agent_id,
                node.team_id,
            )
            node.created_at = row["created_at"]
            node.updated_at = row["updated_at"]
            return node

    async def read(self, node_id: UUID) -> MemoryNode | None:
        if not self._pool:
            raise RuntimeError("Not connected to database")

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM memory_nodes WHERE id = $1",
                node_id,
            )
            if not row:
                return None
            return self._row_to_node(row)

    async def search(
        self,
        team_id: UUID,
        query_embedding: list[float],
        limit: int = 10,
        type_filter: str | None = None,
    ) -> list[MemoryNode]:
        if not self._pool:
            raise RuntimeError("Not connected to database")

        async with self._pool.acquire() as conn:
            if type_filter:
                rows = await conn.fetch(
                    """
                    SELECT * FROM memory_nodes
                    WHERE team_id = $1 AND type = $2 AND embedding IS NOT NULL
                    ORDER BY embedding <=> $3
                    LIMIT $4
                    """,
                    team_id,
                    type_filter,
                    query_embedding,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM memory_nodes
                    WHERE team_id = $1 AND embedding IS NOT NULL
                    ORDER BY embedding <=> $2
                    LIMIT $3
                    """,
                    team_id,
                    query_embedding,
                    limit,
                )
            return [self._row_to_node(row) for row in rows]

    async def query(
        self,
        team_id: UUID,
        type_filter: str | None = None,
        agent_id: UUID | None = None,
        limit: int = 100,
    ) -> list[MemoryNode]:
        if not self._pool:
            raise RuntimeError("Not connected to database")

        conditions = ["team_id = $1"]
        params: list[Any] = [team_id]

        if type_filter:
            conditions.append(f"type = ${len(params) + 1}")
            params.append(type_filter)

        if agent_id:
            conditions.append(f"agent_id = ${len(params) + 1}")
            params.append(agent_id)

        params.append(limit)

        query = f"""
            SELECT * FROM memory_nodes
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
            LIMIT ${len(params)}
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_node(row) for row in rows]

    async def update(self, node: MemoryNode) -> MemoryNode:
        if not self._pool:
            raise RuntimeError("Not connected to database")

        node.updated_at = datetime.utcnow()

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE memory_nodes
                SET content = $2, metadata = $3, updated_at = $4
                WHERE id = $1
                """,
                node.id,
                node.content,
                json.dumps(node.metadata),
                node.updated_at,
            )
            return node

    async def delete(self, node_id: UUID) -> bool:
        if not self._pool:
            raise RuntimeError("Not connected to database")

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM memory_nodes WHERE id = $1",
                node_id,
            )
            return result == "DELETE 1"

    def _row_to_node(self, row: Any) -> MemoryNode:
        import asyncpg

        return MemoryNode(
            id=row["id"],
            type=row["type"],
            content=row["content"],
            embedding=row["embedding"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            agent_id=row["agent_id"],
            team_id=row["team_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# 向后兼容别名
MemoryGraph = MemoryGraphInMemory
