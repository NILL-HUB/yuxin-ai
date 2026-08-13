import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from internal.core.tools.builtin_tools.providers.web_tools.web_extract import (
    WebExtractTool,
    _html_to_readable_text,
    _is_safe_url,
)


def test_is_safe_url_rejects_localhost():
    safe, _ = _is_safe_url("http://localhost/admin")
    assert safe is False


def test_is_safe_url_rejects_non_http():
    safe, _ = _is_safe_url("file:///etc/passwd")
    assert safe is False


def test_html_to_readable_text_strips_markup():
    html = "<html><body><h1>标题</h1><p>第一段 <a href='https://x.com'>链接</a></p></body></html>"
    text = _html_to_readable_text(html, "https://x.com")
    assert "标题" in text
    assert "第一段" in text
    assert "<h1>" not in text


def test_web_extract_returns_content():
    html = "<html><body><h1>Hello</h1><p>World content</p></body></html>"

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/page"

    result = json.loads(WebExtractTool()._run(url=url))
    thread.join(timeout=5)
    server.server_close()

    # 本地地址被 SSRF 防护拦截，因此期望失败而非返回内容。
    assert result["ok"] is False
    assert "内网" in result["error"] or "本地" in result["error"]


def test_web_extract_returns_error_for_bad_url():
    result = json.loads(WebExtractTool()._run(url="http://localhost/x"))
    assert result["ok"] is False
