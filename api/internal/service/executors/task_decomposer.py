import logging
from dataclasses import dataclass

from injector import inject
from pydantic import BaseModel, Field

from internal.entity.execution_orchestration_entity import TaskPlan, TaskPlanItem
from internal.service.language_model_service import LanguageModelService

logger = logging.getLogger(__name__)


class TaskPlanItemModel(BaseModel):
    name: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    agent_id: str | None = None
    tools: list[str] = Field(default_factory=list)


class TaskPlanModel(BaseModel):
    items: list[TaskPlanItemModel] = Field(default_factory=list)
    aggregation_strategy: str = "concat"
    needs_decomposition: bool = False


_VALID_STRATEGIES = {"concat", "summarize", "best_of"}


@inject
@dataclass
class TaskDecomposer:
    language_model_service: LanguageModelService

    def decompose(
        self,
        query: str,
        available_agents: list[dict],
        available_tools: list[dict],
    ) -> TaskPlan:
        try:
            plan_model = self._invoke_llm(query, available_agents, available_tools)
            plan = self._to_task_plan(query, plan_model)
            if not plan.items:
                return self._fallback_plan(query)
            return plan
        except Exception:
            logger.warning("任务分解失败，降级为单任务执行", exc_info=True)
            return self._fallback_plan(query)

    def _invoke_llm(
        self,
        query: str,
        available_agents: list[dict],
        available_tools: list[dict],
    ) -> TaskPlanModel:
        llm = self.language_model_service.get_cheap_chat_model()
        structured = llm.with_structured_output(TaskPlanModel)
        prompt = self._build_prompt(query, available_agents, available_tools)
        plan_model = structured.invoke(prompt)

        if not self._validate_dependencies(plan_model):
            logger.warning("任务依赖关系非法或存在循环依赖，降级为单任务执行")
            return self._fallback_plan(query)

        return plan_model

    @staticmethod
    def _validate_dependencies(plan_model: TaskPlanModel) -> bool:
        items = plan_model.items
        if not items:
            return True

        names = {item.name for item in items}

        for item in items:
            for dep in item.depends_on:
                if dep not in names:
                    return False

        visited = [False] * len(items)
        in_stack = [False] * len(items)
        name_to_idx = {item.name: idx for idx, item in enumerate(items)}

        def dfs(idx: int) -> bool:
            visited[idx] = True
            in_stack[idx] = True
            for dep in items[idx].depends_on:
                dep_idx = name_to_idx.get(dep)
                if dep_idx is None:
                    continue
                if in_stack[dep_idx]:
                    return True
                if not visited[dep_idx]:
                    if dfs(dep_idx):
                        return True
            in_stack[idx] = False
            return False

        for i in range(len(items)):
            if not visited[i]:
                if dfs(i):
                    return False

        return True

    def _to_task_plan(self, query: str, plan_model: TaskPlanModel) -> TaskPlan:
        if not plan_model.items:
            return self._fallback_plan(query)

        name_to_id: dict[str, str] = {}
        for idx, item_model in enumerate(plan_model.items):
            name_to_id[item_model.name] = f"subtask_{idx + 1}"

        items: list[TaskPlanItem] = []
        for idx, item_model in enumerate(plan_model.items):
            task_id = name_to_id[item_model.name]
            depends_on = [
                name_to_id.get(dep, dep) for dep in item_model.depends_on
            ]
            items.append(
                TaskPlanItem(
                    task_id=task_id,
                    title=item_model.name,
                    description=item_model.description,
                    depends_on=depends_on,
                    execution_order=idx,
                    agent_id=(item_model.agent_id or "").strip(),
                    tools=[t.strip() for t in item_model.tools if t and t.strip()],
                )
            )

        return TaskPlan(
            original_query=query,
            items=items,
            execution_mode="multi_agent_parallel",
            aggregation_strategy=self._normalize_strategy(plan_model.aggregation_strategy),
        )

    @staticmethod
    def _fallback_plan(query: str) -> TaskPlan:
        return TaskPlan(
            original_query=query,
            items=[
                TaskPlanItem(
                    task_id="subtask_1",
                    title=query,
                    description=query,
                    execution_order=0,
                )
            ],
            execution_mode="multi_agent_parallel",
            aggregation_strategy="concat",
        )

    @staticmethod
    def _normalize_strategy(strategy: str) -> str:
        normalized = str(strategy or "concat").strip().lower()
        return normalized if normalized in _VALID_STRATEGIES else "concat"

    def _build_prompt(
        self,
        query: str,
        available_agents: list[dict],
        available_tools: list[dict],
    ) -> str:
        agents_text = self._format_agents(available_agents)
        tools_text = self._format_tools(available_tools)
        return (
            "你是一个任务规划专家。请根据用户请求、可用智能体列表和可用工具列表，"
            "判断是否需要将任务分解为多个子任务，并给出分解方案。\n\n"
            f"用户请求：{query}\n\n"
            f"可用智能体列表：\n{agents_text}\n\n"
            f"可用工具列表：\n{tools_text}\n\n"
            "分解规则：\n"
            "1. 简单任务不需要分解（needs_decomposition=false，items 只含 1 个子任务）。\n"
            "2. 复杂任务分解为 2-5 个子任务，每个子任务应可独立执行。\n"
            "3. 用 depends_on 标明子任务之间的依赖关系，引用其他子任务的 name。\n"
            "4. 为每个子任务分配 agent_id（从可用智能体列表中选择，无匹配则填 null）"
            "和 tools（从可用工具列表的 name 中选择子集）。\n"
            "5. aggregation_strategy 取值：concat（独立结果拼接）/ summarize（LLM 摘要合并）/ best_of（LLM 选最佳）。\n"
            "6. 每个 item 的 name 必须唯一且简洁，作为依赖引用的标识。\n"
        )

    @staticmethod
    def _format_agents(agents: list[dict]) -> str:
        if not agents:
            return "（无可用智能体）"
        lines = []
        for agent in agents:
            agent_id = agent.get("agent_id") or agent.get("id") or ""
            name = agent.get("name") or agent_id
            desc = agent.get("description") or ""
            lines.append(f"- agent_id: {agent_id} | name: {name} | description: {desc}")
        return "\n".join(lines)

    @staticmethod
    def _format_tools(tools: list[dict]) -> str:
        if not tools:
            return "（无可用工具）"
        lines = []
        for tool in tools:
            name = tool.get("name") or ""
            desc = tool.get("description") or ""
            lines.append(f"- name: {name} | description: {desc}")
        return "\n".join(lines)
