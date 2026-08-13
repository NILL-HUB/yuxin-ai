"""A2A v1.0 协议工具（JSON-RPC 2.0 绑定）。

协议形状对齐 NousResearch/hermes-agent `plugins/platforms/a2a/protocol.py`
（MIT License）：Agent Card、JSON-RPC 帧、Task/Message/Part 结构、
文本提取。仅保留文本任务交换所需子集，不依赖 a2a-sdk。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any

PROTOCOL_VERSION = "1.0"

STATE_SUBMITTED = "TASK_STATE_SUBMITTED"
STATE_WORKING = "TASK_STATE_WORKING"
STATE_COMPLETED = "TASK_STATE_COMPLETED"
STATE_FAILED = "TASK_STATE_FAILED"
STATE_INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
STATE_CANCELED = "TASK_STATE_CANCELED"

ROLE_USER = "ROLE_USER"
ROLE_AGENT = "ROLE_AGENT"

ERR_PARSE = -32700
ERR_INVALID_PARAMS = -32602
ERR_METHOD_NOT_FOUND = -32601
ERR_TASK_NOT_FOUND = -32001
ERR_UNAUTHORIZED = -32050


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def jsonrpc_result(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def jsonrpc_error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def text_part(text: str) -> dict:
    return {"text": text, "mediaType": "text/plain"}


def build_agent_card(
    *,
    name: str,
    url: str,
    description: str,
    skills: list[dict] | None = None,
    auth_required: bool = False,
) -> dict:
    iface: dict[str, Any] = {
        "url": url,
        "protocolBinding": "JSONRPC",
        "protocolVersion": PROTOCOL_VERSION,
    }
    card: dict[str, Any] = {
        "name": name,
        "description": description,
        "url": url,
        "version": "1.0.0",
        "provider": {
            "organization": os.getenv("A2A_PROVIDER_ORG", "Yuxin AI"),
            "url": os.getenv("A2A_PROVIDER_URL", "") or url,
        },
        "supportedInterfaces": [iface],
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
            "extendedAgentCard": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": skills or [],
    }
    if auth_required:
        card["securitySchemes"] = {"bearer": {"type": "http", "scheme": "bearer"}}
        card["security"] = [{"bearer": []}]
    return card


def skills_from_agent_names(agent_names: list[str]) -> list[dict]:
    """把公共 Agent 列表渲染成 A2A Skill 描述，便于对端发现。"""
    if not agent_names:
        return [
            {
                "id": "general",
                "name": "general",
                "description": "General-purpose conversational agent",
                "tags": ["general"],
            }
        ]
    return [
        {
            "id": f"agent.{name}",
            "name": name,
            "description": f"Yuxin AI public agent: {name}",
            "tags": [name],
        }
        for name in agent_names[:50]
    ]


def extract_text(message_or_params: dict) -> str:
    """从 A2A Message / params 中提取文本（兼容 v1.0 与 v0.3 Part 形状）。"""
    msg = message_or_params.get("message", message_or_params)
    parts = msg.get("parts", []) if isinstance(msg, dict) else []
    chunks: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        txt = part.get("text")
        if isinstance(txt, str):
            chunks.append(txt)
            continue
        if part.get("kind") == "text" and isinstance(part.get("text"), str):
            chunks.append(part["text"])
            continue
        url = part.get("url")
        if isinstance(url, str) and url:
            fname = part.get("filename") or ""
            label = f"[file: {fname}]" if fname else "[file]"
            chunks.append(f"{label} {url}")
            continue
        data = part.get("data")
        if data is not None:
            try:
                rendered = json.dumps(data, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                rendered = str(data)
            chunks.append(f"[data]\n{rendered}")
    return "\n".join(chunks).strip()


def text_message(role: str, text: str, context_id: str = "") -> dict:
    msg: dict[str, Any] = {
        "role": role,
        "parts": [text_part(text)],
        "messageId": uuid.uuid4().hex,
    }
    if context_id:
        msg["contextId"] = context_id
    return msg


def build_task(
    *,
    task_id: str,
    status: str,
    messages: list[dict] | None = None,
    error: str = "",
    artifact: dict | None = None,
) -> dict:
    task: dict[str, Any] = {
        "id": task_id,
        "status": {"state": status},
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    if messages:
        task["messages"] = messages
    if error:
        task["status"]["message"] = {"role": ROLE_AGENT, "parts": [text_part(error)]}
    if artifact is not None:
        task["artifacts"] = [artifact]
    return task


def send_message_response(payload: dict) -> dict:
    """A2A v1.0 SendMessageResponse：task/message oneof 包装。"""
    if isinstance(payload, dict) and payload.get("id") and payload.get("status"):
        return {"task": payload}
    return {"message": payload}


def parse_message_send_params(params: dict) -> dict:
    """解析 message/send 入参，返回 (text, context_id)。"""
    message = params.get("message") or {}
    context_id = str(message.get("contextId") or params.get("contextId") or "")
    return {
        "text": extract_text(params),
        "context_id": context_id,
    }


def parse_task_id_params(params: dict) -> str:
    """解析 tasks/get / tasks/cancel 的 id 参数。"""
    task_id = (params or {}).get("id")
    if task_id is None:
        task_id = (params or {}).get("taskId")
    return str(task_id or "").strip()


def unwrap_send_message_text(result: Any) -> str:
    """从 message/send 响应中提取最终文本（兼容 task/message 包装）。"""
    if isinstance(result, dict):
        task = result.get("task")
        if isinstance(task, dict):
            messages = task.get("messages") or []
            if messages:
                return extract_text({"message": messages[-1]})
            status = task.get("status") or {}
            if isinstance(status, dict) and isinstance(status.get("message"), dict):
                return extract_text({"message": status["message"]})
        message = result.get("message")
        if isinstance(message, dict):
            return extract_text({"message": message})
        if "error" in result:
            return f"ERROR: {result['error']}"
    return str(result)
