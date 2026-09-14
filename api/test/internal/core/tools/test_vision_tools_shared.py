"""确认内置视觉工具已复用共享模块（无本地重复实现）。"""
import importlib

vision_tool_module = importlib.import_module(
    "internal.core.tools.builtin_tools.providers.vision_tools.vision_analyze"
)
video_tool_module = importlib.import_module(
    "internal.core.tools.builtin_tools.providers.vision_tools.video_analyze"
)


def test_vision_analyze_reuses_shared_invoker():
    """视觉分析工具不应再定义本地 _invoke_vision_model。"""
    assert not hasattr(vision_tool_module, "_invoke_vision_model")


def test_video_analyze_reuses_shared_frame_extractor():
    """视频工具不应再定义本地抽帧实现。"""
    assert not hasattr(video_tool_module, "_extract_frames_ffmpeg")
    assert not hasattr(video_tool_module, "_extract_frames_imageio")
    assert not hasattr(video_tool_module, "_image_to_data_uri")
    assert not hasattr(video_tool_module, "_invoke_vision_model")


def test_video_analyze_keeps_ssrf_guard_and_download():
    """工具特有的 SSRF 防护与下载逻辑必须保留。"""
    assert hasattr(video_tool_module, "_is_safe_video_url")
    assert hasattr(video_tool_module, "_download_video")


def test_vision_analyze_keeps_ssrf_guard():
    assert hasattr(vision_tool_module, "_is_safe_image_url")
