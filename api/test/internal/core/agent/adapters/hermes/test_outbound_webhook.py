import base64
import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from internal.core.agent.adapters.hermes.outbound_webhook import (
    build_event,
    deliver_webhook,
    sign_payload,
)


def test_sign_payload_hmac_sha256():
    payload = {"event_type": "tool.confirmed"}
    signature, timestamp = sign_payload(payload, "s3cret")
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    expected = base64.b64encode(
        hmac.new(
            b"s3cret",
            f"{timestamp}.{body}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("ascii")
    assert signature == expected


def test_build_event_envelope():
    event = build_event(
        event_type="tool.confirmed",
        subject_type="tool_confirmation",
        subject_id="conf-1",
        payload={"tool_name": "run_os_task"},
    )
    assert event["event_id"]
    assert event["event_type"] == "tool.confirmed"
    assert event["data"]["tool_name"] == "run_os_task"


def test_deliver_webhook_receives_signed_request():
    received = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            received["body"] = self.rfile.read(length)
            received["signature"] = self.headers.get("X-Webhook-Signature")
            received["timestamp"] = self.headers.get("X-Webhook-Timestamp")
            received["event_id"] = self.headers.get("X-Webhook-Event-Id")
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/hook"
    event = build_event(
        event_type="tool.confirmed",
        subject_type="tool_confirmation",
        subject_id="conf-1",
        payload={"tool_name": "run_os_task"},
    )

    result = deliver_webhook(url, "s3cret", event)
    thread.join(timeout=5)
    server.server_close()

    assert result["ok"] is True
    assert result["event_id"] == event["event_id"]
    assert json.loads(received["body"]) == event
    assert received["event_id"] == event["event_id"]


def test_deliver_webhook_failure_returns_error():
    result = deliver_webhook(
        "http://127.0.0.1:1/hook",
        "s3cret",
        build_event(
            event_type="test",
            subject_type="test",
            subject_id="1",
            payload={},
        ),
        timeout=1,
        max_attempts=1,
    )
    assert result["ok"] is False
    assert result["error"]
