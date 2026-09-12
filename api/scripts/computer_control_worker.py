"""计算机控制 worker。

在用户授权的主机（桌面端/本地）执行受限的屏幕、鼠标、键盘操作，
用于让 Agent 真正“帮用户干活”：打开应用、点击按钮、输入内容、滚动页面。

双后端：
- **cua-driver 后端（默认优先）**：后台定向控制，不抢焦点、不移动真实鼠标，
  按 pid/window_id + element_index 走 UIA Invoke/PostMessage；需常驻 daemon。
- **pyautogui 后端（fallback）**：前台全局模拟（会抢焦点、动真实光标）。

后端选择：``COMPUTER_CONTROL_BACKEND`` = ``auto``（默认，cua 可用则用 cua）/
``cua`` / ``pyautogui``；每个动作亦可用 ``backend`` 字段显式覆盖。

安全模型：
- 仅接受 Authorization: Bearer <COMPUTER_CONTROL_TOKEN> 的请求。
- 默认只监听本机回环地址；不提供任意 shell 执行。
- 每个动作都经过白名单/参数范围校验，截图默认不返回内容（可显式请求）。
- cua-driver 依赖：需已安装并运行 daemon（桌面端主进程托管）。
- pyautogui 依赖可选：pip install pyautogui pillow（截图需要 Pillow）。
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

try:
    from scripts import cua_driver_client
except ImportError:  # PyInstaller / 直接脚本运行场景
    import cua_driver_client  # type: ignore


logger = logging.getLogger("computer_control_worker")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8767
MAX_TEXT_LENGTH = 2000
MAX_COORDINATE = 100000
MAX_ACTIONS = 50

# 前台全局模拟动作（pyautogui 后端）
_FOREGROUND_ACTIONS = frozenset({"move", "click", "scroll", "type", "press", "hotkey", "screenshot"})
# 仅 cua-driver 提供的能力（后台 / 应用管理 / 元素树）
_CUA_ONLY_ACTIONS = frozenset(
    {"capture", "list_apps", "list_windows", "launch_app", "double_click", "right_click", "drag", "set_value"}
)
_ALLOWED_ACTIONS = _FOREGROUND_ACTIONS | _CUA_ONLY_ACTIONS
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


def _resolve_backend(explicit: str = "") -> str:
    """解析生效后端：explicit > COMPUTER_CONTROL_BACKEND > auto。

    auto：cua-driver 可执行文件存在且 daemon 可达时用 cua，否则 pyautogui。
    """
    requested = (explicit or _env("COMPUTER_CONTROL_BACKEND", "auto")).strip().lower()
    if requested in {"cua", "pyautogui"}:
        return requested
    # auto
    if cua_driver_client.is_available():
        try:
            if cua_driver_client.daemon_reachable():
                return "cua"
        except Exception:  # noqa: BLE001 - 探测失败按不可用处理
            logger.warning("cua-driver daemon 探测失败，回退 pyautogui", exc_info=True)
    return "pyautogui"


def _cua_targeted(raw: dict[str, Any]) -> bool:
    """该动作是否带 cua 定向参数（pid/window_id/element_index/element_token）。"""
    return any(
        raw.get(key) not in (None, "")
        for key in ("pid", "window_id", "element_index", "element_token")
    )


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
        # 通用可选字段：后端与 cua 定向参数（pid/window_id/element_token/delivery_mode）
        backend = str(raw.get("backend") or "").strip().lower()
        if backend:
            if backend not in {"cua", "pyautogui"}:
                return [], f"不支持的后端: {backend}"
            item["backend"] = backend
        for key in ("pid", "window_id", "element_index", "element_token", "delivery_mode", "app", "direction", "by"):
            value = raw.get(key)
            if value not in (None, ""):
                item[key] = value
        if action in {"move", "click", "double_click", "right_click"}:
            has_element = raw.get("element_index") is not None or raw.get("element_token")
            if has_element:
                # cua 元素寻址：不需要 x/y
                if action == "click":
                    item["button"] = str(raw.get("button") or "left").lower()
            else:
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
        elif action == "drag":
            for coord_key in ("from_x", "from_y", "to_x", "to_y"):
                if raw.get(coord_key) is None:
                    continue
                try:
                    item[coord_key] = int(raw[coord_key])
                except (TypeError, ValueError):
                    return [], f"drag 的 {coord_key} 需要整数"
            if not any(k in item for k in ("from_x", "to_x")) and not (
                raw.get("from_element") is not None or raw.get("from_element_token")
            ):
                return [], "drag 需要 from/to 坐标或元素"
        elif action == "set_value":
            if raw.get("value") is None:
                return [], "set_value 需要 value"
            item["value"] = raw.get("value")
        elif action == "launch_app":
            if not any(raw.get(k) for k in ("name", "path", "aumid", "bundle_id")):
                return [], "launch_app 需要 name/path/aumid/bundle_id"
            for key in ("name", "path", "aumid", "bundle_id"):
                if raw.get(key):
                    item[key] = raw[key]
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
        elif action == "capture":
            # cua：绑定窗口的元素树 + 截图（可选仅元素树 / 仅截图）
            item["include_screenshot"] = raw.get("include_screenshot", True)
            item["include_accessibility_tree"] = raw.get("include_accessibility_tree", True)
        normalized.append(item)
    return normalized, ""


def _cua_args(item: dict[str, Any], *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """从规范化动作中提取 cua-driver 目标参数（pid/window_id/element*）。"""
    args: dict[str, Any] = {}
    for key in ("pid", "window_id", "element_index", "element_token", "delivery_mode", "app", "direction", "by"):
        if item.get(key) not in (None, ""):
            args[key] = item[key]
    if extra:
        args.update(extra)
    return args


def _run_cua_action(item: dict[str, Any]) -> dict[str, Any]:
    """执行单个动作（cua-driver 后端）。返回结果片段或错误。"""
    action = item["action"]
    if action == "capture":
        return cua_driver_client.call_tool(
            "get_window_state",
            _cua_args(
                item,
                extra={
                    "include_screenshot": item.get("include_screenshot", True),
                    "include_accessibility_tree": item.get("include_accessibility_tree", True),
                },
            ),
        )
    if action == "list_apps":
        return cua_driver_client.call_tool("list_apps", {})
    if action == "list_windows":
        return cua_driver_client.call_tool("list_windows", _cua_args(item))
    if action == "launch_app":
        extra: dict[str, Any] = {}
        for key in ("name", "path", "aumid", "bundle_id"):
            if item.get(key):
                extra[key] = item[key]
        return cua_driver_client.call_tool("launch_app", extra)
    if action in {"click", "double_click", "right_click"}:
        tool = {"click": "click", "double_click": "double_click", "right_click": "right_click"}[action]
        extra = {}
        if action == "click":
            if item.get("button"):
                extra["button"] = item["button"]
            if item.get("clicks"):
                extra["count"] = item["clicks"]
        if "element_index" not in item and "element_token" not in item:
            extra["x"] = item["x"]
            extra["y"] = item["y"]
        return cua_driver_client.call_tool(tool, _cua_args(item, extra=extra))
    if action == "move":
        args = _cua_args(item, extra={"x": item["x"], "y": item["y"]})
        return cua_driver_client.call_tool("move_cursor", args)
    if action == "drag":
        extra = {}
        for key in ("from_x", "from_y", "to_x", "to_y"):
            if item.get(key) is not None:
                extra[key] = item[key]
        return cua_driver_client.call_tool("drag", _cua_args(item, extra=extra))
    if action == "scroll":
        direction = str(item.get("direction") or "down").lower()
        extra = {"amount": item.get("amount") or 3}
        if item.get("by"):
            extra["by"] = item["by"]
        return cua_driver_client.call_tool(f"scroll_{direction}", _cua_args(item, extra=extra))
    if action == "type":
        return cua_driver_client.call_tool("type_text", _cua_args(item, extra={"text": item["text"]}))
    if action == "press":
        return cua_driver_client.call_tool("press_key", _cua_args(item, extra={"key": item["key"]}))
    if action == "hotkey":
        return cua_driver_client.call_tool("hotkey", _cua_args(item, extra={"keys": item["keys"]}))
    if action == "set_value":
        return cua_driver_client.call_tool("set_value", _cua_args(item, extra={"value": item["value"]}))
    if action == "screenshot":
        return cua_driver_client.call_tool("get_desktop_state", {})
    return {"ok": False, "error": f"cua 后端不支持的动作: {action}"}


def _run_actions_cua(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """cua-driver 后端：后台定向控制，不抢焦点、不移动真实鼠标。"""
    results: list[dict[str, Any]] = []
    screenshot_base64 = ""
    for item in actions:
        outcome = _run_cua_action(item)
        if not outcome.get("ok"):
            # background 不可用等结构化拒绝：原样上报，交由上层决定是否升前台
            return {
                "ok": False,
                "error": outcome.get("error") or "cua-driver 动作失败",
                "backend": "cua",
                "results": results + [{"action": item["action"], "ok": False, "detail": outcome}],
            }
        payload = outcome.get("result") or {}
        record: dict[str, Any] = {"action": item["action"], "ok": True, "backend": "cua"}
        if item["action"] == "screenshot":
            b64 = payload.get("screenshot_png_b64") or ""
            if item.get("return_base64"):
                screenshot_base64 = b64
            record["width"] = payload.get("screenshot_width") or payload.get("screen_width")
            record["height"] = payload.get("screenshot_height") or payload.get("screen_height")
        else:
            # 保留 cua 的结构化回执（effect/escalation/delivery 等），供 Agent 判断
            for key in (
                "effect", "escalation", "delivery", "route", "verified", "code",
                "elements", "element_count", "tree_markdown", "app_name", "window_title",
                "pid", "window_id", "running", "active", "name", "bundle_id",
                "windows", "apps", "processes",
                "width", "height", "screen_width", "screen_height",
            ):
                if key in payload:
                    record[key] = payload[key]
            # capture 的截图（仅在显式要求时透传 base64）
            if item["action"] == "capture" and item.get("include_screenshot"):
                b64 = payload.get("screenshot_png_b64")
                if b64 and item.get("return_base64"):
                    screenshot_base64 = b64
        results.append(record)
    return {"ok": True, "backend": "cua", "results": results, "screenshot_base64": screenshot_base64}


def _run_actions_pyautogui(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """pyautogui 后端：前台全局模拟（会抢焦点、移动真实光标）。"""
    try:
        import pyautogui
    except ImportError:
        return {
            "ok": False,
            "error": "计算机控制 worker 未安装 pyautogui，且 cua-driver 后端不可用；"
                     "请安装 cua-driver 或 pip install pyautogui pillow",
        }
    except SystemExit as exc:
        return {
            "ok": False,
            "error": f"计算机控制 worker 初始化失败（可能缺少 tkinter/X 依赖）: {exc}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"计算机控制 worker 初始化失败: {exc}",
        }
    pyautogui.FAILSAFE = True
    results: list[dict[str, Any]] = []
    screenshot_base64 = ""
    try:
        for item in actions:
            action = item["action"]
            if action == "move":
                pyautogui.moveTo(item["x"], item["y"], duration=0.15)
                results.append({"action": action, "ok": True, "backend": "pyautogui"})
            elif action == "click":
                pyautogui.click(item["x"], item["y"], button=item["button"], clicks=item["clicks"])
                results.append({"action": action, "ok": True, "backend": "pyautogui"})
            elif action == "scroll":
                pyautogui.scroll(item["amount"])
                results.append({"action": action, "ok": True, "backend": "pyautogui"})
            elif action == "type":
                pyautogui.typewrite(item["text"], interval=0.01)
                results.append({"action": action, "ok": True, "backend": "pyautogui"})
            elif action == "press":
                pyautogui.press(item["key"])
                results.append({"action": action, "ok": True, "backend": "pyautogui"})
            elif action == "hotkey":
                pyautogui.hotkey(*item["keys"])
                results.append({"action": action, "ok": True, "backend": "pyautogui"})
            elif action == "screenshot":
                image = pyautogui.screenshot()
                if item.get("return_base64"):
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    screenshot_base64 = base64.b64encode(buffer.getvalue()).decode("ascii")
                results.append({
                    "action": action, "ok": True, "backend": "pyautogui",
                    "width": image.width, "height": image.height,
                })
            else:
                return {
                    "ok": False,
                    "error": f"pyautogui 后端不支持的动作: {action}（需 cua-driver 后端）",
                    "backend": "pyautogui",
                    "results": results,
                }
    except Exception as exc:
        logger.warning("计算机动作执行失败", exc_info=True)
        return {"ok": False, "error": f"计算机动作执行失败: {exc}", "backend": "pyautogui", "results": results}
    return {"ok": True, "backend": "pyautogui", "results": results, "screenshot_base64": screenshot_base64}


def _run_actions(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """执行已校验的计算机动作序列（按 backend 路由）。"""
    # 动作含 cua 专有能力，或显式要求 cua，或 auto 解析为 cua → 走 cua 后端
    needs_cua = any(item["action"] in _CUA_ONLY_ACTIONS for item in actions)
    if needs_cua and not cua_driver_client.is_available():
        return {
            "ok": False,
            "error": "该动作需要 cua-driver 后端（后台控制），但未检测到 cua-driver；"
                     "请通过桌面端启动或安装 cua-driver",
        }
    resolved = _resolve_backend()
    # 逐动作路由：允许一序列内混用，但以整体后端为准（显式 backend 优先）
    backend = resolved
    for item in actions:
        if item.get("backend"):
            backend = item["backend"]
            break
    if needs_cua and backend == "pyautogui":
        backend = "cua" if cua_driver_client.is_available() else "pyautogui"
    if backend == "cua":
        return _run_actions_cua(actions)
    return _run_actions_pyautogui(actions)



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
