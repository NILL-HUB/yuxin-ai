class AgentTaskExecutor:
    """将 Agent 类适配为 ExecutionCoordinator 的 TaskExecutor。"""

    def __init__(self, agent_class, agent_config=None, tools=None, llm=None, history=None, query="", long_term_memory="", user_memory=""):
        self.agent_class = agent_class
        self.agent_config = agent_config
        self.tools = tools or []
        self.llm = llm
        self.history = history or []
        self.query = query
        self.long_term_memory = long_term_memory
        self.user_memory = user_memory

    def execute(self, item) -> dict:
        try:
            agent_config = self._resolve_agent_config(item)
            agent = self.agent_class(llm=self.llm, agent_config=agent_config)
            collected_answer = ""
            for thought in agent.stream({
                "messages": [self.llm.convert_to_human_message(item.description or self.query, [])],
                "history": self.history,
                "long_term_memory": self.long_term_memory,
                "user_memory": self.user_memory,
            }):
                answer = getattr(thought, "answer", "")
                if answer:
                    collected_answer = answer
            return {
                "agent_id": item.task_id,
                "task_id": item.task_id,
                "answer": collected_answer,
                "confidence": 1.0,
                "sources": [],
                "tool_calls": [],
                "warnings": [],
                "errors": [],
                "cost": {},
                "metadata": {"title": item.title},
            }
        except Exception:
            return {
                "agent_id": "",
                "task_id": item.task_id,
                "answer": "",
                "errors": ["agent_execution_failed"],
                "warnings": [],
                "confidence": 0,
            }

    def _resolve_agent_config(self, item):
        agent_config = self.agent_config
        item_tools = getattr(item, "tools", None) or []
        if not item_tools:
            return agent_config
        try:
            from internal.core.agent.entities.agent_entity import AgentConfig

            if isinstance(agent_config, AgentConfig):
                base_tools = list(agent_config.tools or [])
                if not base_tools:
                    return agent_config
                requested = {str(name).strip() for name in item_tools if name}
                filtered = [
                    tool for tool in base_tools
                    if getattr(tool, "name", None) in requested
                ]
                if filtered and len(filtered) != len(base_tools):
                    return agent_config.model_copy(update={"tools": filtered})
        except Exception:
            return agent_config
        return agent_config
