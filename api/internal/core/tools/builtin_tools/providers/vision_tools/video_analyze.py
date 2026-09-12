"""视频分析工具（对齐 Hermes `vision_tools.py::video_analyze_tool`）。

Hermes 把整个视频 base64 打包为 ``video_url`` 直传多模态模型；本平台多数视觉
模型只支持图片输入，因此采用“抽帧 + 逐帧视觉分析 + 汇总”的降级路径：

- 下载视频（SSRF 防护 + 大小上限）；
- 抽取 3 个代表帧（首/中/尾），优先用 ffmpeg CLI，其次 imageio_ffmpeg；
- 每个关键帧调用平台视觉模型，最后汇总分析结果。

无抽帧后端可用时返回明确错误提示，避免静默失败。
"""

from __future__ import annotations

import base64
import ipaddress
import json
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import urllib.request
from typing import Any
from urllib.parse import urlparse

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_MAX_VIDEO_BYTES = 50 * 1024 * 1024
_FRAME_COUNT = 3
_FRAME_TIMEOUT = 60


def _is_safe_video_url(url: str) -> tuple[bool, str]:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "URL 无法解析"
    if parsed.scheme not in {"http", "https"}:
        return False, "仅支持 http/https"
    host = (parsed.hostname or "").lower()
    if not host or host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".local"):
        return False, "禁止访问本地地址"
    try:
        ips = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except OSError:
        return False, "域名无法解析"
    for ip in ips:
        try:
            if ipaddress.ip_address(ip).is_private or ipaddress.ip_address(ip).is_loopback:
                return False, "禁止访问内网地址"
        except ValueError:
            continue
    return True, ""


def _download_video(url: str, destination: str) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
            "Accept": "video/*,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as resp:
        raw = resp.read(_MAX_VIDEO_BYTES + 1)
    if len(raw) > _MAX_VIDEO_BYTES:
        raise ValueError("视频超过大小限制（50MB）")
    with open(destination, "wb") as fh:
        fh.write(raw)


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _extract_frames(video_path: str) -> list[str]:
    """抽取视频关键帧，返回 data URI 列表；无可用后端时抛错。"""
    if _ffmpeg_available():
        return _extract_frames_ffmpeg(video_path)
    try:
        import imageio_ffmpeg  # type: ignore

        return _extract_frames_imageio(video_path)
    except ImportError:
        raise RuntimeError(
            "视频抽帧不可用：容器未安装 ffmpeg，也未安装 imageio-ffmpeg。"
            "请安装 imageio-ffmpeg（pip install imageio-ffmpeg）后重试。"
        )


def _extract_frames_ffmpeg(video_path: str) -> list[str]:
    """用 ffmpeg select 均匀采样 _FRAME_COUNT 帧。"""
    from PIL import Image

    out_dir = tempfile.mkdtemp(prefix="video_frames_")
    try:
        pattern = os.path.join(out_dir, "frame_%03d.jpg")
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"select='not(mod(n\\,100))'",  # 兜底抽样
            "-frames:v", str(_FRAME_COUNT),
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
                    step = max(1, int(total_ms / _FRAME_COUNT / 40))  # 每步约 1/FRAME 时长（40ms 采样粒度）
                    cmd = [
                        "ffmpeg", "-y", "-i", video_path,
                        "-vf", f"select='not(mod(n\\,{step}))'",
                        "-frames:v", str(_FRAME_COUNT),
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
        return [_image_to_data_uri(path) for path in frames[: _FRAME_COUNT]]
    except subprocess.CalledProcessError as exc:
        logger.warning("ffmpeg 抽帧失败: %s", getattr(exc, "stderr", b"")[:200])
        return _last_resort_first_frame(video_path)
    finally:
        try:
            shutil.rmtree(out_dir, ignore_errors=True)
        except Exception:
            pass


def _duration_to_ms(duration: str) -> int:
    parts = str(duration).split(":")
    try:
        if len(parts) == 3:
            h, m, s = (float(p) for p in parts)
            return int((h * 3600 + m * 60 + s) * 1000)
    except ValueError:
        return 0
    return 0


def _last_resort_first_frame(video_path: str) -> list[str]:
    """ffmpeg 抽帧失败时尝试取首帧，再失败则抛错。"""
    try:
        out = tempfile.mktemp(suffix=".jpg")
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-frames:v", "1", "-q:v", "4", out],
            capture_output=True, timeout=_FRAME_TIMEOUT,
            check=True,
        )
        from PIL import Image

        Image.open(out).load()
        return [_image_to_data_uri(out)]
    except Exception as exc:
        raise RuntimeError(f"视频帧提取失败: {exc}")


