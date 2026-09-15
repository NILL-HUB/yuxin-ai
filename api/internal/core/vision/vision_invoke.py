"""共享视觉能力：图片/视频帧的视觉模型调用与视频抽帧。

从 vision_tools 内置工具中抽取，供「内置工具」与「知识库多模态解析」复用，
避免两处重复维护模型调用与帧抽取逻辑。
"""
from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from internal.core.vision.frame_sampling import (
    plan_frame_offsets,
    resolve_l1_frame_count,
)

logger = logging.getLogger(__name__)

# 单张图片编码上限（base64 前）
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
# 默认抽帧数量
_DEFAULT_FRAME_COUNT = 3
# ffmpeg 单次命令超时（秒）
_FRAME_TIMEOUT = 60


_EXTENSION_MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def path_to_data_uri(path: str) -> str:
    """把本地图片文件转为 data URI（按扩展名推断 MIME，带大小上限）。"""
    if not os.path.isfile(path):
        raise ValueError(f"图片文件不存在：{path}")
    with open(path, "rb") as fh:
        raw = fh.read(_MAX_IMAGE_BYTES + 1)
    if len(raw) > _MAX_IMAGE_BYTES:
        raise ValueError(f"图片超过大小限制：{path}")
    extension = os.path.splitext(path)[1].lower()
    mime = _EXTENSION_MIME_MAP.get(extension, "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def invoke_vision_model(data_uri: str, prompt: str) -> str:
    """调用平台视觉模型分析单张图片（入参为 data URI）。"""
    from langchain_core.messages import HumanMessage

    from internal.service.language_model_service import LanguageModelService

    llm = LanguageModelService.get_feature_model("vision_analyze")
    if llm is None:
        raise RuntimeError("未配置视觉分析模型")
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_uri}},
    ]
    response = llm.invoke([HumanMessage(content=content)])
    text = getattr(response, "content", "")
    if isinstance(text, list):
        text = "\n".join(
            str(item.get("text", ""))
            for item in text
            if isinstance(item, dict) and item.get("text")
        )
    return str(text or "").strip()


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _resolve_ffmpeg_exe() -> str:
    """返回可用的 ffmpeg 可执行文件路径；两者皆无时抛错。

    优先系统 ffmpeg，其次 imageio-ffmpeg 自带的静态二进制（容器内常见兜底）。
    """
    if _ffmpeg_available():
        return "ffmpeg"
    try:
        import imageio_ffmpeg  # type: ignore
    except ImportError:
        raise RuntimeError(
            "ffmpeg 不可用：容器未安装 ffmpeg，也未安装 imageio-ffmpeg。"
            "请安装 imageio-ffmpeg（pip install imageio-ffmpeg）后重试。"
        )
    return imageio_ffmpeg.get_ffmpeg_exe()


def _duration_to_ms(duration: str) -> int:
    parts = str(duration).split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = (float(part) for part in parts)
            return int((hours * 3600 + minutes * 60 + seconds) * 1000)
    except ValueError:
        return 0
    return 0


def _run_ffmpeg_probe(exe: str, video_path: str):
    """执行 ffmpeg 探测（独立方法便于测试替换，避免单测依赖真实 ffmpeg）。"""
    return subprocess.run(
        [exe, "-i", video_path], capture_output=True, timeout=_FRAME_TIMEOUT
    )


def probe_duration_sec(video_path: str) -> float:
    """探测视频时长（秒）；无法探测时返回 0.0（由调用方退回默认帧数）。

    ffmpeg 无 ffprobe 依赖也能给出 Duration 行，故复用同一可执行文件，
    不额外要求 ffprobe 存在。
    """
    try:
        exe = _resolve_ffmpeg_exe()
        result = _run_ffmpeg_probe(exe, video_path)
        stderr = (result.stderr or b"").decode("utf-8", errors="replace")
    except Exception:
        logger.warning("视频时长探测失败 path=%s", video_path, exc_info=True)
        return 0.0
    for line in stderr.splitlines():
        if "Duration:" in line:
            raw = line.split("Duration:")[1].split(",")[0].strip()
            return _duration_to_ms(raw) / 1000.0
    return 0.0


