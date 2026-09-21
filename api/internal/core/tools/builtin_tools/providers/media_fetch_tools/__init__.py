"""外部素材获取工具包。

必须重导出工厂函数：`Provider._provider_init` 通过
`dynamic_import("...providers.media_fetch_tools", "fetch_media")`（即
`getattr(importlib.import_module(pkg), tool_name)`）取工厂函数，
故包的顶层必须能直接取到与工具同名的可调用对象。
"""
from .fetch_media import fetch_media

__all__ = ["fetch_media"]