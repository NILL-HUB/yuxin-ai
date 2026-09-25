"""管理端 Agent 请求/响应 schema。"""
from marshmallow import Schema, fields


class AdminAgentAssignablePermissionsResp(Schema):
    """可下放权限点响应。

    - ``codes``：纯权限码列表（保持既有契约，供只取码的调用方使用）。
    - ``permissions``：与 ``codes`` 同源的语义化明细（code/name/resource/action/
      description），供前端直接渲染中文名并按 resource 分组——避免前端为拿语义
      再去调全量 ``/admin/permissions``（那会绕过"展示即受限"的安全交集）。
    """

    codes = fields.List(fields.String(), dump_default=[])
    permissions = fields.List(fields.Dict(), dump_default=[])


class AdminAgentCreateReq(Schema):
    """创建管理端 Agent（设计 §4、§10.1）。

    `granted_permissions` 的"可下放"合法性由服务层 `assert_grantable`
    校验（第二层安全边界），此处只做类型约束。
    """

    name = fields.String(required=True)
    description = fields.String(load_default="")
    prompt_key = fields.String(load_default=None, allow_none=True)
    granted_permissions = fields.List(fields.String(), load_default=list)
    automation_policy = fields.Dict(load_default=dict)
    # 预算闸门配置（§6.3）：daily/monthly 的执行次数与 token 上限，空 = 不限制
    budget_config = fields.Dict(load_default=dict)


class AdminAgentUpdateReq(Schema):
    """更新管理端 Agent；未提供的字段保持原值（`None` = 不修改）。"""

    name = fields.String(load_default=None, allow_none=True)
    description = fields.String(load_default=None, allow_none=True)
    prompt_key = fields.String(load_default=None, allow_none=True)
    granted_permissions = fields.List(
        fields.String(), load_default=None, allow_none=True
    )
    automation_policy = fields.Dict(load_default=None, allow_none=True)
    budget_config = fields.Dict(load_default=None, allow_none=True)
    enabled = fields.Boolean(load_default=None, allow_none=True)


class AdminAgentResp(Schema):
    id = fields.String()
    name = fields.String()
    description = fields.String()
    prompt_key = fields.String(allow_none=True)
    granted_permissions = fields.List(fields.String(), dump_default=[])
    automation_policy = fields.Dict(dump_default={})
    budget_config = fields.Dict(dump_default={})
    enabled = fields.Boolean()
    created_at = fields.Integer(allow_none=True)
    updated_at = fields.Integer(allow_none=True)


class AdminAgentListResp(Schema):
    items = fields.List(fields.Nested(AdminAgentResp), dump_default=[])


class AdminAgentInvokeReq(Schema):
    """执行一个板块动作的请求体。

    `board` / `action` 的合法性由板块动作注册表（`admin_agent_boards.py`）
    判定——未登记即拒绝（fail closed），此处只校验"非空"。
    """

    board = fields.String(required=True)
    action = fields.String(required=True)
    payload = fields.Dict(load_default=dict)


class AdminAgentDraftResp(Schema):
    id = fields.String()
    policy_type = fields.String()
    target_id = fields.String()
    before_config = fields.Dict()
    after_config = fields.Dict()
    diff = fields.Dict()
    impact = fields.Dict()
    status = fields.String()
    created_at = fields.Integer(allow_none=True)


class AdminAgentDraftListResp(Schema):
    items = fields.List(fields.Nested(AdminAgentDraftResp), dump_default=[])
