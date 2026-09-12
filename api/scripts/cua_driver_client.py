"""cua-driver 客户端：供 computer worker 调用后台计算机控制后端。

cua-driver（https://github.com/trycua/cua，MIT）是跨平台后台计算机使用驱动：
- 通过 UIA Invoke / PostMessage 定向到目标 pid，默认 **不抢焦点、不移动真实鼠标**；
- 提供 SOM/AX 元素树 + 截图、element_index 点击、set_value、背景输入等能力。

本模块以子进程方式调用 `cua-driver call <tool>`（JSON 经 stdin 传入），
依赖一个常驻 daemon（`cua-driver serve`）。daemon 由桌面端主进程托管。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from typing import Any

logger = logging.getLogger("cua_driver_client")

CALL_TIMEOUT_SECONDS = 60
ENV_EXE = "CUA_DRIVER_EXE"


def _env(key: str, default: str = "") -> str:
    return str(os.environ.get(key, default) or "").strip()


def resolve_cua_driver_exe() -> str:
    """定位 cua-driver 可执行文件：显式环境变量 > 桌面端捆绑 > 默认安装目录 > PATH。"""
    explicit = _env(ENV_EXE)
    if explicit and os.path.isfile(explicit):
        return explicit

    candidates: list[str] = []
    # 桌面端安装包捆绑位置（extraResources/cua-driver/）
    resources_dir = _env("YUJIANWO_RESOURCES_DIR")
    if resources_dir:
        candidates.append(os.path.join(resources_dir, "cua-driver", "cua-driver.exe"))
    # 脚本旁（开发模式）
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "cua-driver", "cua-driver.exe"))
    # 官方安装器默认位置
    local_appdata = _env("LOCALAPPDATA")
    if local_appdata:
        candidates.append(os.path.join(local_appdata, "Programs", "Cua", "cua-driver", "bin", "cua-driver.exe"))
        candidates.append(os.path.join(local_appdata, "Programs", "trycua", "cua-driver-rs", "bin", "cua-driver.exe"))
    for path in candidates:
        if path and os.path.isfile(path):
            return path

    found = shutil.which("cua-driver")
    return found or ""


def is_available() -> bool:
    """cua-driver 可执行文件是否就位（不代表 daemon 已起）。"""
    return bool(resolve_cua_driver_exe())


def call_tool(tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """调用一个 cua-driver 工具，返回解析后的 JSON。

    失败时返回 ``{"ok": False, "error": ...}``，调用方据此回退 pyautogui。
    """
    exe = resolve_cua_driver_exe()
    if not exe:
        return {"ok": False, "error": "cua-driver 未安装"}
    payload = json.dumps(args or {}, ensure_ascii=False).encode("utf-8")
    try:
        completed = subprocess.run(
            [exe, "call", tool],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=CALL_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return {"ok": False, "error": f"cua-driver 可执行文件不存在: {exe}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"cua-driver 调用超时（{tool}）"}
    except Exception as exc:  # noqa: BLE001 - 客户端异常一律转为结构化错误
        return {"ok": False, "error": f"cua-driver 调用失败: {exc}"}

    stdout = (completed.stdout or b"").decode("utf-8", errors="replace").strip()
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
    if completed.returncode != 0:
        detail = stderr or stdout or f"退出码 {completed.returncode}"
        return {"ok": False, "error": f"cua-driver {tool} 失败: {detail}"}
    if not stdout:
        return {"ok": True, "result": {}}
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return {"ok": True, "result": {"raw": stdout}}
    if isinstance(parsed, dict):
        return {"ok": True, "result": parsed}
    return {"ok": True, "result": {"value": parsed}}


def daemon_reachable() -> bool:
    """探测 daemon 是否可达（health_report 成功即视为可用）。"""
    result = call_tool("health_report")
    return bool(result.get("ok"))


if __name__ == "__main__":
    # 便于手工诊断：python cua_driver_client.py [tool] [json]
    tool_name = sys.argv[1] if len(sys.argv) > 1 else "health_report"
    args_json = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    print(json.dumps(call_tool(tool_name, args_json), ensure_ascii=False, default=str))