def extract_video_frames(video_path: str, frame_count: int = _DEFAULT_FRAME_COUNT) -> list[str]:
    """抽取视频关键帧，返回 data URI 列表；无可用后端时抛错。"""
    requested = _DEFAULT_FRAME_COUNT if frame_count is None else int(frame_count)
    normalized_count = max(1, requested)
    if _ffmpeg_available():
        return _extract_frames_ffmpeg(video_path, normalized_count)
    try:
        import imageio_ffmpeg  # type: ignore
    except ImportError:
        raise RuntimeError(
            "视频抽帧不可用：容器未安装 ffmpeg，也未安装 imageio-ffmpeg。"
            "请安装 imageio-ffmpeg（pip install imageio-ffmpeg）后重试。"
        )
    return _extract_frames_imageio(video_path, normalized_count)


def extract_video_audio(video_path: str, target_path: str) -> str:
    """抽取视频音轨为单声道 16k WAV（ASR 友好输入），返回 target_path。

    视频无音轨 / 无可用 ffmpeg / 未产出文件时统一抛 RuntimeError，
    由调用方决定是否降级（视频解析中音轨属增强能力，缺失不应中断解析）。
    """
    exe = _resolve_ffmpeg_exe()
    cmd = [
        exe, "-y", "-i", video_path,
        "-vn",           # 丢弃视频流，只要音频
        "-ac", "1",      # 单声道（ASR 模型的标准输入）
        "-ar", "16000",  # 16k 采样率（ASR 模型的标准输入）
        "-f", "wav",
        target_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=_FRAME_TIMEOUT * 3, check=True)
    except subprocess.CalledProcessError as exc:
        logger.warning("ffmpeg 抽音轨失败: %s", getattr(exc, "stderr", b"")[:200])
        raise RuntimeError("视频音轨抽取失败") from exc
    if not os.path.isfile(target_path):
        raise RuntimeError("视频音轨抽取未产出文件")
    return target_path


def extract_video_frames_to_dir(
    video_path: str,
    out_dir: str,
    frame_count: int = _DEFAULT_FRAME_COUNT,
) -> list[str]:
    """抽取视频关键帧到指定目录，返回帧文件路径列表。

    与 extract_video_frames 的区别：不删除目录、不转 data URI，
    产物生命周期由调用方负责（帧留存 / 视觉向量都要求文件可复用）。
    """
    requested = _DEFAULT_FRAME_COUNT if frame_count is None else max(1, int(frame_count))
    os.makedirs(out_dir, exist_ok=True)
    if _ffmpeg_available():
        return _extract_frames_to_dir_ffmpeg(video_path, requested, out_dir)
    exe = _resolve_ffmpeg_exe()
    return _extract_frames_to_dir_imageio(video_path, requested, out_dir, exe)


@dataclass
class ExtractedFrame:
    """抽出的帧文件及其在视频中的时间偏移（秒）。"""

    path: str
    time_offset: float


def _extract_frames_by_interval(
    exe: str, video_path: str, out_dir: str, interval_sec: float, max_frames: int
) -> None:
    """按固定时间间隔抽帧。

    用 `fps=1/interval` 而非帧号取模：后者依赖源帧率，同一策略在不同帧率
    视频上会得到不同的采样密度；按时间间隔才与「时长」这一产品维度一致。
    """
    pattern = os.path.join(out_dir, "frame_%03d.jpg")
    fps = 1.0 / max(interval_sec, 0.001)
    cmd = [
        exe, "-y", "-i", video_path,
        "-vf", f"fps={fps:.6f}",
        "-frames:v", str(max_frames),
        "-q:v", "4", pattern,
    ]
    subprocess.run(cmd, capture_output=True, timeout=_FRAME_TIMEOUT * 6, check=True)


