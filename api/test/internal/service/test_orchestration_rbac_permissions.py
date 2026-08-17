from internal.core.rbac import PERMISSION_BY_CODE


def _assert_permission(code, expected_name, expected_resource, expected_action, expected_description):
    permission = PERMISSION_BY_CODE[code]
    assert permission.code == code
    assert permission.name == expected_name
    assert permission.resource == expected_resource
    assert permission.action == expected_action
    assert permission.description == expected_description


def test_default_permissions_should_include_orchestration_flags():
    _assert_permission(
        "orchestration_flag:read",
        "查看调度开关",
        "orchestration_flag",
        "read",
        "查看调度平台发布开关",
    )
    _assert_permission(
        "orchestration_flag:update",
        "管理调度开关",
        "orchestration_flag",
        "update",
        "启停调度平台发布开关",
    )
    _assert_permission(
        "orchestration_release:read",
        "查看调度上线验收",
        "orchestration_release",
        "read",
        "查看调度平台上线验收报告",
    )
    _assert_permission(
        "routing_quality:read",
        "查看路由质量",
        "routing_quality",
        "read",
        "查看路由质量指标与调优建议",
    )
    _assert_permission(
        "routing_quality:feedback",
        "提交路由反馈",
        "routing_quality",
        "feedback",
        "提交路由质量反馈",
    )
