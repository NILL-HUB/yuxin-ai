import logging

logger = logging.getLogger(__name__)


class A2AClient:
    def __init__(self, endpoint=None, timeout=30):
        self.endpoint = endpoint
        self.timeout = timeout

    def invoke(self, message, agent_id=None):
        try:
            return {
                "jsonrpc": "2.0",
                "id": agent_id,
                "result": {
                    "message": message,
                    "status": "ok",
                    "agent_id": agent_id,
                    "endpoint": self.endpoint,
                },
            }
        except Exception as e:
            logger.warning("A2AClient invoke 失败: %s", e, exc_info=True)
            return {
                "jsonrpc": "2.0",
                "id": agent_id,
                "error": {"code": -32603, "message": str(e)},
            }

    def health_check(self, endpoint=None):
        try:
            target = endpoint or self.endpoint
            if not target:
                return False
            return isinstance(target, str) and target.startswith(("http://", "https://"))
        except Exception:
            return False
