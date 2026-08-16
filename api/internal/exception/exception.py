from dataclasses import field
from typing import Any
from pkg.response import HttpCode


class CustomException(Exception):
    """基础自定义异常信息"""
    code: HttpCode = HttpCode.FAIL
    message: str = ""
    data: Any = field(default_factory=dict)

    def __init__(self, message: str = None, data: Any = None, *, reason_code: str | None = None):
        # 把 message 透传给 Exception，保证 str(exc) 与业务 message 一致。
        normalized_message = message or ""
        normalized_data = data
        if reason_code:
            if normalized_data is None:
                normalized_data = {}
            if isinstance(normalized_data, dict):
                normalized_data = dict(normalized_data)
                normalized_data.setdefault("reason_code", reason_code)
        super().__init__(normalized_message)
        self.message = normalized_message
        self.data = normalized_data

    def __str__(self) -> str:
        return self.message


class FailException(CustomException):
    """通用失败异常"""
    pass


class NotFoundException(CustomException):
    """未找到数据异常"""
    code = HttpCode.NOT_FOUND


class ConflictException(CustomException):
    """资源冲突异常"""
    code = HttpCode.CONFLICT


class UnauthorizedException(CustomException):
    """未授权异常"""
    code = HttpCode.UNAUTHORIZED


class ForbiddenException(CustomException):
    """无权限异常"""
    code = HttpCode.FORBIDDEN


class ValidateErrorException(CustomException):
    """数据验证异常"""
    code = HttpCode.VALIDATE_ERROR


class DeviceMismatchException(ValidateErrorException):
    """本机文件恢复时检测到删除设备与当前设备不一致。

    recorded_device / current_device 供前端展示「这并非本机删除的文件」提示。
    """

    def __init__(
        self,
        message: str = "该文件并非在本机删除，恢复前请确认恢复方式",
        *,
        recorded_device: dict | None = None,
        current_device: dict | None = None,
        entry_id: str | None = None,
    ):
        super().__init__(
            message,
            {
                "recorded_device": recorded_device or {},
                "current_device": current_device or {},
                "entry_id": entry_id or "",
            },
        )
        self.recorded_device = recorded_device or {}
        self.current_device = current_device or {}
        self.entry_id = entry_id or ""
