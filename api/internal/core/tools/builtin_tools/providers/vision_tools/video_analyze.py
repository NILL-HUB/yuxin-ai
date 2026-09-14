"""视频分析工具（对齐 Hermes `vision_tools.py::video_analyze_tool`）。

Hermes 把整个视频 base64 打包为 ``video_url`` 直传多模态模型；本平台多数视觉
模型只支持图片输入，因此采用“抽帧 + 逐帧视觉分析 + 汇总”的降级路径：

- 下载视频（SSRF 防护 + 大小上限）；
- 抽取 3 个代表帧（首/中/尾），优先用 ffmpeg CLI，其次 imageio_ffmpeg；
- 每个关键帧调用平台视觉模型，最后汇总分析结果。

无抽帧后端可用时返回明确错误提示，避免静默失败。
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import tempfile
import urllib.request
from typing import Any
from urllib.parse import urlparse

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from internal.core.vision.vision_invoke import extract_video_frames, invoke_vision_model

logger = logging.getLogger(__name__)

_MAX_VIDEO_BYTES = 50 * 1024 * 1024


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
            frames = extract_video_frames(video_path)
            analysis: list[str] = []
            for index, frame in enumerate(frames, 1):
                try:
                    text = invoke_vision_model(frame, normalized_prompt)
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
