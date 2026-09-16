"""composition 编译器测试（纯函数，无 IO）。

输出必须满足 HyperFrames 已实测契约：
- 画布元素带 data-composition-id / data-start / data-duration / data-width / data-height
- 定时视觉元素带 class="clip" + data-start + data-duration
- 在 window.__timelines 注册该 composition 的 paused 根时间轴
- 文本必须 HTML 转义（防注入，脚本里出现 </script> 会破坏文档结构）
"""
import re

import pytest

from internal.core.video.composition_builder import (
    CompositionSpecError,
    build_composition_html,
)


def _spec(**overrides):
    spec = {
        "composition_id": "main",
        "width": 1920,
        "height": 1080,
        "duration": 10.0,
        "segments": [
            {"start": 0.0, "duration": 5.0, "text": "开场标题", "track_index": 0},
            {"start": 5.0, "duration": 5.0, "text": "第二幕", "track_index": 1},
        ],
    }
    spec.update(overrides)
    return spec


def test_canvas_carries_composition_contract():
    html = build_composition_html(_spec())

    assert 'data-composition-id="main"' in html
    assert 'data-width="1920"' in html
    assert 'data-height="1080"' in html
    assert 'data-duration="10"' in html or 'data-duration="10.0"' in html


def test_every_segment_becomes_a_timed_clip():
    html = build_composition_html(_spec())

    assert html.count('class="clip"') == 2
    assert 'data-start="0"' in html
    assert 'data-start="5"' in html
    assert 'data-duration="5"' in html


def test_root_timeline_is_registered_and_paused():
    html = build_composition_html(_spec())

    assert "window.__timelines" in html
    assert 'window.__timelines["main"]' in html
    assert "paused: true" in html


def test_segment_text_is_html_escaped():
    html = build_composition_html(
        _spec(segments=[{"start": 0.0, "duration": 1.0, "text": "<b>x</b>&y"}]),
    )

    assert "&lt;b&gt;x&lt;/b&gt;&amp;y" in html
    assert "<b>x</b>&y" not in html


def test_script_breakout_is_neutralized():
    """segment 文本含 </script> 不能逃逸出脚本块。"""
    html = build_composition_html(
        _spec(segments=[{"start": 0.0, "duration": 1.0, "text": "</script><script>x"}]),
    )

    # 注入的标签必须整体被转义，不能产生任何额外的脚本块
    assert "&lt;/script&gt;&lt;script&gt;x" in html
    assert "</script><script>" not in html
    # 正文只应有一个脚本块（head 的 gsap 引用是带 src 属性的标签，不匹配 "<script>"）
    assert html.count("<script>") == 1


def test_media_segment_emits_video_with_media_start():
    """带素材的 segment 生成 <video>，并用 data-media-start 裁切源。"""
    html = build_composition_html(
        _spec(
            segments=[
                {
                    "start": 0.0,
                    "duration": 3.0,
                    "media_src": "clip.mp4",
                    "media_start": 2.5,
                    "track_index": 0,
                }
            ]
        ),
    )

    assert "<video" in html
    assert 'data-media-start="2.5"' in html
    assert 'src="clip.mp4"' in html


def test_video_is_muted_per_hyperframes_rule():
    """HyperFrames 规则：视频须 muted，音轨另用 <audio>。"""
    html = build_composition_html(
        _spec(segments=[{"start": 0.0, "duration": 3.0, "media_src": "clip.mp4"}])
    )

    video_tag = re.search(r"<video[^>]*>", html).group(0)
    assert "muted" in video_tag


def test_empty_segments_rejected():
    with pytest.raises(CompositionSpecError):
        build_composition_html(_spec(segments=[]))


def test_negative_start_rejected():
    with pytest.raises(CompositionSpecError):
        build_composition_html(
            _spec(segments=[{"start": -1.0, "duration": 1.0, "text": "x"}])
        )


def test_non_positive_duration_rejected():
    with pytest.raises(CompositionSpecError):
        build_composition_html(
            _spec(segments=[{"start": 0.0, "duration": 0, "text": "x"}])
        )


def test_blank_composition_id_rejected():
    with pytest.raises(CompositionSpecError):
        build_composition_html(_spec(composition_id="  "))


def test_output_has_no_nondeterministic_calls():
    """HyperFrames 要求确定性：不得出现 Date.now / Math.random。"""
    html = build_composition_html(_spec())

    assert "Date.now" not in html
    assert "Math.random" not in html
