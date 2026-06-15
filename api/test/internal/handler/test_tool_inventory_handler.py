from types import SimpleNamespace
from uuid import uuid4

from internal.handler.tool_inventory_handler import ToolInventoryHandler


class _Collector:
    def collect(self, account_id):
        return [
            {
                "id": "tool-1",
                "name": "Search",
                "description": "Search tool",
                "source_type": "mcp",
                "provider_id": "provider-1",
                "provider_name": "MCP",
                "inputs": [],
                "visibility": "public",
                "enabled": True,
                "metadata": {
                    "tool_pool": "mcp",
                    "risk_level": "medium",
                    "permission_scope": "public",
                    "health_status": "healthy",
                    "cost_level": "low",
                },
            }
        ]


class _PolicyFilter:
    def filter(self, candidates, **kwargs):
        return {"candidates": candidates, "filtered_out_tools": []}


def test_tool_inventory_route_should_be_registered(client):
    response = client.get("/tool-inventory")

    assert response.status_code == 200


def test_tool_inventory_handler_should_return_governance_fields(app):
    handler = ToolInventoryHandler(collector=_Collector(), policy_filter=_PolicyFilter())

    with app.test_request_context("/tool-inventory"):
        response, status_code = handler.get_tool_inventory(
            current_account=SimpleNamespace(id=uuid4())
        )

    assert status_code == 200
    data = response.json["data"]
    assert data["candidates"][0]["metadata"]["tool_pool"] == "mcp"
    assert data["candidates"][0]["metadata"]["risk_level"] == "medium"
    assert data["candidates"][0]["metadata"]["health_status"] == "healthy"
    assert data["candidates"][0]["runtime_name"] == "mcp__provider_1__search"
    assert data["candidates"][0]["mounted"] is False
    assert data["candidates"][0]["mount_reason"] == "not_mounted"
    assert data["filtered_out_tools"] == []