def extract_video_frames_with_offsets(
    video_path: str,
    out_dir: str,
    frame_count: int | None = None,
) -> list[ExtractedFrame]:
    """按视频时长均匀抽帧，返回帧文件与各自的时间偏移。

    与 `extract_video_frames_to_dir` 的区别：后者只给路径、无时间信息，
    且上层若传固定帧数会退化成「只取开头」。本函数按 `frame_sampling`
    的策略全片均匀取帧——这是「改细节」能定位到片段的前提。

    frame_count 显式传入时按传入值抽（供 L2 区间密抽复用）。
    """
    duration = probe_duration_sec(video_path)
    if frame_count is not None:
        count = max(1, int(frame_count))
        offsets = (
            [round(duration / count * (i + 0.5), 3) for i in range(count)]
            if duration > 0
            else [0.0] * count
        )
    else:
        count = resolve_l1_frame_count(duration)
        offsets = plan_frame_offsets(duration)
        if not offsets:
            # 时长不可得：退回下限帧数，偏移未知记 0
            count = resolve_l1_frame_count(0)
            offsets = [0.0] * count

    os.makedirs(out_dir, exist_ok=True)
    if duration > 0:
        _extract_frames_by_interval(
            _resolve_ffmpeg_exe(), video_path, out_dir, duration / count, count
        )

    paths = _list_frame_files(out_dir)
    if not paths:
        # 时长不可得（或按间隔抽帧未产出）：退回「抽首帧」保证仍有产物。
        # 注意顺序——必须先尝试兜底再判定失败，否则兜底分支不可达。
        first = os.path.join(out_dir, "frame_001.jpg")
        _dump_first_frame(video_path, first, _resolve_ffmpeg_exe())
        paths = _list_frame_files(out_dir)

    if not paths:
        raise RuntimeError("视频抽帧未产出任何文件")

    # 偏移按下标与帧文件一一对应，不因实际产出帧数少而重排。
    # `fps=1/interval` 采样自片头起算，实际产出必然是同一条时间线上的**前 k 帧**，
    # 故其真实位置就是计划偏移的前 k 项；若按「实际帧数」把全片重新摊开，
    # 会给位于片头 20s 的帧标上 50s 一类偏移，等于伪造元数据——L2 依赖
    # time_offset 定位区间，错标会静默抽错片段。宁可保留真实偏移、少抽几帧。
    return [
        ExtractedFrame(
            path=path,
            time_offset=float(offsets[index]) if index < len(offsets) else 0.0,
        )
        for index, path in enumerate(paths)
    ]


def _extract_frames_to_dir_ffmpeg(video_path: str, frame_count: int, out_dir: str) -> list[str]:
    """用系统 ffmpeg 抽帧到 out_dir；失败时回落到首帧（仍写文件）。"""
    pattern = os.path.join(out_dir, "frame_%03d.jpg")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", "select='not(mod(n\\,100))'",
        "-frames:v", str(frame_count),
        "-q:v", "4", pattern,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=_FRAME_TIMEOUT * 3, check=True)
    except subprocess.CalledProcessError as exc:
        logger.warning("ffmpeg 抽帧失败: %s", getattr(exc, "stderr", b"")[:200])
    frames = _list_frame_files(out_dir)
    if not frames:
        first_frame = os.path.join(out_dir, "frame_001.jpg")
        _dump_first_frame(video_path, first_frame, "ffmpeg")
        frames = _list_frame_files(out_dir)
    return frames[:frame_count]


def _extract_frames_to_dir_imageio(
    video_path: str,
    frame_count: int,
    out_dir: str,
    exe: str,
) -> list[str]:
    """imageio-ffmpeg 兜底抽帧到 out_dir。"""
    pattern = os.path.join(out_dir, "frame_%03d.jpg")
    cmd = [exe, "-y", "-i", video_path, "-frames:v", str(frame_count), "-q:v", "4", pattern]
    try:
        subprocess.run(cmd, capture_output=True, timeout=_FRAME_TIMEOUT * 3, check=True)
    except subprocess.CalledProcessError as exc:
        logger.warning("imageio_ffmpeg 抽帧失败: %s", getattr(exc, "stderr", b"")[:200])
    frames = _list_frame_files(out_dir)
    if not frames:
        first_frame = os.path.join(out_dir, "frame_001.jpg")
        _dump_first_frame(video_path, first_frame, exe)
        frames = _list_frame_files(out_dir)
    return frames[:frame_count]


