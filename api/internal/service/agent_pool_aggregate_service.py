import logging
from injector import inject
from internal.entity.agent_pool_entity import AgentSubPoolRegistry

logger = logging.getLogger(__name__)


class AgentInventory:
    """从 AgentSubPoolRegistry 读取可治理 Agent 清单。"""

    def __init__(self, registry: AgentSubPoolRegistry = None):
        self.registry = registry or AgentSubPoolRegistry()

    def list_available_agents(self, pool_intent: str = None) -> list[dict]:
        try:
            pools = (
                self.registry.list_pools()
                if hasattr(self.registry, "list_pools")
                else []
            )
            agents = []
            for pool in pools:
                if not isinstance(pool, dict):
                    continue
                name = pool.get("name", "")
                if pool_intent and name != pool_intent:
                    continue
                pool_agents = pool.get("agents") or []
                if pool_agents:
                    agents.extend(pool_agents)
                else:
                    agents.append(
                        {
                            "agent_id": name,
                            "name": pool.get("label", name),
                            "description": pool.get("description", ""),
                            "pool": name,
                            "visible_to_user": pool.get("visible_to_user", True),
                            "capabilities": pool.get("default_capabilities", []),
                        }
                    )
            return agents
        except Exception:
            logger.warning("Agent 清单读取失败", exc_info=True)
            return []


@inject
class AgentPoolService:
    """Agent 池聚合服务，统一管理注册/查询/健康检查。"""

    def __init__(
        self,
        registry: AgentSubPoolRegistry = None,
        inventory: AgentInventory = None,
    ):
        self.registry = registry or AgentSubPoolRegistry()
        self.inventory = inventory or AgentInventory(self.registry)

    def list_agents(self, pool_intent: str = None) -> list[dict]:
        try:
            return self.inventory.list_available_agents(pool_intent)
        except Exception:
            logger.warning("Agent 列表查询失败", exc_info=True)
            return []

    def get_agent(self, agent_id: str) -> dict | None:
        try:
            agents = self.inventory.list_available_agents()
            for agent in agents:
                if str(agent.get("agent_id", "")) == str(agent_id):
                    return agent
            return None
        except Exception:
            logger.warning("Agent 查询失败", exc_info=True)
            return None

    def health_check(self) -> dict:
        try:
            agents = self.inventory.list_available_agents()
            return {"total_agents": len(agents), "healthy": True}
        except Exception:
            return {"total_agents": 0, "healthy": False}
