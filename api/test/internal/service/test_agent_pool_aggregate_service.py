from unittest.mock import MagicMock

from internal.entity.agent_pool_entity import AgentSubPoolRegistry
from internal.service.agent_pool_aggregate_service import (
    AgentInventory,
    AgentPoolService,
)


def _registry_with_agents():
    registry = MagicMock()
    registry.list_pools.return_value = [
        {
            "name": "general",
            "label": "通用",
            "visible_to_user": True,
            "description": "默认兜底",
            "default_capabilities": [],
            "task_keywords": [],
            "agents": [
                {"agent_id": "agent-1", "name": "Agent 1"},
                {"agent_id": "agent-2", "name": "Agent 2"},
            ],
        },
        {
            "name": "coding",
            "label": "编程",
            "visible_to_user": True,
            "description": "写代码",
            "default_capabilities": ["coding"],
            "task_keywords": ["写代码"],
            "agents": [
                {"agent_id": "agent-3", "name": "Agent 3"},
            ],
        },
    ]
    return registry


def test_inventory_list_available_agents_should_return_agents_from_pools():
    registry = _registry_with_agents()

    inventory = AgentInventory(registry=registry)
    agents = inventory.list_available_agents()

    assert [agent["agent_id"] for agent in agents] == [
        "agent-1",
        "agent-2",
        "agent-3",
    ]
    registry.list_pools.assert_called_once()


def test_inventory_list_available_agents_should_filter_by_pool_intent():
    registry = _registry_with_agents()

    inventory = AgentInventory(registry=registry)
    agents = inventory.list_available_agents(pool_intent="coding")

    assert [agent["agent_id"] for agent in agents] == ["agent-3"]


def test_inventory_list_available_agents_should_fallback_to_pool_meta_when_no_agents():
    inventory = AgentInventory(registry=AgentSubPoolRegistry())

    agents = inventory.list_available_agents()

    assert len(agents) == 7
    assert agents[0]["agent_id"] == "general"
    assert agents[0]["name"] == "通用"
    assert agents[0]["pool"] == "general"


def test_inventory_list_available_agents_should_return_empty_when_registry_raises():
    registry = MagicMock()
    registry.list_pools.side_effect = RuntimeError("boom")

    inventory = AgentInventory(registry=registry)

    assert inventory.list_available_agents() == []


def test_pool_service_list_agents_should_delegate_to_inventory():
    inventory = MagicMock()
    inventory.list_available_agents.return_value = [{"agent_id": "x"}]
    service = AgentPoolService(registry=MagicMock(), inventory=inventory)

    result = service.list_agents("coding")

    inventory.list_available_agents.assert_called_once_with("coding")
    assert result == [{"agent_id": "x"}]


def test_pool_service_get_agent_should_return_matched_agent():
    inventory = MagicMock()
    inventory.list_available_agents.return_value = [
        {"agent_id": "agent-1", "name": "A"},
        {"agent_id": "agent-2", "name": "B"},
    ]
    service = AgentPoolService(registry=MagicMock(), inventory=inventory)

    agent = service.get_agent("agent-2")

    assert agent == {"agent_id": "agent-2", "name": "B"}


def test_pool_service_get_agent_should_return_none_when_not_found():
    inventory = MagicMock()
    inventory.list_available_agents.return_value = [{"agent_id": "agent-1"}]
    service = AgentPoolService(registry=MagicMock(), inventory=inventory)

    assert service.get_agent("missing") is None


def test_pool_service_health_check_should_return_stats():
    inventory = MagicMock()
    inventory.list_available_agents.return_value = [
        {"agent_id": "a"},
        {"agent_id": "b"},
        {"agent_id": "c"},
    ]
    service = AgentPoolService(registry=MagicMock(), inventory=inventory)

    result = service.health_check()

    assert result == {"total_agents": 3, "healthy": True}


def test_pool_service_health_check_should_be_unhealthy_when_inventory_raises():
    inventory = MagicMock()
    inventory.list_available_agents.side_effect = RuntimeError("boom")
    service = AgentPoolService(registry=MagicMock(), inventory=inventory)

    result = service.health_check()

    assert result == {"total_agents": 0, "healthy": False}
