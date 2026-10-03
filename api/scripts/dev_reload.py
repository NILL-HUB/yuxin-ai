"""开发用热重载包装：监听源码变更并自动重启子进程。

为什么需要它：`uvicorn --reload` 自带热重载，但 **celery / celery-beat 没有**。
二者都跑挂载进来的源码（`../api` → `/app/api`），改任务代码后若只有 uvicorn 能
重载，就会再次出现「磁盘是新代码、跑起来是旧代码」的迷惑故障。故用 watchfiles 的
`run_process` 对任意命令做「变更即重启」，在 entrypoint 的 `DEV_RELOAD` 分支统一收口。

- 仅当 entrypoint 检测到 `DEV_RELOAD=1` 时才会被调用；**生产不启用**。
- `target_type="command"` 要求 target 为**字符串**（watchfiles 内部用 shlex 拆分），
  故用 `shlex.join` 拼接命令，避免分词/注入问题。
- 只监听 `*.py`（`PythonFilter`），并跳过 `DEV_RELOAD_SKIP_DIRS`（冒号分隔的路径前缀，
  默认含测试目录）——避免改测试用例、storage 写入等触发无谓重启。与 entrypoint 给
  uvicorn 的 `--reload-exclude` 保持同一语义。

用法：python scripts/dev_reload.py <命令> [参数...]
"""
from __future__ import annotations

import logging
import os
import shlex
import sys

from watchfiles import PythonFilter, run_process

logger = logging.getLogger("dev_reload")


def _build_watch_filter():
    """仅 `*.py`，且跳过 `DEV_RELOAD_SKIP_DIRS` 下的文件（watchfiles 过滤器签名 (change, path) -> bool）。"""
    python_only = PythonFilter()
    raw = os.environ.get("DEV_RELOAD_SKIP_DIRS", "")
    skip_prefixes = tuple(
        str(item).strip().replace("\\", "/").rstrip("/") + "/"
        for item in raw.split(":")
        if str(item).strip()
    )

    def _watch_filter(change, path: str) -> bool:
        if not python_only(change, path):
            return False
        if not skip_prefixes:
            return True
        normalized = str(path).replace("\\", "/")
        return not any(normalized.startswith(prefix) for prefix in skip_prefixes)

    return _watch_filter


def main(argv: list[str]) -> int:
    if not argv:
        print("用法: python scripts/dev_reload.py <命令> [参数...]", file=sys.stderr)
        return 2

    watch_dir = os.environ.get("DEV_RELOAD_WATCH_DIR", "/app/api")
    logging.basicConfig(level=logging.INFO, format="[dev-reload] %(message)s")
    logger.info(
        "监听 %s 下的 *.py（跳过 %s），变更即重启: %s",
        watch_dir,
        os.environ.get("DEV_RELOAD_SKIP_DIRS", "") or "(无)",
        " ".join(argv),
    )

    # run_process 会阻塞直到目标进程退出；期间每次命中变更都会重启目标进程。
    # target 必须是字符串（command 模式内部 shlex 拆分），shlex.join 保证参数安全还原。
    run_process(
        watch_dir,
        target=shlex.join(argv),
        target_type="command",
        watch_filter=_build_watch_filter(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
