"""调用 HyperFrames CLI 把 composition 渲染为 MP4。

「渲」层。已实测要点（勿改，改了会静默坏）：

1. 必须注入三个路径环境变量：HYPERFRAMES_BROWSER_PATH / HYPERFRAMES_FFMPEG_PATH
   / HYPERFRAMES_FFPROBE_PATH；缺任一 CLI 会在启动阶段拒绝渲染。
2. 浏览器必须是「能响应 --version」的构建。实测 chrome-headless-shell 正常；
   部分完整版 Chrome 在受限环境下 --version 挂死，CLI 会判定
   "Chrome cannot start" 而拒绝启动。
3. ffprobe 必须是**真 ffprobe**：用 ffmpeg 冒充会因 `-print_format` 不支持而失败。
4. CLI 版本必须钉死（hyperframes@X.Y.Z），否则同一 composition 跨时间渲染结果可能漂移。
5. **退出码为 0 不等于成功、非 0 也不等于产物无用**：实测出现过「300 帧全部捕获
   并编码完成、产物已落盘，但最后一步 ffprobe 时长探测失败 → 非 0 退出」。
   因此本模块的判定是「退出码为 0 **且** 产物存在非空 **且** ffprobe 能读出正时长」，
   三者同时满足才返回成功；任一不满足一律抛错，交给上层重试，
   绝不把半成品当成品入库。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = [
    "RenderEnvironmentError",
    "RenderFailedError",
    "build_render_command",
    "build_render_env",
    "render_composition",
    "verify_artifact",
]

_SUPPORTED_QUALITIES = ("draft", "standard", "high")
_SUPPORTED_FPS = (24, 30, 60)

_REQUIRED_ENV_KEYS = (
    "HYPERFRAMES_BROWSER_PATH",
    "HYPERFRAMES_FFMPEG_PATH",
    "HYPERFRAMES_FFPROBE_PATH",
)


class RenderEnvironmentError(RuntimeError):
    """渲染环境不完整（缺二进制路径等）——属配置问题，重试无用。"""


class RenderFailedError(RuntimeError):
    """渲染失败（CLI 报错 / 产物缺失 / 产物无效）。"""


def build_render_env(settings: Any) -> dict[str, str]:
    """构造渲染子进程环境：继承当前环境 + 注入 HyperFrames 三个路径。

    三个路径缺任一直接报错并指名缺哪个——渲染是分钟级长任务，
    与其跑到一半失败，不如在启动前拦下。
    """
    env = dict(os.environ)
    missing: list[str] = []
    for key in _REQUIRED_ENV_KEYS:
        value = getattr(settings, key, "") or ""
        if not value:
            missing.append(key)
            continue
        env[key] = value
    if missing:
        raise RenderEnvironmentError(
            "渲染环境缺少必需配置：" + "、".join(missing) + "（见 .env.example 的渲染段）"
        )
    return env


def build_render_command(
    settings: Any, *, output_path: Path, quality: str = "standard", fps: int = 30
) -> list[str]:
    """构造渲染命令。CLI 版本钉死，参数白名单校验。"""
    if quality not in _SUPPORTED_QUALITIES:
        raise RenderFailedError(
            f"不支持的渲染质量：{quality}，可选：{list(_SUPPORTED_QUALITIES)}"
        )
    if int(fps) not in _SUPPORTED_FPS:
        raise RenderFailedError(f"不支持的帧率：{fps}，可选：{list(_SUPPORTED_FPS)}")

    version = getattr(settings, "HYPERFRAMES_CLI_VERSION", "") or "0.8.42"
    return [
        "npx",
        "--yes",
        f"hyperframes@{version}",
        "render",
        "--quality",
        quality,
        "--fps",
        str(int(fps)),
        "--output",
        str(output_path),
    ]


def probe_duration_sec(video_path: Path, settings: Any) -> float:
    """用真 ffprobe 读时长（秒）；读不出返回 0.0。

    不额外依赖外部 ffprobe 时也可复用 internal/core/vision/vision_invoke.py
    的探测思路，但那里解析的是 ffmpeg 的 stderr，产出的是「源文件时长」，
    与「渲染产物是否有效」是两件事，故此处独立实现。
    """
    ffprobe = getattr(settings, "HYPERFRAMES_FFPROBE_PATH", "") or "ffprobe"
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        logger.warning("ffprobe 探测失败 path=%s", video_path, exc_info=True)
        return 0.0
    if result.returncode != 0:
        return 0.0
    try:
        payload = json.loads(result.stdout or "{}")
        return float((payload.get("format") or {}).get("duration") or 0.0)
    except (ValueError, TypeError):
        return 0.0


def verify_artifact(
    output_path: Path, *, prober: Callable[[Path], float] | None = None
) -> float:
    """校验渲染产物：文件存在、非空、能读出正时长。返回时长秒数。"""
    probe = prober or (lambda path: 0.0)
    if not output_path.is_file():
        raise RenderFailedError(f"渲染产物不存在：{output_path}")
    if output_path.stat().st_size <= 0:
        raise RenderFailedError(f"渲染产物为空文件：{output_path}")
    duration = probe(output_path)
    if not duration or duration <= 0:
        raise RenderFailedError(f"渲染产物时长无效（{duration}），文件可能损坏：{output_path}")
    return float(duration)


def render_composition(
    *,
    project_dir: Path,
    output_path: Path,
    settings: Any,
    quality: str = "standard",
    fps: int = 30,
    timeout_sec: int | None = None,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    prober: Callable[[Path], float] | None = None,
) -> Path:
    """在 project_dir 内渲染 composition 到 output_path，返回校验通过的产物路径。

    `runner` / `prober` 为测试注入点（默认走真实 subprocess 与 ffprobe）。
    """
    project_dir = Path(project_dir)
    output_path = Path(output_path)
    if not (project_dir / "index.html").is_file():
        raise RenderFailedError(f"工程目录缺少 index.html：{project_dir}")

    env = build_render_env(settings)
    cmd = build_render_command(
        settings, output_path=output_path, quality=quality, fps=fps
    )
    run = runner or (
        lambda command, cwd, env, timeout: subprocess.run(
            command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
        )
    )
    if prober is None:
        prober = lambda path: probe_duration_sec(path, settings)

    timeout = int(timeout_sec or getattr(settings, "RENDER_TIMEOUT_SEC", 1800))
    logger.info("开始渲染 composition dir=%s output=%s", project_dir, output_path)

    try:
        result = run(cmd, str(project_dir), env, timeout)
    except subprocess.TimeoutExpired as exc:
        raise RenderFailedError(f"渲染超时（{timeout}s）：{project_dir}") from exc

    stdout = (getattr(result, "stdout", "") or "").strip()
    stderr = (getattr(result, "stderr", "") or "").strip()
    if result.returncode != 0:
        tail = (stderr or stdout)[-800:]
        raise RenderFailedError(f"渲染失败（exit={result.returncode}）：{tail}")

    duration = verify_artifact(output_path, prober=prober)
    logger.info("渲染完成 output=%s duration=%.2fs", output_path, duration)
    return output_path
