"""把结构化视频脚本编译为 HyperFrames composition（HTML）。

「编」层：一个 segment（台词/镜头）= 一个容器，挂载素材/文本。
编译结果是 HyperFrames 可直接 lint/render 的 index.html。

契约（取自 HyperFrames 0.8.42 官方 scaffold，已实测渲染通过）：
- 画布元素：data-composition-id / data-start / data-duration / data-width / data-height
- 定时视觉元素：class="clip" + data-start + data-duration（+ 可选 data-track-index）
- 每个 composition 在 window.__timelines 注册一个 paused 根时间轴
- 确定性：禁 Date.now() / Math.random() / 网络请求

安全：所有用户可控文本一律 HTML 转义；否则文本里的 </script> 会逃逸出脚本块
（实测该场景会破坏文档结构）。
"""
from __future__ import annotations

import html as _html
from typing import Any

__all__ = ["CompositionSpecError", "build_composition_html"]


class CompositionSpecError(ValueError):
    """composition spec 非法（字段缺失/类型不符/数值越界）。"""


def _require_number(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CompositionSpecError(f"{field} 必须是数字，实际为 {type(value).__name__}")
    number = float(value)
    if minimum is not None and number < minimum:
        raise CompositionSpecError(f"{field} 不能小于 {minimum}，实际为 {number}")
    return number


def _format_seconds(value: float) -> str:
    """秒数格式化：整数去掉小数点（10.0 -> "10"），保留小数（2.5 -> "2.5"）。"""
    return str(int(value)) if float(value).is_integer() else str(value)


def _build_segment(segment: dict, index: int) -> str:
    if not isinstance(segment, dict):
        raise CompositionSpecError(f"segments[{index}] 必须是对象")

    start = _require_number(segment.get("start", 0.0), f"segments[{index}].start", minimum=0.0)
    duration = _require_number(segment.get("duration"), f"segments[{index}].duration")
    if duration <= 0:
        raise CompositionSpecError(f"segments[{index}].duration 必须大于 0")

    track_index = segment.get("track_index")
    track_attr = (
        f' data-track-index="{int(track_index)}"' if track_index is not None else ""
    )
    timing = (
        f'class="clip" data-start="{_format_seconds(start)}"'
        f' data-duration="{_format_seconds(duration)}"{track_attr}'
    )

    media_src = segment.get("media_src")
    if media_src:
        # HyperFrames 规则：视频须 muted，音轨另用 <audio> 元素承载
        media_start = segment.get("media_start")
        media_attr = (
            f' data-media-start="{_format_seconds(_require_number(media_start, f"segments[{index}].media_start", minimum=0.0))}"'
            if media_start is not None
            else ""
        )
        return (
            f'    <video id="seg-{index}" {timing}{media_attr}'
            f' src="{_html.escape(str(media_src), quote=True)}" muted playsinline></video>'
        )

    text = _html.escape(str(segment.get("text") or ""), quote=True)
    return f'    <div id="seg-{index}" {timing}>{text}</div>'


def build_composition_html(spec: dict) -> str:
    """把结构化 spec 编译为 HyperFrames composition 的 index.html 内容。

    spec 形状::

        {
          "composition_id": "main",
          "width": 1920, "height": 1080, "duration": 10.0,
          "segments": [
            {"start": 0.0, "duration": 5.0, "text": "开场"},                  # 文本段
            {"start": 5.0, "duration": 5.0, "media_src": "a.mp4",
             "media_start": 2.5, "track_index": 0},                          # 素材段
          ],
        }
    """
    if not isinstance(spec, dict):
        raise CompositionSpecError("spec 必须是对象")

    composition_id = str(spec.get("composition_id") or "").strip()
    if not composition_id:
        raise CompositionSpecError("composition_id 不能为空")

    width = _require_number(spec.get("width", 1920), "width")
    height = _require_number(spec.get("height", 1080), "height")
    duration = _require_number(spec.get("duration"), "duration")
    if duration <= 0:
        raise CompositionSpecError("duration 必须大于 0")

    segments = spec.get("segments")
    if not isinstance(segments, list) or not segments:
        raise CompositionSpecError("segments 必须是非空列表")

    body = "\n".join(
        _build_segment(segment, index) for index, segment in enumerate(segments)
    )
    safe_id = _html.escape(composition_id, quote=True)

    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={_format_seconds(width)}, height={_format_seconds(height)}" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{
        margin: 0;
        width: {_format_seconds(width)}px;
        height: {_format_seconds(height)}px;
        overflow: hidden;
        background: #0a0a0a;
      }}
      #root {{
        position: relative;
        width: 100%;
        height: 100%;
        font-family: Inter, ui-sans-serif, system-ui, sans-serif;
      }}
      .clip {{
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #f4f4f5;
        font-size: 64px;
        font-weight: 600;
      }}
      video.clip {{ object-fit: cover; }}
    </style>
  </head>
  <body>
    <div
      id="root"
      data-composition-id="{safe_id}"
      data-start="0"
      data-duration="{_format_seconds(duration)}"
      data-width="{_format_seconds(width)}"
      data-height="{_format_seconds(height)}"
    >
{body}
    </div>
    <script>
      window.__timelines = window.__timelines || {{}};
      window.__timelines["{composition_id}"] = gsap.timeline({{ paused: true }});
      window.__timelines["{composition_id}"].seek(0);
    </script>
  </body>
</html>
"""
