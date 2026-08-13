"""Codex OS 自动化全链路 E2E 测试。

流程：
1. 在随机端口启动宿主机 OS automation worker（当前进程内）。
2. GET /health 验证 worker 与 Codex 可用。
3. POST /run preview，让 Codex 只读分析并返回 approval_token。
4. POST /run apply，使用同一个 approval_token 在临时目录执行真实写文件任务。
5. 校验文件存在并清理临时目录。

用法：
  $env:OS_AUTOMATION_TOKEN="..." ; $env:CODEX_CLI_PATH="..." ; python api/scripts/test_os_automation_e2e.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.os_automation_worker import OsAutomationHandler


def _request(url: str, payload: dict | None = None, token: str = "") -> dict:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method="GET" if payload is None else "POST",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=700) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    token = os.environ.get("OS_AUTOMATION_TOKEN", "").strip()
    if not token:
        print("OS_AUTOMATION_TOKEN 未配置", file=sys.stderr)
        return 2

    server = ThreadingHTTPServer(("127.0.0.1", 0), OsAutomationHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"

    try:
        health = _request(f"{base_url}/health", token=token)
        print("health:", json.dumps(health, ensure_ascii=False), flush=True)
        if not health.get("codex_path"):
            print("Codex CLI 不可用", file=sys.stderr)
            return 1

        preview = _request(
            f"{base_url}/run",
            {
                "task": "输出 C 盘剩余空间，不要修改任何文件",
                "mode": "preview",
                "timeout": 120,
            },
            token=token,
        )
        print("preview:", json.dumps(preview, ensure_ascii=False), flush=True)
        approval_token = preview.get("approval_token", "")
        if not preview.get("ok") or not approval_token:
            print("preview 未返回 approval_token", file=sys.stderr)
            return 1

        workdir = Path(tempfile.mkdtemp(prefix="yuxin_os_automation_e2e_"))
        try:
            apply_result = _request(
                f"{base_url}/run",
                {
                    "task": "在当前目录创建 probe.txt，文件内容为 os-automation-ok；不要修改其他文件",
                    "mode": "apply",
                    "approval_token": approval_token,
                    "working_dir": str(workdir),
                    "timeout": 120,
                },
                token=token,
            )
            print("apply:", json.dumps(apply_result, ensure_ascii=False), flush=True)
            probe = workdir / "probe.txt"
            if not apply_result.get("ok") or not probe.is_file():
                print("apply 未生成 probe.txt", file=sys.stderr)
                return 1
            if probe.read_text(encoding="utf-8").strip() != "os-automation-ok":
                print("probe.txt 内容不正确", file=sys.stderr)
                return 1
            print("E2E PASS")
            return 0
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
