"""视频轻量剪辑服务（trim / concat / subtitle）。

职责边界：
- 本模块负责「下载素材 → 构造命令 → 执行 ffmpeg → 校验产物」；
- 命令构造是纯函数，见 `internal.core.video.ffmpeg_edit`；
- 分钟级/大批量场景由调用方（Celery 任务）承载，本模块自身是同步的。

为什么不做复杂重试/闸门：trim（-c copy）与 concat（-c copy）本质是封装操作（秒级），
subtitle 的重编码也仅对短视频耗时明显；故由 Celery 的 max_retries 兜底即可，
无需复制渲染链路的并发闸门（那是分钟级任务的成本，此处属过度设计）。
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from injector import inject

from internal.core.video.ffmpeg_edit import (
    build_concat_command,
    build_subtitle_command,
    build_trim_command,
    render_srt,
)

logger = logging.getLogger(__name__)

# 单条 ffmpeg 命令超时：剪辑是 IO 密集，但重编码可能较慢，留足余量
_EDIT_TIMEOUT_SEC = 600
# 产物体积下限：小于 1KB 基本可判定为「空壳产物」
_MIN_OUTPUT_BYTES = 1024


class VideoEditError(RuntimeError):
    """视频编辑失败。消息面向用户可直接展示，不进重试。"""


@inject
@dataclass
class VideoEditService:
    """视频剪辑服务。依赖注入保持与既有 service 一致的写型注解。"""

    def _resolve_exe(self) -> str:
        """ffmpeg 可执行文件路径（系统优先，imageio 兜底）。"""
        from internal.core.vision.vision_invoke import _resolve_ffmpeg_exe

        return _resolve_ffmpeg_exe()

    def _probe_duration(self, path: str | Path) -> float:
        """探测时长（秒）；失败返回 0.0（调用方据此跳过边界校验）。"""
        from internal.core.vision.vision_invoke import probe_duration_sec

        return probe_duration_sec(str(path))

    def _run_ffmpeg(self, cmd: list[str], timeout: int = _EDIT_TIMEOUT_SEC) -> None:
        """执行 ffmpeg；失败抛 CalledProcessError（由调用方包装为可读错误）。"""
        subprocess.run(cmd, capture_output=True, timeout=timeout, check=True)

    def _ensure_source(self, path: str | Path) -> Path:
        source = Path(path)
        if not source.is_file():
            raise VideoEditError(f"源视频不存在：{source}")
        return source

    def _ensure_output(self, output: str | Path) -> Path:
        out = Path(output)
        if not out.is_file() or out.stat().st_size < _MIN_OUTPUT_BYTES:
            # ffmpeg 退出码 0 不等于产物有效（既有渲染链路同样教训）
            raise VideoEditError("剪辑未产出有效文件")
        return out

    def _materialize_output(self, output: str | Path) -> Path:
        """产物后处理钩子（默认恒等）。

        单独抽成方法便于测试替换；执行 ffmpeg 的路径本身不在此处，
        故默认实现只回传路径，产物有效性统一由 `_ensure_output` 校验。
        """
        return Path(output)

    def trim(
        self,
        *,
        source_path: str | Path,
        output_path: str | Path,
        start_sec: float,
        end_sec: float | None,
        reencode: bool = False,
    ) -> Path:
        """按时间区间裁剪。默认流拷贝（无损、秒级）。"""
        source = self._ensure_source(source_path)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # 边界校验：仅在能探到时长时启用（探测失败不阻断，交由 ffmpeg 自身报错）
        duration = self._probe_duration(source)
        if duration > 0:
            if float(start_sec) >= duration:
                raise VideoEditError(
                    f"开始时间 {float(start_sec):.2f}s 超出视频时长 {duration:.2f}s"
                )
            if end_sec is not None and float(end_sec) > duration + 0.5:
                raise VideoEditError(
                    f"结束时间 {float(end_sec):.2f}s 超出视频时长 {duration:.2f}s"
                )

        try:
            cmd = build_trim_command(
                self._resolve_exe(),
                source=str(source), output=str(out),
                start_sec=start_sec, end_sec=end_sec, reencode=reencode,
            )
            self._run_ffmpeg(cmd, _EDIT_TIMEOUT_SEC)
        except subprocess.CalledProcessError as exc:
            logger.warning("裁剪失败 source=%s", source, exc_info=True)
            detail = (exc.stderr or b"").decode("utf-8", errors="replace")[:200]
            raise VideoEditError(f"裁剪失败：{detail or exc}") from exc
        except ValueError as exc:
            raise VideoEditError(str(exc)) from exc
        return self._ensure_output(self._materialize_output(out))

    def concat(self, *, source_paths: list[str | Path], output_path: str | Path) -> Path:
        """按传入顺序拼接多段视频（concat demuxer + 流拷贝）。"""
        # 先校验段数（纯参数错误，无需触碰文件系统），再逐个校验素材存在
        if len(list(source_paths or [])) < 2:
            raise VideoEditError("拼接至少需要两段视频")
        paths = [self._ensure_source(p) for p in (source_paths or [])]

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="video-concat-") as work:
            list_file = Path(work) / "list.txt"
            # concat demuxer 清单：绝对路径 + 单引号（-safe 0 允许绝对路径）
            list_file.write_text(
                "".join(f"file '{p.resolve().as_posix()}'\n" for p in paths),
                encoding="utf-8",
            )
            try:
                cmd = build_concat_command(
                    self._resolve_exe(), list_file=str(list_file), output=str(out)
                )
                self._run_ffmpeg(cmd, _EDIT_TIMEOUT_SEC)
            except subprocess.CalledProcessError as exc:
                logger.warning("拼接失败 sources=%s", paths, exc_info=True)
                detail = (exc.stderr or b"").decode("utf-8", errors="replace")[:200]
                raise VideoEditError(f"拼接失败：{detail or exc}") from exc
        return self._ensure_output(out)

    def burn_subtitles(
        self,
        *,
        source_path: str | Path,
        output_path: str | Path,
        cues: list[dict[str, Any]],
    ) -> Path:
        """把字幕烧录进画面（subtitles 滤镜，需重编码）。"""
        source = self._ensure_source(source_path)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        try:
            srt_text = render_srt(cues)
        except ValueError as exc:
            # 统一成 VideoEditError，工具层只需处理一种异常
            raise VideoEditError(str(exc)) from exc

        with tempfile.TemporaryDirectory(prefix="video-subtitle-") as work:
            srt_path = Path(work) / "subtitle.srt"
            # 必须 UTF-8 无 BOM：带 BOM 时 libass 会把首行时间码读坏
            srt_path.write_text(srt_text, encoding="utf-8")
            try:
                cmd = build_subtitle_command(
                    self._resolve_exe(),
                    source=str(source), output=str(out), srt_path=str(srt_path),
                )
                self._run_ffmpeg(cmd, _EDIT_TIMEOUT_SEC)
            except subprocess.CalledProcessError as exc:
                logger.warning("字幕烧录失败 source=%s", source, exc_info=True)
                detail = (exc.stderr or b"").decode("utf-8", errors="replace")[:200]
                raise VideoEditError(f"字幕烧录失败：{detail or exc}") from exc
        return self._ensure_output(out)
