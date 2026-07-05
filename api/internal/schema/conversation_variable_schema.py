from pydantic import BaseModel, Field
from typing import Any


class SetVariableReq(BaseModel):
    """设置会话变量请求"""
    name: str = Field(..., description="变量名")
    value: Any = Field(..., description="变量值")
    value_type: str = Field(default="auto", description="值类型: string/int/float/boolean/json/auto")


class BatchSetVariablesReq(BaseModel):
    """批量设置会话变量请求"""
    variables: dict[str, Any] = Field(default_factory=dict, description="变量字典")
