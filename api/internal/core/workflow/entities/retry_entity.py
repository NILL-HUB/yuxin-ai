"""节点重试配置实体。

参考 Dify 的节点级 retry 设计，为工作流节点提供失败重试能力。
配置项：
- retry_on_fail: 是否在失败时重试（默认 False）
- max_tries: 最大尝试次数（含首次执行，默认 3，即最多重试 2 次）
- retry_interval: 重试间隔（秒，默认 1.0）
"""

from pydantic import BaseModel, field_validator

from internal.exception import ValidateErrorException


class RetryConfig(BaseModel):
    """节点重试配置。

    参考 Dify 的节点级 retry 设计：
    - retry_on_fail: 是否在失败时重试（默认 False）
    - max_tries: 最大重试次数（含首次执行，默认 3，即最多重试 2 次）
    - retry_interval: 重试间隔（秒，默认 1.0）
    """

    retry_on_fail: bool = False  # 是否开启重试
    max_tries: int = 3  # 最大尝试次数（含首次，所以重试次数 = max_tries - 1）
    retry_interval: float = 1.0  # 重试间隔（秒）

    @field_validator("max_tries")
    def validate_max_tries(cls, v: int) -> int:
        """校验最大尝试次数，取值范围为 [1, 10]。"""
        if v < 1:
            raise ValidateErrorException("最大尝试次数不能小于1")
        if v > 10:
            raise ValidateErrorException("最大尝试次数不能超过10")
        return v

    @field_validator("retry_interval")
    def validate_retry_interval(cls, v: float) -> float:
        """校验重试间隔，取值范围为 [0, 60] 秒。"""
        if v < 0:
            raise ValidateErrorException("重试间隔不能为负数")
        if v > 60:
            raise ValidateErrorException("重试间隔不能超过60秒")
        return v

    @property
    def retry_count(self) -> int:
        """实际重试次数（不含首次执行）。"""
        return max(0, self.max_tries - 1) if self.retry_on_fail else 0