def _extract_frames_imageio(video_path: str) -> list[str]:
    """用 imageio_ffmpeg 的 ffmpeg 二进制抽帧。"""
    import imageio_ffmpeg  # type: ignore

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    out_dir = tempfile.mkdtemp(prefix="video_frames_")
    try:
        pattern = os.path.join(out_dir, "frame_%03d.jpg")
        cmd = [exe, "-y", "-i", video_path, "-frames:v", str(_FRAME_COUNT), "-q:v", "4", pattern]
        subprocess.run(cmd, capture_output=True, timeout=_FRAME_TIMEOUT * 3, check=True)
        frames = sorted(
            os.path.join(out_dir, name)
            for name in os.listdir(out_dir)
            if name.startswith("frame_")
        )
        if not frames:
            raise RuntimeError("imageio_ffmpeg 未产出帧")
        return [_image_to_data_uri(path) for path in frames[: _FRAME_COUNT]]
    finally:
        try:
            shutil.rmtree(out_dir, ignore_errors=True)
        except Exception:
            pass


def _image_to_data_uri(path: str) -> str:
    mime = "image/jpeg"
    with open(path, "rb") as fh:
        raw = fh.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("抽帧图片超过大小限制")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _invoke_vision_model(data_uri: str, prompt: str) -> str:
    from internal.service.language_model_service import LanguageModelService

    llm = LanguageModelService.get_feature_model("vision_analyze")
    if llm is None:
        raise RuntimeError("未配置视觉分析模型")
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_uri}},
    ]
    from langchain_core.messages import HumanMessage

    response = llm.invoke([HumanMessage(content=content)])
    text = getattr(response, "content", "")
    if isinstance(text, list):
        text = "\n".join(
            str(item.get("text", ""))
            for item in text
            if isinstance(item, dict) and item.get("text")
        )
    return str(text or "").strip()


class VideoAnalyzeInput(BaseModel):
    video_url: str = Field(..., description="视频的 http(s) URL")
    prompt: str = Field(
        default="请分析这段视频的内容：描述画面主体、场景变化、字幕文字与关键动作。",
        description="分析要求",
    )


class VideoAnalyzeTool(BaseTool):
    name: str = "video_analyze"
    description: str = (
        "分析视频：下载视频并抽取 3 个关键帧，用视觉模型逐帧分析后汇总。"
        "用于审阅视频内容、提取字幕、检查画面等场景。需要容器具备 ffmpeg 或 imageio-ffmpeg。"
    )
    args_schema: type[BaseModel] = VideoAnalyzeInput

    def _run(self, video_url: str, prompt: str = "", **kwargs: Any) -> str:
        normalized_url = str(video_url or "").strip()
        if not normalized_url:
            return json.dumps({"ok": False, "error": "视频 URL 不能为空"}, ensure_ascii=False)
        safe, reason = _is_safe_video_url(normalized_url)
        if not safe:
            return json.dumps({"ok": False, "error": reason}, ensure_ascii=False)
        normalized_prompt = str(prompt or "").strip() or "请分析这段视频的内容：描述画面主体、场景变化、字幕文字与关键动作。"

        video_path = tempfile.mktemp(suffix=os.path.splitext(urlparse(normalized_url).path)[1] or ".mp4")
        try:
            _download_video(normalized_url, video_path)
            frames = _extract_frames(video_path)
            analysis: list[str] = []
            for index, frame in enumerate(frames, 1):
                try:
                    text = _invoke_vision_model(frame, normalized_prompt)
                    analysis.append(f"帧 {index}\n{text}")
                except Exception as exc:  # noqa: BLE001
                    analysis.append(f"帧 {index}: 分析失败（{exc}）")
            combined = "\n\n".join(analysis)
            return json.dumps(
                {
                    "ok": True,
                    "frame_count": len(frames),
                    "analysis": combined,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            logger.warning("视频分析失败", exc_info=True)
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        finally:
            try:
                os.remove(video_path)
            except OSError:
                pass

    async def _arun(self, video_url: str, prompt: str = "", **kwargs: Any) -> str:
        return self._run(video_url=video_url, prompt=prompt, **kwargs)


def video_analyze(**kwargs: Any) -> BaseTool:
    return VideoAnalyzeTool()