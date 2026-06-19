class AgentTaskExecutor:
    """将 Agent 类适配为 ExecutionCoordinator 的 TaskExecutor。"""

    def __init__(self, agent_class, agent_config=None, tools=None, llm=None, history=None, query=""):
        self.agent_class = agent_class
        self.agent_config = agent_config
        self.tools = tools or []
        self.llm = llm
        self.history = history or []
        self.query = query

    def execute(self, item) -> dict:
        try:
            agent = self.agent_class(self.agent_config, self.tools)
            collected_answer = ""
            for thought in agent.stream({
                "messages": [self.llm.convert_to_human_message(item.description or self.query, [])],
                "history": self.history,
                "long_term_memory": "",
                "user_memory": "",
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
