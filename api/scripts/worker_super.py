"""YuxinAI 桌面 worker 统一入口（单一 exe）。

PyInstaller 打包为 yuxin-worker.exe 后，Electron 主进程通过子命令启动
对应服务，避免为每个 worker 单独打包：

    yuxin-worker.exe os       --port 8765
    yuxin-worker.exe browser  --port 8766
    yuxin-worker.exe computer --port 8767
    yuxin-worker.exe wake

开发模式（无 exe）下等效于 python scripts/<worker>.py。
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from typing import Any

# 开发模式直接 `python scripts/worker_super.py <service>` 运行时，sys.path[0]
# 是 api/scripts 而非 api/；把 api/（包根）补入 sys.path，使 scripts.* 可导入。
# PyInstaller 打包场景由 worker.spec 的 pathex 覆盖，此处为幂等兜底。
_API_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.isdir(os.path.join(_API_ROOT, "scripts")) and _API_ROOT not in sys.path:
    sys.path.insert(0, _API_ROOT)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="yuxin-worker", description="YuxinAI desktop worker")
    parser.add_argument(
        "service",
        choices=("os", "browser", "computer", "wake"),
        help="要启动的 worker 服务",
    )
    parser.add_argument("--host", default="", help="监听地址（默认取各 worker 环境变量/常量）")
    parser.add_argument("--port", type=int, default=0, help="监听端口（默认取各 worker 环境变量/常量）")
    return parser.parse_args(argv)


def _module_and_entry(service: str) -> tuple[str, str]:
    return {
        "os": ("scripts.os_automation_worker", "main"),
        "browser": ("scripts.browser_automation_worker", "main"),
        "computer": ("scripts.computer_control_worker", "main"),
        "wake": ("scripts.wake_word_worker", "main"),
    }[service]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    module_name, entry_name = _module_and_entry(args.service)
    # 各 worker 的 main() 自行 argparse --host/--port（取各自环境变量默认值）。
    # 这里注入 argv，让 worker 的 argparse 只看到自己的参数。
    module = importlib.import_module(module_name)
    entry = getattr(module, entry_name)

    worker_argv = []
    if args.host:
        worker_argv += ["--host", args.host]
    if args.port:
        worker_argv += ["--port", str(args.port)]
    # 替换 sys.argv 后调用 worker main，使 worker 内 argparse 解析到正确参数
    old_argv = sys.argv
    sys.argv = [sys.argv[0], *worker_argv]
    try:
        result = entry()
        return int(result or 0)
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    raise SystemExit(main())
