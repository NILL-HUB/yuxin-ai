"""视频编辑工具包（裁剪 / 拼接 / 加字幕 / 成片编排）。

必须重导出工厂函数：`Provider._provider_init` 通过
`dynamic_import("...providers.video_edit_tools", "<tool_name>")`（即
`getattr(importlib.import_module(pkg), tool_name)`）取工厂函数，
故包的顶层必须能直接取到与工具同名的可调用对象。
这与同层其它 33 个 provider 的约定一致（见 video_render_tools/__init__.py）。
"""
from .video_concat import video_concat
from .video_reassemble import video_reassemble
from .video_subtitle import video_subtitle
from .video_trim import video_trim

__all__ = ["video_concat", "video_reassemble", "video_subtitle", "video_trim"]
