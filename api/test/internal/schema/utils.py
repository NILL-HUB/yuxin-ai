from __future__ import annotations

import io
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from internal.context import request
from werkzeug.datastructures import CombinedMultiDict, ImmutableMultiDict


def build_formdata():
    """从当前 request scope 提取表单数据，供 wtforms Form(formdata=...) 使用。"""
    if request.files:
        return CombinedMultiDict(
            (request.files, ImmutableMultiDict(request.form or {}))
        )
    if request.form:
        return ImmutableMultiDict(request.form)
    if request.json is not None:
        return ImmutableMultiDict(request.json)
    return None


def ns(**kwargs: Any) -> SimpleNamespace:
    """快速构造带属性访问能力的测试对象。"""
    return SimpleNamespace(**kwargs)


def utc_dt(
    year: int = 2024,
    month: int = 1,
    day: int = 1,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> datetime:
    """生成 UTC datetime，便于断言时间戳转换结果。"""
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def upload(filename: str, content: bytes | None = None):
    """构造 Flask/Werkzeug 可识别的上传文件元组。"""
    return (io.BytesIO(content or b"test-bytes"), filename)
