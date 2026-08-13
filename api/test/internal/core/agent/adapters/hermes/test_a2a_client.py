import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from internal.core.agent.adapters.hermes.a2a_client import (
    fetch_agent_card,
    send_message_text,
)


def test_send_message_text_returns_agent_reply():
    received = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            received["body"] = json.loads(self.rfile.read(length))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "1",
                        "result": {
                            "task": {
                                "id": "task-1",
                                "status": {"state": "TASK_STATE_COMPLETED"},
                                "messages": [
                                    {
                                        "role": "ROLE_AGENT",
                                        "parts": [{"text": "外部回复", "mediaType": "text/plain"}],
                                    }
                                ],
                            }
                        },
                    }
                ).encode("utf-8")
            )

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_address[1]}/a2a"

    result = send_message_text(endpoint, "你好")
    thread.join(timeout=5)
    server.server_close()

    assert result == "外部回复"
    assert received["body"]["method"] == "message/send"
    assert received["body"]["params"]["message"]["parts"][0]["text"] == "你好"


def test_fetch_agent_card():
    card = {
        "name": "Remote",
        "supportedInterfaces": [{"protocolVersion": "1.0"}],
    }

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(card).encode("utf-8"))

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    result = fetch_agent_card(base)
    thread.join(timeout=5)
    server.server_close()

    assert result["name"] == "Remote"


def test_send_message_text_returns_error_on_failure():
    result = send_message_text(
        "http://127.0.0.1:1/a2a",
        "ping",
        timeout=1,
    )
    assert result.startswith("ERROR:")
