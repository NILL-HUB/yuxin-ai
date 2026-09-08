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
import threading
import time
from typing import Any

# 开发模式直接 `python scripts/worker_super.py <service>` 运行时，sys.path[0]
# 是 api/scripts 而非 api/；把 api/（包根）补入 sys.path，使 scripts.* 可导入。
# PyInstaller 打包场景由 worker.spec 的 pathex 覆盖，此处为幂等兜底。
_API_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.isdir(os.path.join(_API_ROOT, "scripts")) and _API_ROOT not in sys.path:
    sys.path.insert(0, _API_ROOT)


# 接受并透传 --host/--port 的服务（其 worker main 的 argparse 声明了这两个参数）。
# wake_word_worker 的 argparse 只接受 --keyword/--endpoint/--token/--engine/--check，
# 向其注入 --host/--port 会以误导性 usage 崩溃，故不在白名单内。
_SERVICE_SUPPORTS_HOST_PORT = frozenset(("os", "browser", "computer"))

# Electron 主进程启动 worker 时注入自身 PID；worker 周期性检测该宿主是否存活，
# 宿主退出（正常退出/被杀/崩溃）即自杀，避免 worker 进程树散落残留。
HOST_PID_ENV = "YUXIN_HOST_PID"
_WATCHDOG_INTERVAL_SECONDS = 3.0


def _parse_host_pid() -> int | None:
    raw = os.environ.get(HOST_PID_ENV, "").strip()
    if not raw:
        return None
    try:
        pid = int(raw)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _pid_exists(pid: int) -> bool:
    """跨平台判断 PID 对应的进程是否存在。

    Windows 的 os.kill(pid, 0) 语义与 POSIX 不同：它不会"仅探活"，对已结束
    进程也不报错，无法用于存活检测。OpenProcess 对已结束进程仍可返回句柄
    （进程对象尚在），需再以 GetExitCodeProcess 判断：退出码为
    STILL_ACTIVE(259) 才视为存活。
    """
    if os.name == "nt":
        import ctypes

        STILL_ACTIVE = 259
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _host_alive(host_pid: int) -> bool:
    """宿主存活判断：PID 存在即视为存活。"""
    return _pid_exists(host_pid)


def _start_host_watchdog(host_pid: int) -> None:
    def _watch() -> None:
        while True:
            time.sleep(_WATCHDOG_INTERVAL_SECONDS)
            try:
                alive = _host_alive(host_pid)
            except Exception as exc:  # noqa: BLE001 - watchdog 线程异常不能静默死亡
                print(
                    f"yuxin-worker: host watchdog probe error: {exc!r}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            if not alive:
                # 宿主已退出：主动终止当前服务进程。os._exit 跳过清理直接退出，
                # 与 SystemExit/KeyboardInterrupt 不同，可被任意阻塞的 serve_forever 中断。
                print(
                    f"yuxin-worker: host process {host_pid} exited, shutting down",
                    file=sys.stderr,
                    flush=True,
                )
                os._exit(0)

    thread = threading.Thread(target=_watch, name="host-watchdog", daemon=True)
    thread.start()
    print(
        f"yuxin-worker: host watchdog armed for pid {host_pid}",
        file=sys.stderr,
        flush=True,
    )


def _run_with_host_watchdog(host_pid: int, entry: Any, service: str) -> int:
    """以宿主存活看门狗方式运行 worker。

    返回 worker 的退出码（0/非 0）；宿主已死时返回 0（视为宿主主动关闭）。
    """
    _start_host_watchdog(host_pid)
    try:
        result = entry()
        return int(result or 0)
    except SystemExit as exc:
        code = exc.code if exc.code is not None else 0
        if code:
            print(
                f"yuxin-worker {service} 启动失败: {exc}",
                file=sys.stderr,
            )
        raise
    except KeyboardInterrupt:
        return 130


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="yuxin-worker", description="YuxinAI desktop worker")
    parser.add_argument(
        "service",
        choices=("os", "browser", "computer", "wake"),
        help="要启动的 worker 服务",
    )
    # 默认 None（而非 ""/0），仅当调用方显式提供 --host/--port 时才注入到 worker argv，
    # 避免把"未指定"误判为显式值、造成重复/多余参数注入。
    parser.add_argument("--host", default=None, help="监听地址（默认取各 worker 环境变量/常量）")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认取各 worker 环境变量/常量）")
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
    # 这里按服务白名单注入 argv，让 worker 的 argparse 只看到自己支持的参数：
    # 仅显式传入的 --host/--port 会注入，未指定则保持 worker 自身默认值，
    # wake 等不接收 host/port 的服务绝不注入。
    worker_argv: list[str] = []
    if args.service in _SERVICE_SUPPORTS_HOST_PORT:
        if args.host:
            worker_argv += ["--host", args.host]
        if args.port:
            worker_argv += ["--port", str(args.port)]
    # 替换 sys.argv 后调用 worker main，使 worker 内 argparse 解析到正确参数
    module = importlib.import_module(module_name)
    entry = getattr(module, entry_name)
    old_argv = sys.argv
    sys.argv = [sys.argv[0], *worker_argv]
    try:
        host_pid = _parse_host_pid()
        if host_pid is not None:
            return _run_with_host_watchdog(host_pid, entry, args.service)
        # 未注入宿主 PID（独立运行/测试）时保持原行为
        try:
            result = entry()
            return int(result or 0)
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
            if code:
                print(
                    f"yuxin-worker {args.service} 启动失败: {exc}",
                    file=sys.stderr,
                )
            raise
        except KeyboardInterrupt:
            return 130
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    raise SystemExit(main())
