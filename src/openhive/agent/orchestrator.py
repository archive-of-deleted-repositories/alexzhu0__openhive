"""Orchestrator Agent - 任务分解与协调"""

import asyncio
from collections import deque
import json
from typing import Any, Awaitable, Callable
from uuid import uuid4

from openhive.agent.base import BaseAgent
from openhive.core.message import Message, MessageType
from openhive.core.external_routing import select_external_runtimes
from openhive.core.swarm import SwarmDecision, SwarmExecutionPolicy, SwarmResponseScorer


class OrchestratorAgent(BaseAgent):
    """编排器 Agent - 负责分解任务、协调 Specialist Agent"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        external_executors = kwargs.pop(
            "external_executors",
            {},
        )
        super().__init__(*args, **kwargs)
        self._pending_tasks: dict[str, asyncio.Future] = {}
        self._pending_task_queues: dict[str, deque[asyncio.Future]] = {}
        self.external_executors: dict[str, Callable[[dict[str, Any]], Awaitable[Any]]] = (
            external_executors
        )
        self._response_scorer = SwarmResponseScorer()

    async def execute_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        """执行任务：分析目标、分解子任务、分配给 Specialist、等待结果"""
        goal = task_data.get("goal", "")
        precomputed_tasks = task_data.get("tasks", [])
        precomputed_assignments = task_data.get("assignments", {})
        candidate_assignments = task_data.get("candidate_assignments", {})
        policy = SwarmExecutionPolicy.from_mapping(task_data.get("swarm_policy"))
        audit = bool(policy.audit_enabled)

        # 写记忆：开始规划
        if audit:
            await self.write_memory(
                type="orchestrator_start",
                content=f"Orchestrator 开始规划任务: {goal}",
                metadata={"goal": goal, "policy": policy.to_dict()},
            )

        # 如果有预计算的任务（来自 TeamAssembler），直接使用；否则自己分解
        if precomputed_tasks:
            subtasks = []
            for t in precomputed_tasks:
                if isinstance(t, dict):
                    task_name = t.get("name", "unknown")
                    specialist = precomputed_assignments.get(
                        task_name,
                        t.get("specialist_name", "research"),
                    )
                    subtasks.append(
                        {
                            "name": task_name,
                            "description": t.get("description", ""),
                            "specialist": specialist,
                            "risk_level": t.get("risk_level", "medium"),
                            "department": t.get("department", ""),
                            "required_capabilities": self._normalize_capabilities(
                                t.get("required_capabilities")
                            ),
                            "parent_goal": goal,
                        }
                    )
                else:
                    task_name = getattr(t, "name", "unknown")
                    subtasks.append(
                        {
                            "name": task_name,
                            "description": getattr(t, "description", ""),
                            "specialist": precomputed_assignments.get(
                                task_name,
                                getattr(t, "specialist_name", "research"),
                            ),
                            "risk_level": getattr(t, "risk_level", "medium"),
                            "department": getattr(t, "department", ""),
                            "required_capabilities": self._normalize_capabilities(
                                getattr(t, "required_capabilities", [])
                            ),
                            "parent_goal": goal,
                        }
                    )
        else:
            subtasks = await self._decompose_task_async(goal)

        # 分配子任务给 Specialist Agent 并等待结果
        task_futures: list[asyncio.Task[dict[str, Any]]] = []
        for subtask in subtasks:
            specialist_name = subtask.get("specialist")
            if not specialist_name:
                continue

            task_id = subtask.get("name", "unnamed")
            risk_level = subtask.get("risk_level", "medium")
            department = subtask.get("department", "")
            candidates = candidate_assignments.get(task_id, [])
            responders = policy.responders(specialist_name, candidates, risk_level)

            if audit:
                await self.write_memory(
                    type="swarm_dispatch",
                    content=f"子任务派发: {task_id}",
                    metadata={
                        "goal": goal,
                        "task": task_id,
                        "primary": specialist_name,
                        "responders": responders,
                        "risk_level": risk_level,
                        "department": department,
                    },
                )

            subtask["responders"] = responders
            subtask["parallelism"] = policy.parallelism
            subtask["risk_level"] = risk_level
            subtask["department"] = department
            future = asyncio.create_task(
                self._run_with_redundancy(task_id, responders, subtask, policy)
            )
            task_futures.append(future)

        # 等待所有子任务完成
        results = await asyncio.gather(*task_futures, return_exceptions=True)
        decisions = [r for r in results if isinstance(r, dict) and r.get("decision")]

        # 汇总结果
        summary = self._summarize_results(results)

        # 写记忆：完成规划
        if audit:
            await self.write_memory(
                type="orchestrator_done",
                content=f"Orchestrator 完成规划: {summary}",
                metadata={"goal": goal, "subtasks": subtasks, "results": results},
            )

        return {
            "goal": goal,
            "subtasks": subtasks,
            "results": [r for r in results if not isinstance(r, Exception)],
            "summary": summary,
            "decisions": decisions,
        }

    async def _assign_and_wait(
        self,
        specialist_name: str,
        subtask: dict[str, Any],
    ) -> dict[str, Any]:
        """分配子任务给 Specialist 并等待结果"""
        task_id = subtask.get("name", str(id(subtask)))
        execution_id = str(subtask.get("execution_id") or f"{task_id}::{uuid4().hex[:12]}")

        if not specialist_name:
            return {
                "name": task_id,
                "execution_id": execution_id,
                "status": "error",
                "specialist": specialist_name,
                "error": "specialist_name 为空",
            }

        # 创建 Future 用于接收结果，按 execution_id 做隔离
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_tasks[execution_id] = future
        self._register_legacy_waiter(task_id, future)
        timeout_seconds = self._parse_timeout_seconds(
            subtask.get("execution_timeout_seconds", 120.0)
        )

        try:
            # 发送任务消息
            await self.send_to(
                specialist_name,
                MessageType.TASK,
                {
                    "name": task_id,
                    "description": subtask.get("description", ""),
                    "task_id": task_id,
                    "execution_id": execution_id,
                    "department": subtask.get("department", ""),
                    "parent_goal": subtask.get("parent_goal", ""),
                },
            )

            # 等待结果（带超时）
            try:
                result = await asyncio.wait_for(future, timeout=timeout_seconds)
                return {
                    "name": task_id,
                    "execution_id": execution_id,
                    "status": "done",
                    "specialist": specialist_name,
                    "result": result,
                }
            except asyncio.TimeoutError:
                return {
                    "name": task_id,
                    "execution_id": execution_id,
                    "status": "timeout",
                    "specialist": specialist_name,
                    "error": f"任务执行超时（{timeout_seconds}秒）",
                }

        finally:
            self._pending_tasks.pop(execution_id, None)
            self._unregister_legacy_waiter(task_id, future)

    async def _run_with_redundancy(
        self,
        task_id: str,
        responders: list[str],
        subtask: dict[str, Any],
        policy: SwarmExecutionPolicy,
    ) -> dict[str, Any]:
        """按冗余策略并行执行同一子任务"""
        responders, routing_notes = self._filter_external_responders(
            list(responders),
            subtask,
        )
        limit = min(len(responders), max(1, subtask.get("parallelism", 1)))
        responders = responders[:limit] if responders else []

        if not responders:
            return {
                "task_id": task_id,
                "status": "error",
                "decision": SwarmDecision(
                    task_name=task_id,
                    chosen="",
                    responders=[],
                    risk_level=subtask.get("risk_level", "medium"),
                    routing_notes=routing_notes,
                    notes=["No responders available"],
                ).__dict__,
                "responses": [],
            }

        max_rounds = 1 + max(0, policy.max_retry_rounds)
        responses: list[Any] = []
        decision = SwarmDecision(
            task_name=task_id,
            chosen="",
            responders=list(responders),
            risk_level=subtask.get("risk_level", "medium"),
            routing_notes=list(routing_notes),
        )

        for attempt_index in range(max_rounds):
            round_responses = await self._collect_redundant_responses(
                task_id,
                responders,
                subtask,
                attempt_index + 1,
            )
            responses.extend(round_responses)
            decision = self._resolve_conflicts(responses, task_id, subtask, policy)
            decision.responders = list(responders)
            decision.routing_notes = list(routing_notes)
            decision.attempts = attempt_index + 1

            if policy.should_retry(decision, subtask.get("risk_level", "medium")):
                if attempt_index + 1 >= max_rounds:
                    decision.retry_reason = "高风险任务超过重试上限，仍未通过仲裁阈值"
                else:
                    decision.notes.insert(
                        0,
                        f"第{attempt_index + 1}轮结果未满足置信度阈值，准备第{attempt_index + 2}轮",
                    )
            else:
                break

        if policy.audit_enabled and self.llm:
            await self.write_memory(
                type="swarm_decision",
                content=f"子任务 {task_id} 决策完成: {decision.chosen}",
                metadata={
                    "task": task_id,
                    "decision": decision.__dict__,
                    "responses": [
                        str(r)[:200] for r in responses if not isinstance(r, Exception)
                    ],
                },
            )

        return {
            "task_id": task_id,
            "name": task_id,
            "status": "done"
            if decision.chosen and not decision.retry_reason
            else "retry",
            "decision": decision.__dict__,
            "responses": responses,
        }

    def _filter_external_responders(
        self,
        responders: list[str],
        subtask: dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        """按能力标签过滤外部 runtime 响应者"""
        if not responders:
            return [], []

        external_candidates = [
            responder for responder in responders if responder in self.external_executors
        ]
        if not external_candidates:
            return responders, []

        required_capabilities = self._normalize_capabilities(
            subtask.get("required_capabilities", [])
        )
        external_selected = select_external_runtimes(
            required_capabilities=required_capabilities,
            specialist_name=subtask.get("specialist", ""),
            risk_level=subtask.get("risk_level", "medium"),
            runtime_names=external_candidates,
        )
        routing_notes: list[str] = []
        risk_level = str(subtask.get("risk_level", "medium")).strip().lower()
        is_high_risk = risk_level in {"high", "critical"}

        if not external_selected:
            if is_high_risk:
                routing_notes.append("高风险任务未命中能力路由，保留全部外部执行者以保障兜底")
                return responders, routing_notes

            filtered_out = list(external_candidates)
            routing_notes.append("按路由能力剔除外部执行者: " + ", ".join(filtered_out))
            return [
                responder
                for responder in responders
                if responder not in self.external_executors
            ], routing_notes

        filtered_out: list[str] = [
            responder for responder in external_candidates if responder not in external_selected
        ]
        if filtered_out:
            routing_notes.append(
                "按路由能力剔除外部执行者: "
                + ", ".join(filtered_out)
            )

        routing_notes.append(
            "路由保留外部执行者: " + ", ".join(external_selected)
        )
        internal_selected = [
            responder for responder in responders if responder not in self.external_executors
        ]
        return internal_selected + external_selected, routing_notes

    async def _collect_redundant_responses(
        self,
        task_id: str,
        responders: list[str],
        subtask: dict[str, Any],
        attempt: int,
    ) -> list[Any]:
        """发起一轮冗余执行，返回该轮有效响应"""
        parallel_futures = []
        for responder_name in responders:
            execution_id = f"{task_id}::{attempt}::{responder_name}::{uuid4().hex[:12]}"
            subtask_copy = dict(subtask)
            subtask_copy["execution_id"] = execution_id
            if responder_name in self.external_executors:
                parallel_futures.append(
                    asyncio.create_task(
                        self._assign_external_and_wait(responder_name, subtask_copy),
                    )
                )
                continue

            parallel_futures.append(
                asyncio.create_task(
                    self._assign_and_wait(responder_name, subtask_copy),
                )
            )

        return await asyncio.gather(*parallel_futures, return_exceptions=True)

    async def _assign_external_and_wait(
        self,
        responder_name: str,
        subtask: dict[str, Any],
    ) -> dict[str, Any]:
        """使用外部执行器执行任务"""
        task_id = subtask.get("name", str(id(subtask)))
        execution_id = str(subtask.get("execution_id") or f"{task_id}::{uuid4().hex[:12]}")
        executor = self.external_executors.get(responder_name)
        if not executor:
            return {
                "name": task_id,
                "execution_id": execution_id,
                "status": "error",
                "specialist": responder_name,
                "error": "外部执行器不存在",
            }

        request_payload = {
            "name": task_id,
            "description": subtask.get("description", ""),
            "task_id": task_id,
            "execution_id": execution_id,
            "specialist": responder_name,
            "department": subtask.get("department", ""),
            "parent_goal": subtask.get("parent_goal", ""),
            "risk_level": subtask.get("risk_level", ""),
        }
        request_payload["required_capabilities"] = subtask.get("required_capabilities", [])
        request_payload["payload"] = subtask

        execution_timeout_seconds = self._parse_timeout_seconds(
            subtask.get("execution_timeout_seconds", 120.0)
        )

        try:
            result = await asyncio.wait_for(
                executor(
                    dict(
                        request_payload,
                        task_id=execution_id,
                        dispatch_task_id=execution_id,
                        task_name=task_id,
                    )
                ),
                timeout=execution_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return {
                "name": task_id,
                "execution_id": execution_id,
                "status": "timeout",
                "specialist": responder_name,
                "error": f"任务执行超时（{execution_timeout_seconds}秒）",
            }
        except Exception as e:
            return {
                "name": task_id,
                "execution_id": execution_id,
                "status": "error",
                "specialist": responder_name,
                "error": str(e),
            }

        return self._normalize_external_result(
            task_id=task_id,
            execution_id=execution_id,
            specialist_name=responder_name,
            raw_result=result,
        )

    @staticmethod
    def _parse_timeout_seconds(value: Any) -> float:
        """将超时配置标准化为正数秒"""
        try:
            timeout_seconds = float(value)
        except (TypeError, ValueError):
            return 120.0
        return timeout_seconds if timeout_seconds > 0 else 120.0

    def _register_legacy_waiter(self, task_id: str, future: asyncio.Future) -> None:
        if not task_id:
            return
        queue = self._pending_task_queues.setdefault(task_id, deque())
        queue.append(future)

    def _unregister_legacy_waiter(self, task_id: str, future: asyncio.Future) -> None:
        if not task_id:
            return
        queue = self._pending_task_queues.get(task_id)
        if not queue:
            return
        filtered = deque(item for item in queue if item is not future)
        if filtered:
            self._pending_task_queues[task_id] = filtered
        else:
            self._pending_task_queues.pop(task_id, None)

    def _take_legacy_waiter(self, task_id: str) -> asyncio.Future | None:
        if not task_id:
            return None
        queue = self._pending_task_queues.get(task_id)
        if not queue:
            return None

        while queue and (queue[0].done() or queue[0].cancelled()):
            queue.popleft()

        if not queue:
            self._pending_task_queues.pop(task_id, None)
            return None

        future = queue.popleft()
        if not queue:
            self._pending_task_queues.pop(task_id, None)
        return future

    def _normalize_external_result(
        self,
        task_id: str,
        execution_id: str,
        specialist_name: str,
        raw_result: Any,
    ) -> dict[str, Any]:
        """将外部执行器响应标准化为编排器可消费格式"""
        if not isinstance(raw_result, dict):
            return {
                "name": task_id,
                "execution_id": execution_id,
                "status": "error",
                "specialist": specialist_name,
                "error": "外部执行器返回非字典响应",
            }

        message_type = str(raw_result.get("type", "")).upper()
        status = str(raw_result.get("status", "")).lower()

        if message_type == "ERROR" or status in {"error", "failed", "failure"}:
            error_payload = raw_result.get("error")
            error_message = (
                error_payload.get("message", "未知错误")
                if isinstance(error_payload, dict)
                else str(error_payload or "外部执行器返回错误")
            )
            return {
                "name": task_id,
                "execution_id": execution_id,
                "status": "error",
                "specialist": specialist_name,
                "error": error_message,
                "result": raw_result,
            }

        if status == "timeout":
            return {
                "name": task_id,
                "execution_id": execution_id,
                "status": "timeout",
                "specialist": specialist_name,
                "error": str(raw_result.get("error", "任务执行超时")),
                "result": raw_result,
            }

        result_payload = raw_result.get("result", raw_result)
        return {
            "name": task_id,
            "execution_id": execution_id,
            "status": "done",
            "specialist": specialist_name,
            "result": result_payload if isinstance(result_payload, dict) else {"result": result_payload},
        }

    def _result_text(self, response_item: dict[str, Any]) -> str:
        """提取响应文本，用于仲裁长度与质量评估"""
        return self._response_scorer.extract_result_text(response_item)

    def _resolve_conflicts(
        self,
        responses: list[Any],
        task_id: str,
        subtask: dict[str, Any],
        policy: SwarmExecutionPolicy,
    ) -> SwarmDecision:
        """对并行多响应做简单仲裁"""
        min_chars = max(1, int(policy.min_result_chars))
        scorer = SwarmResponseScorer(
            min_result_chars=min_chars,
            evidence_fields=policy.scorer_evidence_fields,
            length_target_factor=policy.scorer_length_target_factor,
            duplicate_similarity_threshold=policy.scorer_duplicate_similarity_threshold,
            length_weight=policy.scorer_length_weight,
            evidence_weight=policy.scorer_evidence_weight,
            structure_weight=policy.scorer_structure_weight,
        )

        valid: list[dict[str, Any]] = []
        for item in responses:
            if not isinstance(item, dict) or item.get("status") != "done":
                continue
            if len(scorer.extract_result_text(item)) >= min_chars:
                valid.append(item)

        notes: list[str] = [f"候选池大小: {len(valid)}"]
        if not valid:
            return SwarmDecision(
                task_name=task_id,
                chosen="",
                responders=subtask.get("responders", []),
                risk_level=subtask.get("risk_level", "medium"),
                winner_confidence=0.0,
                notes=["No valid responder" if not policy.requires_redundancy_for(
                    subtask.get("risk_level", "medium")
                ) else "No successful responder"],
            )

        ranked: list[tuple[float, int, dict[str, Any], str]] = []
        signatures: list[str] = []
        deduped: list[dict[str, Any]] = []
        duplicate_removed = 0

        for item in valid:
            signature = scorer.response_signature(item)
            if any(scorer.is_duplicate(signature, existing) for existing in signatures):
                duplicate_removed += 1
                continue
            signatures.append(signature)
            deduped.append(item)

        if duplicate_removed > 0:
            notes.append(f"去重后候选: {len(deduped)}（去除 {duplicate_removed} 条重复）")

        if not deduped:
            return SwarmDecision(
                task_name=task_id,
                chosen="",
                responders=subtask.get("responders", []),
                risk_level=subtask.get("risk_level", "medium"),
                winner_confidence=0.0,
                notes=["No unique responder after dedupe", *notes],
            )

        for item in deduped:
            quality = scorer.evaluate(item)
            ranked.append(
                (quality.total, len(self._result_text(item)), item, self._format_quality_note(quality))
            )

        if not ranked:
            return SwarmDecision(
                task_name=task_id,
                chosen="",
                responders=subtask.get("responders", []),
                risk_level=subtask.get("risk_level", "medium"),
                winner_confidence=0.0,
                notes=["No unique responder after scoring", *notes],
            )

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        best_score = ranked[0][0]
        best = ranked[0][2]
        best_specialist = best.get("specialist", "")
        best_quality_note = ranked[0][3]
        chosen_content_len = len(self._result_text(best))
        notes.extend(
            [
                f"长度得分: {chosen_content_len}",
                f"质量得分: {best_score:.3f}",
                best_quality_note,
            ]
        )
        if len(deduped) > 1:
            notes.append(f"多模型验证：{len(deduped)} 路并发")

        return SwarmDecision(
            task_name=task_id,
            chosen=best_specialist,
            responders=subtask.get("responders", []),
            risk_level=subtask.get("risk_level", "medium"),
            winner_confidence=min(0.99, max(0.1, best_score)),
            notes=notes,
        )

    @staticmethod
    def _format_quality_note(quality: Any) -> str:
        reasons = getattr(quality, "reasons", [])
        if not reasons:
            return "无质量细分"
        return "; ".join(reasons)

    async def _handle_result(self, message: Message) -> None:
        """处理子任务结果（由 BaseAgent._handle_message 调用）"""
        content = message.content
        execution_id = content.get("execution_id")

        if isinstance(execution_id, str) and execution_id in self._pending_tasks:
            future = self._pending_tasks[execution_id]
            if not future.done():
                future.set_result(content)
            return

        task_name = content.get("task_name")
        if task_name and isinstance(task_name, str):
            # 兼容旧流程：按任务名队列回退匹配，支持冗余并发任务
            legacy_waiter = self._take_legacy_waiter(task_name)
            if legacy_waiter and not legacy_waiter.done():
                legacy_waiter.set_result(content)
                return
            keys = [
                key for key in self._pending_tasks
                if key.startswith(f"{task_name}::")
                and not self._pending_tasks[key].done()
            ]
            if len(keys) == 1:
                future = self._pending_tasks[keys[0]]
                future.set_result(content)
                return
            if len(keys) > 1:
                # 历史兼容：不唯一时取首个可用等待者，避免阻塞
                for key in keys:
                    future = self._pending_tasks.get(key)
                    if future and not future.done():
                        future.set_result(content)
                        return

    def _decompose_task(self, goal: str) -> list[dict[str, Any]]:
        """使用 LLM 分解任务（同步版本，由 execute_task 调用时在协程中执行）"""
        # 这个方法会被 execute_task 中的异步代码调用
        # 实际的 LLM 调用在下面的异步版本中进行
        return []

    async def _decompose_task_async(self, goal: str) -> list[dict[str, Any]]:
        """使用 LLM 分解任务"""
        prompt = f"""你是一个任务分解专家。用户的目标是：

