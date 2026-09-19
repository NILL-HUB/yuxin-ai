"""视频轻量剪辑的 ffmpeg 命令构造（纯函数）。

只做「构造命令 / 生成文本」，不碰 subprocess、不碰文件系统——
执行与 IO 在 `internal.service.video_edit_service`，便于本模块被充分单测。

实测约束（api 容器）：
- 无系统 ffmpeg，仅有 imageio_ffmpeg 静态兜底（v7.0.2）；
- 该构建具备 libx264 编码器、subtitles/ass 滤镜（依赖 libass）、concat demuxer，
  但**没有 drawtext 滤镜**——故字幕走 `subtitles` 烧录而非 drawtext。
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "build_concat_command",
    "build_subtitle_command",
    "build_trim_command",
    "format_srt_timestamp",
    "render_srt",
]

# 重编码时的编码参数：与既有渲染链路口径一致（H.264 + AAC，广泛兼容）
_VIDEO_ENCODER = "libx264"
_AUDIO_ENCODER = "aac"
_ENCODE_PRESET = "veryfast"
_ENCODE_CRF = "23"


def format_srt_timestamp(seconds: Any) -> str:
    """秒 → SRT 时间戳 `HH:MM:SS,mmm`。

    注意用**逗号**分隔毫秒（SRT 规范），不是点号；负数按 0 处理。
    """
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        value = 0.0
    if value < 0:
        value = 0.0
    total_ms = int(round(value * 1000))
    hours, remainder = divmod(total_ms, 3600 * 1000)
    minutes, remainder = divmod(remainder, 60 * 1000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def render_srt(cues: list[dict[str, Any]]) -> str:
    """把 `[{start, end, text}]` 渲染为 SRT 文本。

    规则：丢弃空文本块后**重新连续编号**（不能留 1,3 这类断号，部分播放器会错位）；
    结束时间必须晚于开始时间；全部为空则报错（避免烧出一张空白字幕）。
    """
    blocks: list[str] = []
    index = 0
    for cue in cues or []:
        text = str((cue or {}).get("text") or "").strip()
        if not text:
            continue
        try:
            start = float((cue or {}).get("start") or 0.0)
            end = float((cue or {}).get("end") or 0.0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"字幕时间非法：{cue}") from exc
        if end <= start:
            raise ValueError(f"字幕结束时间必须晚于开始时间：start={start} end={end}")
        index += 1
        blocks.append(
            f"{index}\n{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}\n{text}\n"
        )
    if index == 0:
        raise ValueError("字幕内容为空：至少需要一条非空文本")
    # 每块以空行分隔，末尾保留一个空行
    return "\n".join(blocks) + "\n"


def build_trim_command(
    ffmpeg_exe: str,
    *,
    source: str,
    output: str,
    start_sec: float,
    end_sec: float | None,
    reencode: bool = False,
) -> list[str]:
    """构造裁剪命令。

    默认 `-c copy`（无损且秒级，纯封装操作）；`reencode=True` 时才重编码
    （帧对齐更精确，但慢得多）。`-ss` 必须放在 `-i` 之前走快速定位。
    """
    start = float(start_sec or 0.0)
    if start < 0:
        raise ValueError("开始时间不能为负")
    args = [ffmpeg_exe, "-y", "-ss", f"{start:.3f}", "-i", str(source)]
    if end_sec is not None:
        end = float(end_sec)
        if end <= start:
            raise ValueError(f"结束时间必须晚于开始时间：start={start} end={end}")
        args += ["-t", f"{end - start:.3f}"]
    if reencode:
        args += [
            "-c:v", _VIDEO_ENCODER, "-preset", _ENCODE_PRESET, "-crf", _ENCODE_CRF,
            "-c:a", _AUDIO_ENCODER,
        ]
    else:
        args += ["-c", "copy"]
    args.append(str(output))
    return args


def build_concat_command(ffmpeg_exe: str, *, list_file: str, output: str) -> list[str]:
    """构造拼接命令（concat demuxer + `-c copy`）。

    `list_file` 是 concat 清单文件（每行 `file '<abs path>'`），
    由 service 层按素材实际路径生成。
    """
    return [
        ffmpeg_exe, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(output),
    ]


def _escape_subtitle_path(path: str) -> str:
    """转义 subtitles 滤镜里的路径。

    ffmpeg 滤镜参数用 `:` 分隔选项，绝对路径中的 `:`（Windows 盘符）必须转义为 `\\:`；
    反斜杠同样要转义，否则被当作转义符吃掉。
    """
    return str(path).replace("\\", "\\\\").replace(":", "\\:")


def build_subtitle_command(
    ffmpeg_exe: str, *, source: str, output: str, srt_path: str
) -> list[str]:
    """构造字幕烧录命令（`subtitles` 滤镜 + libass + 重编码）。

    字幕必须重编码才能烧进画面（无法 copy），故固定用 libx264/AAC。
    """
    vf = f"subtitles='{_escape_subtitle_path(srt_path)}'"
    return [
        ffmpeg_exe, "-y",
        "-i", str(source),
        "-vf", vf,
        "-c:v", _VIDEO_ENCODER, "-preset", _ENCODE_PRESET, "-crf", _ENCODE_CRF,
        "-c:a", _AUDIO_ENCODER,
        str(output),
    ]
