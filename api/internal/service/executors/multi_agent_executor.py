import json
import logging
from dataclasses import dataclass

from injector import inject
from flask import current_app, has_app_context
from langchain_core.messages import HumanMessage, SystemMessage

from internal.core.agent.agents.function_call_agent import FunctionCallAgent
from internal.core.agent.entities.agent_entity import AgentConfig
from internal.core.agent.entities.queue_entity import QueueEvent
from internal.entity.conversation_entity import InvokeFrom
from internal.entity.dag_entity import DAGGraph, DAGNode, AgentInstanceSpec
from internal.entity.execution_orchestration_entity import (
    OrchestratedAgentResult,
    TaskPlan,
)
from internal.service.agent_task_executor import AgentTaskExecutor
from internal.service.dag_engine_service import DAGEngine
from internal.service.agent_instance_pool import AgentInstancePool
from internal.service.execution_coordinator_service import ExecutionCoordinatorService
from internal.service.executors.task_decomposer import TaskDecomposer
from internal.service.result_synthesizer_service import ResultSynthesizerService
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

_MULTI_AGENT_MODES = {"multi_agent", "multi_agent_parallel", "multi_agent_sequential"}


@inject
@dataclass
class MultiAgentExecutor:
    db: SQLAlchemy
    task_decomposer: TaskDecomposer
    result_synthesizer: ResultSynthesizerService
    dag_engine: DAGEngine
    agent_instance_pool: AgentInstancePool

    def execute(
        self,
        query,
        account,
        conversation,
        message,
        routing_decision,
        llm,
        tools,
        history,
    ):
        conversation_id = str(conversation.id)
        message_id = str(message.id)
        try:
            available_agents = self._extract_available_agents(routing_decision)
            available_tools = self._extract_available_tools(tools)

            plan = self.task_decomposer.decompose(query, available_agents, available_tools)
            plan.execution_mode = self._resolve_execution_mode(routing_decision)

            agent_config = self._build_agent_config(account, tools)
            executor = AgentTaskExecutor(
                agent_class=FunctionCallAgent,
                agent_config=agent_config,
                tools=tools or [],
                llm=llm,
                history=history or [],
                query=query,
            )

            nodes: dict[str, DAGNode] = {}
            for item in plan.items:
                agent_entry = next(
                    (a for a in available_agents if a["agent_id"] == item.agent_id),
                    None,
                )
                agent_id = item.agent_id or (agent_entry["agent_id"] if agent_entry else item.task_id)
                nodes[item.task_id] = DAGNode(
                    id=item.task_id,
                    agent_id=agent_id,
                    title=item.title,
                    description=item.description,
                    depends_on=list(item.depends_on),
                )

            graph = DAGGraph(
                nodes=nodes,
                original_query=query,
                aggregation_strategy=plan.aggregation_strategy,
            )

            for item in plan.items:
                agent_entry = next(
                    (a for a in available_agents if a["agent_id"] == (item.agent_id or item.task_id)),
                    None,
                )
                agent_id = item.agent_id or (agent_entry["agent_id"] if agent_entry else item.task_id)
                spec = AgentInstanceSpec(
                    agent_id=agent_id,
                    agent_class=FunctionCallAgent,
                    llm=llm,
                    tools=tools or [],
                    system_prompt=None,
                    max_iterations=15,
                )
                self.agent_instance_pool.create_instance(
                    agent_id=spec.agent_id,
                    agent_class=spec.agent_class,
                    llm=spec.llm,
                    tools=spec.tools,
                    system_prompt=spec.system_prompt,
                    max_iterations=spec.max_iterations,
                )

            coordinator = ExecutionCoordinatorService(executor=executor)
            dag_results = self.dag_engine.execute(
                graph=graph,
                instance_pool=self.agent_instance_pool,
                coordinator=coordinator,
            )

            results = []
            for dag_result in dag_results:
                task_id = dag_result.get("task_id", "")
                answer = dag_result.get("answer", "")
                error = dag_result.get("error")
                metadata = {}
                node = graph.nodes.get(task_id)
                if node and node.token_usage:
                    metadata["token_usage"] = node.token_usage
                result = OrchestratedAgentResult(
                    agent_id=task_id,
                    task_id=task_id,
                    answer=answer or "",
                    confidence=0.0 if error else 1.0,
                    errors=[error] if error else [],
                    metadata=metadata,
                )
                results.append(result)

            for result in results:
                token_usage = (result.metadata or {}).get("token_usage") or {}
                if token_usage:
                    from internal.entity.billing_metering_entity import BillingEventType
                    from internal.service.billing_metering_service import BillingUsageAggregator
                    billing_delta = BillingUsageAggregator(task_id=message_id).model_tokens(
                        "multi_agent",
                        input_tokens=token_usage.get("prompt_tokens", 0),
                        output_tokens=token_usage.get("completion_tokens", 0),
                        reason="agent_llm_invoke",
                    )
                    yield f"event: {BillingEventType.DELTA.value}\ndata:{json.dumps(billing_delta.to_sse())}\n\n"
                yield self._thought_sse(result, conversation_id, message_id)

            final_answer = self._aggregate_results(
                results, plan.aggregation_strategy, llm, query
            )
            synthesis_meta = {}
            if len(results) > 1:
                final_answer, synthesis_meta = self._synthesize_with_quality_check(
                    results, final_answer, query
                )
            yield self._message_sse(final_answer, conversation_id, message_id, synthesis_meta=synthesis_meta)
        except Exception as e:
            logger.warning("MultiAgentExecutor 执行失败: %s", e, exc_info=True)
            yield self._fallback_sse(conversation_id, message_id)

    def _synthesize_with_quality_check(
        self, results, fallback_answer, query
    ) -> tuple:
        try:
            synthesizer = self.result_synthesizer
            if synthesizer is None:
                return fallback_answer, {}
            orchestrated = [
                OrchestratedAgentResult(
                    agent_id=getattr(r, "agent_id", "") or getattr(r, "task_id", ""),
                    task_id=getattr(r, "task_id", ""),
                    answer=getattr(r, "answer", "") or "",
                    confidence=getattr(r, "confidence", 0.0) or 0.0,
                    sources=getattr(r, "sources", None) or [],
                    tool_calls=getattr(r, "tool_calls", None) or [],
                    warnings=getattr(r, "warnings", None) or [],
                    errors=getattr(r, "errors", None) or [],
                )
                for r in results
                if getattr(r, "answer", None)
            ]
            if len(orchestrated) <= 1:
                return fallback_answer, {}
            synthesis = synthesizer.synthesize(
                orchestrated, original_query=query
            )
            synthesized = synthesis.get("final_answer") if synthesis else None
            if not synthesized:
                return fallback_answer, {}
            warnings = synthesis.get("user_warnings") or []
            if warnings:
                logger.info("ResultSynthesizer 质量检查告警: %s", warnings)
            synthesis_meta = {
                "summary": synthesis.get("summary", ""),
                "confidence": synthesis.get("confidence", 0),
                "visible_sources": synthesis.get("visible_sources", []),
                "user_warnings": warnings,
            }
            return synthesized, synthesis_meta
        except Exception:
            logger.warning("ResultSynthesizer 汇总失败，降级为内联聚合", exc_info=True)
            return fallback_answer, {}

    def _resolve_execution_mode(self, routing_decision) -> str:
        if isinstance(routing_decision, dict):
            mode = routing_decision.get("execution_mode")
            if mode in _MULTI_AGENT_MODES:
                return mode
        return "multi_agent_parallel"

    def _extract_available_agents(self, routing_decision) -> list[dict]:
        if not isinstance(routing_decision, dict):
            return []
        agent_subset = routing_decision.get("agent_subset") or {}
        selected = agent_subset.get("selected_agents") or []
        agents: list[dict] = []
        for entry in selected:
            if isinstance(entry, dict):
                agent_id = entry.get("agent_id") or entry.get("id") or ""
                agents.append({
                    "agent_id": agent_id,
                    "name": entry.get("name") or agent_id,
                    "description": entry.get("description") or "",
                })
            elif isinstance(entry, str) and entry:
                agents.append({"agent_id": entry, "name": entry, "description": ""})
        return agents

    @staticmethod
    def _extract_available_tools(tools) -> list[dict]:
        result: list[dict] = []
        for tool in tools or []:
            name = getattr(tool, "name", None) or ""
            if not name:
                continue
            result.append({
                "name": name,
                "description": getattr(tool, "description", None) or "",
            })
        return result

    def _build_agent_config(self, account, tools):
        runtime_flask_app = current_app._get_current_object() if has_app_context() else None
        return AgentConfig(
            user_id=account.id,
            invoke_from=InvokeFrom.ASSISTANT_AGENT.value,
            tools=list(tools or []),
            language_model_service=self.task_decomposer.language_model_service,
            runtime_flask_app=runtime_flask_app,
            enable_long_term_memory=False,
        )

    def _aggregate_results(self, results, strategy, llm, query) -> str:
        answers = [result.answer for result in results if result.answer]
        if not answers:
            return ""
        if len(answers) == 1:
            return answers[0]
        if strategy == "summarize":
            return self._summarize(llm, query, answers)
        if strategy == "best_of":
            return self._best_of(llm, query, answers)
        return "\n\n---\n\n".join(answers)

    @staticmethod
    def _summarize(llm, query, answers) -> str:
        try:
            numbered = "\n".join(
                f"{idx}. {answer}" for idx, answer in enumerate(answers, start=1)
            )
            response = llm.invoke([
                SystemMessage(content="你是一个结果聚合专家。请将以下多个子任务的回答整合成一份连贯、完整的最终回答，去除重复内容，保留关键信息。"),
                HumanMessage(content=f"用户原始请求：{query}\n\n各子任务回答：\n{numbered}"),
            ])
            content = getattr(response, "content", None)
            if content:
                return content
            return "\n\n---\n\n".join(answers)
        except Exception:
            logger.warning("结果摘要聚合失败，降级为拼接", exc_info=True)
            return "\n\n---\n\n".join(answers)

    @staticmethod
    def _best_of(llm, query, answers) -> str:
        try:
            numbered = "\n".join(
                f"候选 {idx}：{answer}" for idx, answer in enumerate(answers, start=1)
            )
            response = llm.invoke([
                SystemMessage(content="你是一个结果评估专家。请从以下多个候选回答中选择最全面、最准确的一份作为最终回答，直接输出该回答的内容，不要添加解释说明。"),
                HumanMessage(content=f"用户原始请求：{query}\n\n候选回答：\n{numbered}"),
            ])
            content = getattr(response, "content", None)
            if content:
                return content
            return "\n\n---\n\n".join(answers)
        except Exception:
            logger.warning("结果择优聚合失败，降级为拼接", exc_info=True)
            return "\n\n---\n\n".join(answers)

    @staticmethod
    def _thought_sse(result, conversation_id, message_id):
        payload = {
            "id": str(message_id),
            "thought": result.task_id,
            "observation": result.answer,
            "answer": result.answer,
            "conversation_id": str(conversation_id),
            "message_id": str(message_id),
            "latency": 0,
            "total_token_count": 0,
        }
        return f"event: {QueueEvent.AGENT_THOUGHT.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _message_sse(final_answer, conversation_id, message_id, synthesis_meta=None):
        payload = {
            "answer": final_answer or "多智能体执行完成，但未获得有效回答。",
            "id": str(message_id),
            "conversation_id": str(conversation_id),
            "message_id": str(message_id),
        }
        if synthesis_meta:
            for key in ("summary", "confidence", "visible_sources", "user_warnings"):
                value = synthesis_meta.get(key)
                if value is not None and value != "" and value != [] and value != 0:
                    payload[key] = value
        return f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _fallback_sse(conversation_id, message_id):
        payload = {
            "answer": "多智能体执行遇到问题，请稍后重试。",
            "id": str(message_id),
            "conversation_id": str(conversation_id),
            "message_id": str(message_id),
        }
        return f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"
