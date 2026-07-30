from datetime import UTC, datetime, timezone, timedelta
from typing import Any
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class CurrentTimeInput(BaseModel):
    """获取当前时间工具的输入模型"""
    timezone_offset: int = Field(
        default=8,
        description="目标时区相对 UTC 的偏移小时数，默认 8（北京时间 UTC+8）。取值范围 -12 ~ 14",
    )


class CurrentTimeTool(BaseTool):
    """获取当前时间的工具，支持时区转换"""
    name: str = "current_time"
    description: str = (
        "获取当前系统时间。默认返回北京时间(UTC+8)，可通过 timezone_offset 参数指定其他时区。"
        "返回格式为 'YYYY-MM-DD HH:MM:SS TZ'，同时附带 UTC 时间用于校验。"
    )
    args_schema: type[BaseModel] = CurrentTimeInput

    def _run(self, timezone_offset: int = 8, **kwargs: Any) -> str:
        """获取当前时间，默认北京时间，支持时区偏移"""
        # 限制偏移范围，避免非法输入
        offset = max(-12, min(14, int(timezone_offset)))
        utc_now = datetime.now(UTC)
        target_tz = timezone(timedelta(hours=offset))
        local_now = utc_now.astimezone(target_tz)

        # 生成时区标签（如 UTC+8、UTC-4）
        tz_label = f"UTC{'+' if offset >= 0 else ''}{offset}"

        # 返回本地时间和 UTC 时间，供 LLM 准确呈现
        return (
            f"本地时间({tz_label}): {local_now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"UTC时间: {utc_now.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

    async def _arun(self, timezone_offset: int = 8, **kwargs: Any) -> str:
        """异步获取当前时间"""
        return self._run(timezone_offset=timezone_offset, **kwargs)


def current_time(**kwargs: Any) -> BaseTool:
    """工厂函数：返回获取当前时间的 LangChain 工具"""
    return CurrentTimeTool()
