"""admin_agent feature 注册守卫（AGENTS.md：公共 AI 配置必须走 admin 板块）。

管理端 Agent 的成本由系统承担（设计 §6.2：billable=False → system_borne），
但**必须**经 `_BUILTIN_FEATURES` 注册，让管理员能在
`/admin/public-ai-features` 为其绑定模型与档位——不得在业务代码里硬编码模型。
"""
import internal.service.public_ai_feature_service as public_ai_feature_service


def _feature(feature_key):
    for item in public_ai_feature_service._BUILTIN_FEATURES:
        if item["feature_key"] == feature_key:
            return item
    return None


def test_admin_agent_feature_registered():
    feature = _feature("admin_agent")

    assert feature is not None, "必须在 _BUILTIN_FEATURES 注册 admin_agent"
    assert feature["billable"] is False, "管理端 Agent 成本由系统承担（设计 §6.2）"
    assert feature["model_type"] == "chat"
    assert feature["fallback_tier"], "必须给 fallback_tier，避免未绑定时无法降级"


def test_feature_key_matches_chat_service_constant():
    from internal.service.admin_agent_chat_service import FEATURE_KEY

    assert FEATURE_KEY == "admin_agent"
    assert _feature(FEATURE_KEY) is not None
