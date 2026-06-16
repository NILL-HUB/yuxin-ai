from internal.service.admin_rbac_service import AdminRbacService


def test_default_permissions_should_include_orchestration_flags():
    permissions = {item["code"]: item for item in AdminRbacService.DEFAULT_PERMISSIONS}

    assert permissions["orchestration_flag:read"] == {
        "code": "orchestration_flag:read",
        "name": "查看调度开关",
        "resource": "orchestration_flag",
        "action": "read",
        "description": "查看调度平台发布开关",
    }
    assert permissions["orchestration_flag:update"] == {
        "code": "orchestration_flag:update",
        "name": "管理调度开关",
        "resource": "orchestration_flag",
        "action": "update",
        "description": "启停调度平台发布开关",
    }
    assert permissions["orchestration_release:read"] == {
        "code": "orchestration_release:read",
        "name": "查看调度上线验收",
        "resource": "orchestration_release",
        "action": "read",
        "description": "查看调度平台上线验收报告",
    }
    assert permissions["routing_quality:read"] == {
        "code": "routing_quality:read",
        "name": "查看路由质量",
        "resource": "routing_quality",
        "action": "read",
        "description": "查看路由质量指标与调优建议",
    }
    assert permissions["routing_quality:feedback"] == {
        "code": "routing_quality:feedback",
        "name": "提交路由反馈",
        "resource": "routing_quality",
        "action": "feedback",
        "description": "提交路由质量反馈",
    }
