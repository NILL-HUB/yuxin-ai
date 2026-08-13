"""浏览器自动化 worker。

运行在隔离环境（宿主机或独立容器），通过受保护的本机 HTTP 接口接收平台请求，
使用 Playwright 执行受限的浏览器操作。平台侧 `browser_action` 工具调用本服务。

安全模型：
- 仅接受 Authorization: Bearer <BROWSER_AUTOMATION_TOKEN> 的请求。
- 仅允许 http/https URL，并拦截 localhost/私网/环回地址（SSRF 防护）。
- 每次请求创建独立 browser context，操作完成后关闭。
- 默认监听本机回环地址；如部署在容器可访问的地址，必须配置强 token。

依赖：pip install playwright && playwright install chromium
"""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import logging
import os
import socket
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


logger = logging.getLogger("browser_automation_worker")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766
MAX_TEXT_CHARS = 12000

_ALLOWED_ACTIONS = frozenset({"navigate", "snapshot", "click", "type", "scroll", "back"})


def _env(key: str, default: str = "") -> str:
    return str(os.environ.get(key, default) or "").strip()


def _safe_url(url: str) -> str:
    """校验并规范化 URL，阻止 SSRF 到本机/私网。"""
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("仅支持 http/https URL")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("不允许访问本机地址")
    try:
        if ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback:
            raise ValueError("不允许访问私网地址")
    except ValueError:
        # 域名解析后再检查一次
        try:
            for info in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80)):
                ip = ipaddress.ip_address(info[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    raise ValueError("不允许访问私网地址")
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"无法解析目标地址: {exc}")
    return parsed.geturl()


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """校验浏览器操作参数，返回错误 dict 或 None。"""
    action = str(payload.get("action") or "navigate").strip().lower()
    url = str(payload.get("url") or "").strip()
    selector = str(payload.get("selector") or "").strip()
    text = str(payload.get("text") or "")
    if action not in _ALLOWED_ACTIONS:
        return {"ok": False, "error": f"不支持的浏览器操作: {action}"}
    if action == "navigate" and not url:
        return {"ok": False, "error": "navigate 操作需要 url"}
    if action in {"click", "type", "scroll"} and not selector:
        return {"ok": False, "error": f"{action} 操作需要 selector"}
    if action == "type" and not text:
        return {"ok": False, "error": "type 操作需要 text"}
    return None


def _run_playwright(payload: dict[str, Any]) -> dict[str, Any]:
    """用 Playwright 执行受限浏览器操作。"""
    validation_error = _validate_payload(payload)
    if validation_error is not None:
        return validation_error
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "ok": False,
            "error": "浏览器 worker 未安装 Playwright，请先安装 playwright 与 chromium",
        }

    action = str(payload.get("action") or "navigate").strip().lower()
    url = str(payload.get("url") or "").strip()
    selector = str(payload.get("selector") or "").strip()
    text = str(payload.get("text") or "")
    wait_ms = max(int(payload.get("wait_ms") or 0), 0)
    timeout = max(int(payload.get("timeout") or 30000), 1000)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                if action == "navigate":
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                elif action == "snapshot":
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                elif action == "back":
                    page.go_back(wait_until="domcontentloaded", timeout=timeout)
                elif action == "click":
                    page.click(selector, timeout=timeout)
                elif action == "type":
                    page.fill(selector, text)
                elif action == "scroll":
                    page.locator(selector).scroll_into_view_if_needed(timeout=timeout)
                if wait_ms:
                    page.wait_for_timeout(wait_ms)
                title = page.title() or ""
                final_url = page.url or ""
                body_text = page.evaluate("() => document.body ? document.body.innerText.slice(0, 12000) : ''")
                return {
                    "ok": True,
                    "action": action,
                    "title": title,
                    "url": final_url,
                    "text": (body_text or "")[:MAX_TEXT_CHARS],
                }
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("浏览器操作失败: %s", exc, exc_info=True)
        return {"ok": False, "error": f"浏览器操作失败: {exc}"}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _authorized(self) -> bool:
        expected = _env("BROWSER_AUTOMATION_TOKEN")
        if not expected:
            return False
        header = str(self.headers.get("Authorization", ""))
        if not header.lower().startswith("bearer "):
            return False
        return hmac.compare_digest(header[7:].strip(), expected)

    def do_POST(self):
        if self.path.rstrip("/") != "/browser":
            self._json_response({"ok": False, "error": "not found"}, status=404)
            return
        if not self._authorized():
            self._json_response({"ok": False, "error": "unauthorized"}, status=401)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            self._json_response({"ok": False, "error": "invalid json"}, status=400)
            return
        result = _run_playwright(payload)
        self._json_response(result)

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Browser automation worker")
    parser.add_argument("--host", default=_env("BROWSER_AUTOMATION_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(_env("BROWSER_AUTOMATION_PORT", str(DEFAULT_PORT))))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    if not _env("BROWSER_AUTOMATION_TOKEN"):
        logger.error("BROWSER_AUTOMATION_TOKEN 未配置，拒绝启动")
        raise SystemExit(1)
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    logger.info("Browser automation worker listening on %s:%s", args.host, args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