{goal}

请将这个目标分解成 2-5 个具体的子任务，每个子任务由一个 Specialist Agent 执行。

对于每个子任务，指定：
- name: 任务名称（英文，简短）
- description: 任务描述（中文，详细）
- specialist: 适合执行此任务的 Specialist 名称（如 "research", "analysis", "writing"）

请只返回 JSON 数组，不要有其他文字。例如：
[{{"name": "research_market", "description": "调研市场规模和增长趋势", "specialist": "research"}}, {{"name": "analyze_competitors", "description": "分析主要竞争对手", "specialist": "analysis"}}]"""

        try:
            response = await self.llm.complete(prompt)
            return self._parse_subtasks(response)
        except Exception:
            # LLM 调用失败时返回默认任务
            return [
                {
                    "name": "default_task",
                    "description": goal,
                    "specialist": "research",
                    "risk_level": "medium",
                    "department": "general",
                    "required_capabilities": [],
                }
            ]

    def _parse_subtasks(self, response: str) -> list[dict[str, Any]]:
        """解析 LLM 返回的子任务列表"""
        try:
            start = response.find("[")
            end = response.rfind("]") + 1
            if start != -1 and end != 0:
                parsed = json.loads(response[start:end])
                if isinstance(parsed, list):
                    normalized = []
                    for item in parsed:
                        if not isinstance(item, dict):
                            continue
                        normalized.append(
                            {
                                "name": item.get("name", "unnamed"),
                                "description": item.get("description", ""),
                                "specialist": item.get("specialist", "research"),
                                "risk_level": item.get("risk_level", "medium"),
                                "department": item.get("department", ""),
                                "required_capabilities": self._normalize_capabilities(
                                    item.get("required_capabilities", item.get("capabilities", [])),
                                ),
                            }
                        )
                    if normalized:
                        return normalized
        except Exception:
            pass

        return [
                {
                    "name": "default_task",
                    "description": response[:200] if response else "任务",
                    "specialist": "research",
                    "risk_level": "medium",
                    "department": "general",
                    "required_capabilities": [],
                }
            ]

    def _summarize_results(self, results: list[Any]) -> str:
        """汇总子任务结果"""
        successful = 0
        failed = 0
        for r in results:
            if isinstance(r, Exception):
                failed += 1
            elif isinstance(r, dict) and r.get("status") == "done":
                successful += 1
            else:
                failed += 1
        total = successful + failed
        return f"完成 {successful}/{total} 个子任务"

    @staticmethod
    def _normalize_capabilities(raw: Any) -> list[str]:
        """将能力声明标准化为字符串列表"""
        if not raw:
            return []

        if isinstance(raw, str):
            return [raw] if raw.strip() else []

        caps: list[str] = []
        for cap in raw:
            if isinstance(cap, str) and cap.strip():
                caps.append(cap.strip())
                continue

            cap_name = getattr(cap, "name", None)
            if isinstance(cap_name, str) and cap_name.strip():
                caps.append(cap_name.strip())

        return list(dict.fromkeys(caps))
