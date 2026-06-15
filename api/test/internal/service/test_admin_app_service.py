from datetime import datetime
from uuid import uuid4

from internal.entity.agent_entity import DEFAULT_AGENT_METADATA
from internal.model.app import App
from internal.service.admin_app_service import AdminAppService


class _QueryStub:
    def __init__(self, *, one_or_none_result=None):
        self._one_or_none_result = one_or_none_result

    def filter(self, *_args, **_kwargs):
        return self

    def one_or_none(self):
        return self._one_or_none_result


class _SessionStub:
    def __init__(self, app):
        self.app = app
        self.committed = False

    def query(self, *_args, **_kwargs):
        return _QueryStub(one_or_none_result=self.app)

    def commit(self):
        self.committed = True


def _app(**kwargs):
    defaults = {
        "id": uuid4(),
        "account_id": uuid4(),
        "name": "配置 Agent",
        "icon": "🤖",
        "description": "可配置 Agent",
        "status": "published",
        "is_public": True,
        "agent_metadata": None,
        "published_at": datetime(2030, 1, 1, 0, 0, 0),
    }
    defaults.update(kwargs)
    return App(**defaults)


def test_update_app_should_update_agent_metadata_fields():
    app = _app()
    session = _SessionStub(app)
    service = AdminAppService(session=session)

    result = service.update_app(
        app.id,
        agent_metadata={
            "primary_pool": "customer_support",
            "secondary_pools": ["sales", "ops"],
            "capabilities": ["faq"],
            "task_types": ["customer_service"],
            "model_tier": "balanced",
            "cost_level": "low",
            "routing_priority": 50,
            "allowed_tool_categories": ["knowledge"],
        },
    )

    assert session.committed is True
    assert app.agent_metadata == {
        **DEFAULT_AGENT_METADATA,
        "primary_pool": "customer_support",
        "secondary_pools": ["sales", "ops"],
        "capabilities": ["faq"],
        "task_types": ["customer_service"],
        "model_tier": "balanced",
        "cost_level": "low",
        "routing_priority": 50,
        "allowed_tool_categories": ["knowledge"],
    }
    assert result["agent_metadata"]["primary_pool"] == "customer_support"
