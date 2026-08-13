import json

from internal.core.agent.adapters.hermes.a2a_protocol import (
    build_agent_card,
    build_task,
    extract_text,
    jsonrpc_error,
    jsonrpc_result,
    send_message_response,
    text_message,
)


def test_agent_card_shape():
    card = build_agent_card(
        name="Yuxin Gateway",
        url="http://localhost/a2a",
        description="test",
        skills=[{"id": "agent.x", "name": "x", "description": "x", "tags": ["x"]}],
    )
    assert card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
    assert card["capabilities"]["streaming"] is False
    assert card["skills"][0]["id"] == "agent.x"


def test_extract_text_v10():
    params = {
        "message": {
            "role": "ROLE_USER",
            "parts": [{"text": "帮我清理 C 盘", "mediaType": "text/plain"}],
        }
    }
    assert extract_text(params) == "帮我清理 C 盘"


def test_extract_text_v03_kind():
    params = {
        "message": {
            "parts": [{"kind": "text", "text": "legacy"}],
        }
    }
    assert extract_text(params) == "legacy"


def test_jsonrpc_framing():
    result = jsonrpc_result("1", {"ok": True})
    assert result["jsonrpc"] == "2.0"
    assert result["result"]["ok"] is True
    error = jsonrpc_error("1", -32001, "task not found")
    assert error["error"]["code"] == -32001


def test_send_message_response_wraps_task():
    task = build_task(task_id="task-1", status="TASK_STATE_COMPLETED")
    assert send_message_response(task) == {"task": task}


def test_text_message_has_part():
    msg = text_message("ROLE_AGENT", "hello")
    assert msg["parts"][0]["text"] == "hello"


def test_task_json_serializable():
    task = build_task(
        task_id="task-1",
        status="TASK_STATE_COMPLETED",
        messages=[text_message("ROLE_AGENT", "ok")],
    )
    assert json.loads(json.dumps(task))
