from dataclasses import dataclass
from uuid import UUID

from flask import request
from flask_login import current_user, login_required
from injector import inject
from pydantic import ValidationError

from internal.schema.conversation_variable_schema import (
    BatchSetVariablesReq,
    SetVariableReq,
)
from internal.service.conversation_service import ConversationService
from internal.service.conversation_variable_service import ConversationVariableService
from pkg.response import success_json, success_message, validate_error_json


@inject
@dataclass
class ConversationVariableHandler:
    """会话变量处理器，提供会话变量的增删改查 HTTP 接口。"""
    conversation_variable_service: ConversationVariableService
    conversation_service: ConversationService

    @login_required
    def get_variables(self, conversation_id: UUID):
        """获取指定会话的所有变量列表"""
        # 1.校验会话归属
        self.conversation_service.get_conversation(conversation_id, current_user)

        # 2.调用服务获取变量列表
        variables = self.conversation_variable_service.get_variables(conversation_id)
        return success_json({"list": variables})

    @login_required
    def set_variable(self, conversation_id: UUID):
        """设置（新增/更新）指定会话的一个变量"""
        # 1.校验会话归属
        self.conversation_service.get_conversation(conversation_id, current_user)

        # 2.解析并校验请求数据
        payload = request.get_json(silent=True) or {}
        try:
            req = SetVariableReq(**payload)
        except ValidationError as ex:
            errors = { ".".join(str(loc) for loc in err["loc"]): [err["msg"]] for err in ex.errors() }
            return validate_error_json(errors)

        # 3.调用服务写入变量
        variable = self.conversation_variable_service.set_variable(
            conversation_id,
            req.name,
            req.value,
            req.value_type,
        )
        return success_json(variable)

    @login_required
    def batch_set_variables(self, conversation_id: UUID):
        """批量设置指定会话的多个变量"""
        # 1.校验会话归属
        self.conversation_service.get_conversation(conversation_id, current_user)

        # 2.解析并校验请求数据
        payload = request.get_json(silent=True) or {}
        try:
            req = BatchSetVariablesReq(**payload)
        except ValidationError as ex:
            errors = { ".".join(str(loc) for loc in err["loc"]): [err["msg"]] for err in ex.errors() }
            return validate_error_json(errors)

        # 3.调用服务批量写入变量
        variables = self.conversation_variable_service.batch_set_variables(
            conversation_id,
            req.variables,
        )
        return success_json({"list": variables})

    @login_required
    def delete_variable(self, conversation_id: UUID, name: str):
        """删除指定会话的单个变量"""
        # 1.校验会话归属
        self.conversation_service.get_conversation(conversation_id, current_user)

        # 2.调用服务删除变量
        self.conversation_variable_service.delete_variable(conversation_id, name)
        return success_message("删除变量成功")

    @login_required
    def delete_all_variables(self, conversation_id: UUID):
        """清空指定会话的所有变量"""
        # 1.校验会话归属
        self.conversation_service.get_conversation(conversation_id, current_user)

        # 2.调用服务清空变量
        count = self.conversation_variable_service.delete_variables_by_conversation(conversation_id)
        return success_json({"count": count})
