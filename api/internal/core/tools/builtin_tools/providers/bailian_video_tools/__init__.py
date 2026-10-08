"""百炼视频工具包（通义万相 AI 视频生成）。

必须重导出工厂函数：`Provider._provider_init` 通过
`dynamic_import("...providers.bailian_video_tools", "<tool_name>")` 取工厂函数，
故包的顶层必须能直接取到与工具同名的可调用对象（与同层其它 provider 约定一致）。
"""
from .bailian_video_generate import bailian_video_generate

__all__ = ["bailian_video_generate"]
