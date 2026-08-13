"""计算机控制 worker。

在用户授权的主机（桌面端/本地）执行受限的屏幕、鼠标、键盘操作，
用于让 Agent 真正“帮用户干活”：打开应用、点击按钮、输入内容、滚动页面。

安全模型：
- 仅接受 Authorization: Bearer <COMPUTER_CONTROL_TOKEN> 的请求。
- 默认只监听本机回环地址；不提供任意 shell 执行。
- 每个动作都经过白名单/参数范围校验，截图默认不返回内容（可显式请求）。
- 依赖可选：pip install pyautogui pillow（截图需要 Pillow）。
"""

from __future__ import annotations

import argparse
import base64
import hmac
import io
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


logger = logging.getLogger("computer_control_worker")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8767
MAX_TEXT_LENGTH = 2000
MAX_COORDINATE = 100000
MAX_ACTIONS = 50

_ALLOWED_ACTIONS = frozenset({"move", "click", "scroll", "type", "press", "hotkey", "screenshot"})
_ALLOWED_KEYS = frozenset(
    {
        "enter", "tab", "esc", "escape", "space", "backspace", "delete",
        "ctrl", "control", "alt", "shift", "win", "cmd", "home", "end",
        "pageup", "pagedown", "insert",
        "up", "down", "left", "right",
        *(f"f{i}" for i in range(1, 25)),
        *(str(i) for i in range(10)),
        *(chr(code) for code in range(ord("a"), ord("z") + 1)),
    }
)


def _env(key: str, default: str = "") -> str:
    return str(os.environ.get(key, default) or "").strip()


def _validate_actions(actions: Any) -> tuple[list[dict[str, Any]], str]:
    """校验动作序列，返回 (规范化动作, 错误信息)。"""
    if not isinstance(actions, list) or not actions:
        return [], "actions 不能为空"
    if len(actions) > MAX_ACTIONS:
        return [], f"actions 数量超过上限 {MAX_ACTIONS}"
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(actions):
        if not isinstance(raw, dict):
            return [], f"actions[{index}] 必须是对象"
        action = str(raw.get("action") or "").strip().lower()
        if action not in _ALLOWED_ACTIONS:
            return [], f"不支持的计算机操作: {action}"
        item: dict[str, Any] = {"action": action}
        if action in {"move", "click"}:
            try:
                x = int(raw.get("x"))
                y = int(raw.get("y"))
            except (TypeError, ValueError):
                return [], f"{action} 需要整数 x/y"
            if abs(x) > MAX_COORDINATE or abs(y) > MAX_COORDINATE:
                return [], f"{action} 坐标超出范围"
            item["x"] = x
            item["y"] = y
            if action == "click":
                item["button"] = str(raw.get("button") or "left").lower()
                item["clicks"] = max(int(raw.get("clicks") or 1), 1)
        elif action == "scroll":
            try:
                item["amount"] = int(raw.get("amount") or 0)
            except (TypeError, ValueError):
                return [], "scroll 需要整数 amount"
        elif action == "type":
            text = str(raw.get("text") or "")
            if not text:
                return [], "type 需要 text"
            if len(text) > MAX_TEXT_LENGTH:
                return [], f"text 超过长度上限 {MAX_TEXT_LENGTH}"
            item["text"] = text
        elif action == "press":
            key = str(raw.get("key") or "").strip().lower()
            if key not in _ALLOWED_KEYS:
                return [], f"不支持的按键: {key}"
            item["key"] = key
        elif action == "hotkey":
            keys = raw.get("keys") or []
            if not isinstance(keys, list) or not keys:
                return [], "hotkey 需要 keys 列表"
            normalized_keys: list[str] = []
            for key in keys:
                normalized_key = str(key or "").strip().lower()
                if normalized_key not in _ALLOWED_KEYS:
                    return [], f"不支持的按键: {normalized_key}"
                normalized_keys.append(normalized_key)
            item["keys"] = normalized_keys
        elif action == "screenshot":
            item["return_base64"] = bool(raw.get("return_base64"))
        normalized.append(item)
    return normalized, ""


def _run_actions(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """执行已校验的计算机动作序列。"""
    try:
        import pyautogui
    except ImportError:
        return {
            "ok": False,
            "error": "计算机控制 worker 未安装 pyautogui，请先安装 pyautogui 与 pillow",
        }
    pyautogui.FAILSAFE = True
    results: list[dict[str, Any]] = []
    screenshot_base64 = ""
    try:
        for item in actions:
            action = item["action"]
            if action == "move":
                pyautogui.moveTo(item["x"], item["y"], duration=0.15)
                results.append({"action": action, "ok": True})
            elif action == "click":
                pyautogui.click(item["x"], item["y"], button=item["button"], clicks=item["clicks"])
                results.append({"action": action, "ok": True})
            elif action == "scroll":
                pyautogui.scroll(item["amount"])
                results.append({"action": action, "ok": True})
            elif action == "type":
                pyautogui.typewrite(item["text"], interval=0.01)
                results.append({"action": action, "ok": True})
            elif action == "press":
                pyautogui.press(item["key"])
                results.append({"action": action, "ok": True})
            elif action == "hotkey":
                pyautogui.hotkey(*item["keys"])
                results.append({"action": action, "ok": True})
            elif action == "screenshot":
                image = pyautogui.screenshot()
                if item.get("return_base64"):
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    screenshot_base64 = base64.b64encode(buffer.getvalue()).decode("ascii")
                results.append({"action": action, "ok": True, "width": image.width, "height": image.height})
    except Exception as exc:
        logger.warning("计算机动作执行失败", exc_info=True)
        return {"ok": False, "error": f"计算机动作执行失败: {exc}", "results": results}
    return {"ok": True, "results": results, "screenshot_base64": screenshot_base64}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _authorized(self) -> bool:
        expected = _env("COMPUTER_CONTROL_TOKEN")
        if not expected:
            return False
        header = str(self.headers.get("Authorization", ""))
        if not header.lower().startswith("bearer "):
            return False
        return hmac.compare_digest(header[7:].strip(), expected)

    def do_POST(self):
        if self.path.rstrip("/") != "/control":
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
        actions, error = _validate_actions(payload.get("actions"))
        if error:
            self._json_response({"ok": False, "error": error}, status=400)
            return
        self._json_response(_run_actions(actions))

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Computer control worker")
    parser.add_argument("--host", default=_env("COMPUTER_CONTROL_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(_env("COMPUTER_CONTROL_PORT", str(DEFAULT_PORT))))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    if not _env("COMPUTER_CONTROL_TOKEN"):
        logger.error("COMPUTER_CONTROL_TOKEN 未配置，拒绝启动")
        raise SystemExit(1)
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    logger.info("Computer control worker listening on %s:%s", args.host, args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
