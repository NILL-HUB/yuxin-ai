from typing import Any, List, Protocol


class UserMemoryServicePort(Protocol):
    """用户记忆服务端口定义"""

    def recall_relevant_memories(
        self, account: Any, query: str, top_k: int = 5, scope: str = "global"
    ) -> List[dict]:
        ...
