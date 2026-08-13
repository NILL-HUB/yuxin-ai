"""A2A v1.0 网关服务。

把 A2A JSON-RPC 请求接到现有公共 Agent 路由（`PublicAgentA2AService`），
让外部 A2A 对端可以“发现”钰心AI 的公共 Agent 并委派消息。
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from injector import inject

from internal.core.agent.adapters.hermes.a2a_protocol import (
    STATE_CANCELED,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_WORKING,
    build_agent_card,
    build_task,
    parse_message_send_params,
    parse_task_id_params,
    send_message_response,
    skills_from_agent_names,
    text_message,
)

logger = logging.getLogger(__name__)


@inject
@dataclass
class A2AGatewayService:
    """A2A 入站网关。"""

    public_agent_a2a_service: Any = None
    public_agent_registry_service: Any = None

    def __post_init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _resolve_public_agent_service(self):
        if self.public_agent_a2a_service is not None:
            return self.public_agent_a2a_service
        from app.http.module import injector
        from internal.service.public_agent_a2a_service import PublicAgentA2AService

        return injector.get(PublicAgentA2AService)

    def get_agent_card(self, *, base_url: str) -> dict:
        """生成 A2A v1.0 Agent Card，技能列表来自公共 Agent 名称。"""
        agent_names: list[str] = []
        registry = self.public_agent_registry_service
        if registry is not None and hasattr(registry, "search_public_agents"):
            try:
                docs = registry.search_public_agents("", limit=50)
                for doc in docs or []:
                    name = (
                        doc.get("name")
                        if isinstance(doc, dict)
                        else getattr(doc, "name", "")
                    )
                    if name:
                        agent_names.append(str(name))
            except Exception:
                logger.warning("读取公共 Agent 列表用于 A2A Agent Card 失败", exc_info=True)
        return build_agent_card(
            name="Yuxin AI Gateway",
            url=base_url.rstrip("/") + "/a2a",
            description="Yuxin AI public agent routing gateway (A2A v1.0)",
            skills=skills_from_agent_names(agent_names),
        )

    def handle_message_send(self, req_id: Any, params: dict) -> dict:
        """处理 message/send：提取文本，委派公共 Agent，返回 Task。"""
        try:
            parsed = parse_message_send_params(params)
        except Exception:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "invalid params"}}
        query = parsed["text"]
        if not query:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "message text is empty"}}

        task_id = "task-" + uuid.uuid4().hex[:16]
        with self._lock:
            self._tasks[task_id] = {"state": STATE_WORKING, "query": query}
        try:
            service = self._resolve_public_agent_service()
            result = service.route_public_agents(
                query=query,
                caller_account_id=uuid.UUID(int=0),
                limit=3,
            )
            answer = self._format_result(result)
            task = build_task(
                task_id=task_id,
                status=STATE_COMPLETED,
                messages=[text_message("ROLE_AGENT", answer)],
            )
            with self._lock:
                self._tasks[task_id]["state"] = STATE_COMPLETED
            return {"jsonrpc": "2.0", "id": req_id, "result": send_message_response(task)}
        except Exception as exc:
            logger.exception("A2A message/send 委派失败")
            with self._lock:
                self._tasks[task_id]["state"] = STATE_FAILED
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": send_message_response(
                    build_task(task_id=task_id, status=STATE_FAILED, error=str(exc))
                ),
            }

    def handle_tasks_get(self, req_id: Any, params: dict) -> dict:
        task_id = parse_task_id_params(params)
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32001, "message": "task not found"}}
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": build_task(
                task_id=task_id,
                status=task.get("state", "TASK_STATE_WORKING"),
            ),
        }

    def handle_tasks_cancel(self, req_id: Any, params: dict) -> dict:
        """处理 A2A tasks/cancel：取消正在运行的公共 Agent 任务。"""
        task_id = parse_task_id_params(params)
        if not task_id:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": "task id is empty"},
            }
        cancelled = False
        try:
            service = self._resolve_public_agent_service()
            if hasattr(service, "cancel_task"):
                cancelled = bool(service.cancel_task(task_id))
        except Exception:
            logger.warning("A2A tasks/cancel 委派取消失败: %s", task_id, exc_info=True)

        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                if cancelled or task.get("state") == STATE_WORKING:
                    task["state"] = STATE_CANCELED

        if cancelled:
            final_state = STATE_CANCELED
        elif task is not None:
            final_state = task.get("state", STATE_WORKING)
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32001, "message": "task not found"},
            }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": send_message_response(
                build_task(task_id=task_id, status=final_state)
            ),
        }

    def handle_message_stream(self, req_id: Any, params: dict) -> dict:
        """处理 message/stream：与 message/send 相同委派，返回最终 Task。"""
        response = self.handle_message_send(req_id, params)
        if response.get("error"):
            return response
        return response

    @staticmethod
    def _format_result(result: dict) -> str:
        if not isinstance(result, dict):
            return str(result)
        delegated = result.get("delegated_results") or []
        parts = []
        for item in delegated:
            if isinstance(item, dict):
                answer = item.get("answer") or item.get("result") or item.get("output") or ""
                agent_name = item.get("agent_name") or item.get("app_name") or ""
                if answer:
                    parts.append(f"[{agent_name}]\n{answer}".strip())
        if parts:
            return "\n\n".join(parts)
        message = result.get("message") or result.get("summary") or ""
        return str(message or "A2A gateway received the request but produced no answer.")

    def create_outbound_send_tool(self) -> Any:
        """创建 A2A 出站工具：让 Agent 主动调用外部 A2A 对端。"""
        from langchain_core.tools import tool
        from pydantic import BaseModel, Field

        class A2ASendInput(BaseModel):
            endpoint: str = Field(description="外部 A2A JSON-RPC 端点 URL（如 https://host/a2a）")
            text: str = Field(description="发送给对端 Agent 的文本消息")

        @tool("a2a_send_message", args_schema=A2ASendInput)
        def a2a_send_message(endpoint: str, text: str) -> str:
            """向外部 A2A Agent 发送消息并返回其回复。用于与其他 Agent 系统互操作。"""
            from internal.core.agent.adapters.hermes.a2a_client import send_message_text

            return send_message_text(endpoint, text)

        return a2a_send_message
