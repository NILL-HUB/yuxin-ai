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
from internal.entity.execution_orchestration_entity import TaskPlan
from internal.service.agent_task_executor import AgentTaskExecutor
from internal.service.execution_coordinator_service import ExecutionCoordinatorService
from internal.service.executors.task_decomposer import TaskDecomposer
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

_MULTI_AGENT_MODES = {"multi_agent", "multi_agent_parallel", "multi_agent_sequential"}


@inject
@dataclass
class MultiAgentExecutor:
    db: SQLAlchemy
    task_decomposer: TaskDecomposer

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
            coordinator = ExecutionCoordinatorService(executor=executor)
            results = coordinator.execute(plan)

            for result in results:
                yield self._thought_sse(result, conversation_id, message_id)

            final_answer = self._aggregate_results(
                results, plan.aggregation_strategy, llm, query
            )
            yield self._message_sse(final_answer, conversation_id, message_id)
        except Exception as e:
            logger.warning("MultiAgentExecutor 执行失败: %s", e, exc_info=True)
            yield self._fallback_sse(conversation_id, message_id)

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
    def _message_sse(final_answer, conversation_id, message_id):
        payload = {
            "answer": final_answer or "多智能体执行完成，但未获得有效回答。",
            "id": str(message_id),
            "conversation_id": str(conversation_id),
            "message_id": str(message_id),
        }
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