def _list_frame_files(out_dir: str) -> list[str]:
    """列出目录内已产出的帧文件（按文件名排序）。"""
    return sorted(
        os.path.join(out_dir, name)
        for name in os.listdir(out_dir)
        if name.startswith("frame_") and name.endswith(".jpg")
    )


def _dump_first_frame(video_path: str, target_path: str, exe: str) -> str:
    """抽首帧写到 target_path，并校验可解码，失败则抛错。

    损坏/空帧必须抛出而不是当作成功，否则下游视觉模型会收到空图静默失败。
    """
    try:
        subprocess.run(
            [exe, "-y", "-i", video_path, "-frames:v", "1", "-q:v", "4", target_path],
            capture_output=True, timeout=_FRAME_TIMEOUT, check=True,
        )
        from PIL import Image

        Image.open(target_path).load()
    except Exception as exc:
        raise RuntimeError(f"视频帧提取失败: {exc}") from exc
    return target_path


def _extract_frames_ffmpeg(video_path: str, frame_count: int) -> list[str]:
    out_dir = tempfile.mkdtemp(prefix="video_frames_")
    try:
        pattern = os.path.join(out_dir, "frame_%03d.jpg")
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", "select='not(mod(n\\,100))'",
            "-frames:v", str(frame_count),
            "-q:v", "4", pattern,
        ]
        try:
            probe = subprocess.run(
                ["ffmpeg", "-i", video_path],
                capture_output=True, timeout=_FRAME_TIMEOUT,
            )
            stderr = probe.stderr.decode("utf-8", errors="replace")
            duration = None
            for line in stderr.splitlines():
                if "Duration:" in line:
                    duration = line.split("Duration:")[1].split(",")[0].strip()
                    break
            if duration:
                total_ms = _duration_to_ms(duration)
                if total_ms > 0:
                    step = max(1, int(total_ms / frame_count / 40))
                    cmd = [
                        "ffmpeg", "-y", "-i", video_path,
                        "-vf", f"select='not(mod(n\\,{step}))'",
                        "-frames:v", str(frame_count),
                        "-q:v", "4", pattern,
                    ]
        except Exception:
            pass

        subprocess.run(cmd, capture_output=True, timeout=_FRAME_TIMEOUT * 3, check=True)
        frames = sorted(
            os.path.join(out_dir, name)
            for name in os.listdir(out_dir)
            if name.startswith("frame_")
        )
        if not frames:
            return _last_resort_first_frame(video_path)
        return [path_to_data_uri(path) for path in frames[:frame_count]]
    except subprocess.CalledProcessError as exc:
        logger.warning("ffmpeg 抽帧失败: %s", getattr(exc, "stderr", b"")[:200])
        return _last_resort_first_frame(video_path)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def _last_resort_first_frame(video_path: str) -> list[str]:
    """抽帧失败时尝试取首帧，再失败则抛错。

    必须校验产出的首帧可被解码，否则损坏/空帧会被当作成功，
    让下游视觉模型收到空图并静默失败。
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
            out = handle.name
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", video_path, "-frames:v", "1", "-q:v", "4", out],
                capture_output=True, timeout=_FRAME_TIMEOUT, check=True,
            )
            from PIL import Image

            Image.open(out).load()
            return [path_to_data_uri(out)]
        finally:
            try:
                os.remove(out)
            except OSError:
                pass
    except Exception as exc:
        raise RuntimeError(f"视频帧提取失败: {exc}")


def _extract_frames_imageio(video_path: str, frame_count: int) -> list[str]:
    import imageio_ffmpeg  # type: ignore

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    out_dir = tempfile.mkdtemp(prefix="video_frames_")
    try:
        pattern = os.path.join(out_dir, "frame_%03d.jpg")
        cmd = [exe, "-y", "-i", video_path, "-frames:v", str(frame_count), "-q:v", "4", pattern]
        subprocess.run(cmd, capture_output=True, timeout=_FRAME_TIMEOUT * 3, check=True)
        frames = sorted(
            os.path.join(out_dir, name)
            for name in os.listdir(out_dir)
            if name.startswith("frame_")
        )
        if not frames:
            raise RuntimeError("imageio_ffmpeg 未产出帧")
        return [path_to_data_uri(path) for path in frames[:frame_count]]
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
