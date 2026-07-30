"""工具选择器（方案A）：关键词快通道 + LLM 语义兜底。

设计哲学：
- 关键词优先（零成本，毫秒级）：匹配 task_keywords + tool_name + description 子串
- LLM 兜底（覆盖模糊 query）：当关键词未命中或命中不足时，对全 source_type 候选做语义选择
- 全 source_type 覆盖：builtin + api_tool + mcp + skill + workflow + knowledge

替代之前的 _filter_builtin_candidates 仅 builtin 过滤，让 MCP/Skill/Workflow
也能被 LLM 选中，配合 task_keywords 实现两层快速路径。

使用 get_feature_model("tool_selection") 获取模型，fallback 到 cheap tier。
"""
import json
import logging
from typing import Any

from injector import inject
from langchain_core.messages import HumanMessage, SystemMessage

from .builtin_tool_service import BuiltinToolService
from .language_model_service import LanguageModelService

logger = logging.getLogger(__name__)

# 工具选择系统提示词：让 LLM 根据查询语义选择最相关的工具（全 source_type）
_TOOL_SELECTOR_SYSTEM_PROMPT = """你是一个工具选择专家。根据用户查询，从可用工具列表中选择最相关的工具。

## 任务
1. 分析用户查询的真实意图
2. 从提供的工具列表中，选择最多 {max_tools} 个最相关的工具
3. 只选择用户查询确实需要的工具，不要过度选择

## 输出格式
返回 JSON 数组，每个元素包含：
- "source_type": 工具来源类型（builtin/api_tool/mcp/skill/workflow/knowledge）
- "provider_id": 工具提供者 ID
- "tool_name": 工具名称
- "reason": 选择该工具的理由（简短）

如果用户查询不需要任何工具，返回空数组 []。

## 示例
查询: "现在几点了"
工具列表: [{{"source_type": "builtin", "provider_id": "time", "tool_name": "current_time", "description": "获取当前系统时间"}}]
输出: [{{"source_type": "builtin", "provider_id": "time", "tool_name": "current_time", "reason": "用户询问时间，需要 current_time 工具"}}]

查询: "你好"
工具列表: [{{"source_type": "builtin", "provider_id": "time", "tool_name": "current_time", "description": "获取当前系统时间"}}]
输出: []

查询: "用 GitHub MCP 工具查仓库 issues"
工具列表: [
  {{"source_type": "mcp", "provider_id": "mcp-gh-001", "tool_name": "list_issues", "description": "列出 GitHub 仓库 issues"}},
  {{"source_type": "builtin", "provider_id": "time", "tool_name": "current_time", "description": "获取当前系统时间"}}
]
输出: [{{"source_type": "mcp", "provider_id": "mcp-gh-001", "tool_name": "list_issues", "reason": "用户明确要求用 GitHub MCP 工具查 issues"}}]

## 重要约束
- 只能从提供的工具列表中选择，不能编造工具
- 优先选择用户明确提及的工具（按 source_type 和 tool_name 匹配）
- 如果查询意图模糊，选择 0-1 个工具
- 最多选择 {max_tools} 个工具
- builtin 工具最稳定，无凭证依赖；MCP/Skill/Workflow 需要明确意图才选
"""

# 关键词快速匹配的最小查询长度（短查询留给 LLM）
_MIN_QUERY_LEN_FOR_KEYWORD = 4
# 关键词快速匹配的最大命中数（避免过选）
_MAX_KEYWORD_HITS = 3
# 工具名直接出现的最小长度（避免短名误命中，如 "t" / "ai"）
_MIN_TOOL_NAME_LEN_FOR_SUBSTRING = 4
# 描述子串匹配的最小长度（避免短子串误命中）
_MIN_DESC_SUBSTRING_LEN = 6


@inject
class ToolSelectorService:
    """工具选择器（方案A）：关键词快通道 + LLM 语义兜底。

    架构：
    1. 关键词快通道（_fast_keyword_match）：零成本，毫秒级
       - 匹配 task_keywords（用户配置的关键词列表）
       - 匹配 tool_name 直接出现（如 query="current_time" 直接命中工具名）
       - 匹配 description 子串（如 query="天气" 命中 description 含"天气"的工具）
    2. LLM 语义兜底（_select_with_llm）：覆盖全 source_type
       - 当关键词未命中或命中数 < max_tools 时调用
       - LLM 对 builtin + mcp + skill + workflow + api_tool 候选做语义选择
       - 使用 probe-based 活性检测，避免 LLM 死机
    """

    def __init__(
        self,
        builtin_tool_service: BuiltinToolService | None = None,
        language_model_service: LanguageModelService | None = None,
    ):
        self.builtin_tool_service = builtin_tool_service
        self.language_model_service = language_model_service

    def select_tools(
        self,
        query: str,
        *,
        candidates: list[dict[str, object]] | None = None,
        max_tools: int = 5,
    ) -> list[dict[str, str]]:
        """根据查询语义选择最相关的工具（方案A：关键词优先 + LLM 兜底）。

        Args:
            query: 用户查询文本
            candidates: 工具候选列表（来自 ToolCandidateCollector），若为 None 则自动收集 builtin
            max_tools: 最多选择的工具数量

        Returns:
            工具列表，每个元素包含 source_type, provider_id, tool_name, reason, match_type
            - match_type: "keyword"（关键词命中）或 "llm"（LLM 语义选择）
        """
        if not query or not query.strip():
            return []

        normalized_query = query.strip()
        normalized_lower = normalized_query.lower()

        # 1. 规范化候选列表（全 source_type，不再过滤 builtin）
        all_candidates = self._normalize_candidates(candidates)
        if not all_candidates:
            return []

        # 2. 关键词快通道：优先匹配 task_keywords + tool_name + description 子串
        keyword_hits = self._fast_keyword_match(normalized_lower, all_candidates, max_tools=max_tools)
        if keyword_hits:
            # 关键词命中数已满足需求，直接返回（零 LLM 调用）
            if len(keyword_hits) >= max_tools:
                logger.info(
                    "ToolSelector 关键词快通道命中已满 query=%s hits=%d",
                    normalized_query[:50], len(keyword_hits),
                )
                return keyword_hits[:max_tools]

            # 关键词命中不足，继续 LLM 兜底补充（但避免重复选已命中的工具）
            logger.info(
                "ToolSelector 关键词快通道部分命中 query=%s hits=%d，补充 LLM 选择",
                normalized_query[:50], len(keyword_hits),
            )
            llm_selected = self._select_with_llm(
                normalized_query, all_candidates, max_tools=max_tools,
                exclude_keys={self._candidate_key(h) for h in keyword_hits},
            )
            merged = list(keyword_hits) + llm_selected
            return merged[:max_tools]

        # 3. 关键词未命中，走 LLM 语义兜底（覆盖全 source_type）
        logger.info(
            "ToolSelector 关键词快通道未命中 query=%s，进入 LLM 语义选择",
            normalized_query[:50],
        )
        return self._select_with_llm(normalized_query, all_candidates, max_tools=max_tools)

    # ------------------------------------------------------------------
    # 关键词快通道
    # ------------------------------------------------------------------

    def _fast_keyword_match(
        self,
        query_lower: str,
        candidates: list[dict[str, object]],
        *,
        max_tools: int = 5,
    ) -> list[dict[str, str]]:
        """关键词快速匹配：零成本，毫秒级。

        匹配优先级（从高到低）：
        1. task_keywords 精确包含（用户显式配置的关键词）
        2. tool_name 直接出现在 query 中（如 query="current_time"）
        3. description 子串匹配（如 query="天气" 命中 description 含"天气"）

        Args:
            query_lower: 已小写化的查询文本
            candidates: 规范化后的候选列表
            max_tools: 最多返回数量

        Returns:
            命中的工具列表，每个元素含 match_type="keyword"
        """
        if len(query_lower) < _MIN_QUERY_LEN_FOR_KEYWORD:
            return []

        hits: list[dict[str, str]] = []
        seen_keys: set[str] = set()

        # Pass 1: task_keywords 精确匹配（最高优先级）
        for cand in candidates:
            task_keywords = cand.get("task_keywords") or []
            if not isinstance(task_keywords, list):
                continue
            for kw in task_keywords:
                if not isinstance(kw, str) or len(kw) < 2:
                    continue
                if kw.lower() in query_lower:
                    key = self._candidate_key(cand)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    hits.append({
                        "source_type": str(cand.get("source_type", "")),
                        "provider_id": str(cand.get("provider_id", "")),
                        "tool_name": str(cand.get("tool_name", "")),
                        "reason": f"keyword_hit:{kw}",
                        "match_type": "keyword",
                    })
                    if len(hits) >= min(max_tools, _MAX_KEYWORD_HITS):
                        return hits
                    break  # 同一工具只命中一次

        # Pass 2: tool_name 直接出现
        for cand in candidates:
            tool_name = str(cand.get("tool_name", "")).strip()
            if len(tool_name) < _MIN_TOOL_NAME_LEN_FOR_SUBSTRING:
                continue
            if tool_name.lower() in query_lower:
                key = self._candidate_key(cand)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                hits.append({
                    "source_type": str(cand.get("source_type", "")),
                    "provider_id": str(cand.get("provider_id", "")),
                    "tool_name": tool_name,
                    "reason": f"tool_name_hit:{tool_name}",
                    "match_type": "keyword",
                })
                if len(hits) >= min(max_tools, _MAX_KEYWORD_HITS):
                    return hits

        # Pass 3: description 子串匹配（最宽松，仅当查询足够长时启用）
        if len(query_lower) >= _MIN_DESC_SUBSTRING_LEN:
            for cand in candidates:
                desc = str(cand.get("description", "")).strip().lower()
                if not desc or len(desc) < _MIN_DESC_SUBSTRING_LEN:
                    continue
                # 查询的关键子串出现在 description 中
                # 取查询的前 8 个字符作为匹配窗口（避免整句匹配失败）
                match_window = query_lower[: min(len(query_lower), 12)]
                if len(match_window) >= _MIN_DESC_SUBSTRING_LEN and match_window in desc:
                    key = self._candidate_key(cand)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    hits.append({
                        "source_type": str(cand.get("source_type", "")),
                        "provider_id": str(cand.get("provider_id", "")),
                        "tool_name": str(cand.get("tool_name", "")),
                        "reason": "description_substring_hit",
                        "match_type": "keyword",
                    })
                    if len(hits) >= min(max_tools, _MAX_KEYWORD_HITS):
                        return hits

        return hits

    @staticmethod
    def _candidate_key(cand: dict[str, object]) -> str:
        """生成候选唯一键，用于去重。"""
        return f"{cand.get('source_type', '')}:{cand.get('provider_id', '')}:{cand.get('tool_name', '')}"

    # ------------------------------------------------------------------
    # LLM 语义兜底
    # ------------------------------------------------------------------

    def _select_with_llm(
        self,
        query: str,
        candidates: list[dict[str, object]],
        *,
        max_tools: int = 5,
        exclude_keys: set[str] | None = None,
    ) -> list[dict[str, str]]:
        """LLM 语义选择：覆盖全 source_type。

        Args:
            query: 用户查询文本
            candidates: 规范化后的候选列表
            max_tools: 最多返回数量
            exclude_keys: 已被关键词命中的工具 key 集合，LLM 不再重复选择
        """
        # 过滤掉已命中的候选
        exclude = exclude_keys or set()
        llm_candidates = [
            c for c in candidates
            if self._candidate_key(c) not in exclude
        ]
        if not llm_candidates:
            return []

        # 构造工具列表文本（全 source_type）
        tools_text = self._format_tools_for_llm(llm_candidates)
        if not tools_text:
            return []

        try:
            llm = self._get_selector_llm()
            if llm is None:
                logger.warning("工具选择器 LLM 不可用，跳过 LLM 工具选择")
                return []

            messages = [
                SystemMessage(content=_TOOL_SELECTOR_SYSTEM_PROMPT.format(max_tools=max_tools)),
                HumanMessage(content=f"## 用户查询\n{query}\n\n## 可用工具列表\n{tools_text}\n\n## 请输出 JSON"),
            ]

            # 使用 probe 监控 LLM 活性，避免死机
            response_text = self._invoke_with_probe(llm, messages)
            if not response_text:
                return []

            # 解析 LLM 输出
            selected = self._parse_selection(response_text, llm_candidates, max_tools)
            logger.info(
                "LLM 工具选择完成 query=%s selected=%s",
                query[:50], [t.get("tool_name") for t in selected],
            )
            return selected

        except Exception:
            logger.warning("LLM 工具选择失败，返回空列表", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # 候选规范化
    # ------------------------------------------------------------------

    def _normalize_candidates(
        self, candidates: list[dict[str, object]] | None
    ) -> list[dict[str, object]]:
        """规范化候选列表：全 source_type，统一字段名。

        不再过滤 builtin，让 MCP/Skill/Workflow/API 都能进入 LLM 选择。
        当 candidates 为 None 时，自动收集 builtin 工具（向后兼容）。
        """
        if candidates is None:
            # 自动收集 builtin 工具（向后兼容无候选传入的场景）
            if self.builtin_tool_service is None:
                return []
            result = []
            for provider in self.builtin_tool_service.get_builtin_tools():
                for tool in provider.get("tools", []):
                    # builtin 工具的 task_keywords 来自 YAML 配置（ToolEntity.task_keywords）
                    # + tool.name（兜底），与 _collect_builtin_tools 保持一致
                    tool_keywords = list(tool.get("task_keywords") or [])
                    tool_name = tool.get("name", "")
                    if tool_name and tool_name not in tool_keywords:
                        tool_keywords.append(tool_name)
                    result.append({
                        "source_type": "builtin",
                        "provider_id": provider.get("name", ""),
                        "provider_name": provider.get("label") or provider.get("name", ""),
                        "tool_name": tool_name,
                        "description": tool.get("description", ""),
                        "task_keywords": tool_keywords,
                    })
            return result

        # 规范化传入的候选（全 source_type）
        normalized = []
        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            source_type = str(cand.get("source_type", ""))
            if not source_type:
                continue
            normalized.append({
                "source_type": source_type,
                "provider_id": str(cand.get("provider_id", "")),
                "provider_name": str(cand.get("provider_name", "")),
                "tool_name": str(cand.get("name", "")),
                "description": str(cand.get("description", "")),
                "task_keywords": list(cand.get("task_keywords") or []),
            })
        return normalized

    @staticmethod
    def _format_tools_for_llm(tools: list[dict[str, object]]) -> str:
        """将工具列表格式化为 LLM 可读的文本（含 source_type 信息）"""
        if not tools:
            return ""
        lines = []
        for idx, tool in enumerate(tools, 1):
            source_type = tool.get("source_type", "")
            provider_id = tool.get("provider_id", "")
            tool_name = tool.get("tool_name", "")
            desc = tool.get("description", "")
            lines.append(
                f'{idx}. {{"source_type": "{source_type}", "provider_id": "{provider_id}", "tool_name": "{tool_name}", "description": "{desc}"}}'
            )
        return "\n".join(lines)

    def _get_selector_llm(self):
        """获取工具选择器使用的 LLM

        优先使用 get_feature_model("tool_selection")，fallback 到 cheap tier。
        """
        if self.language_model_service is None:
            return None
        try:
            if hasattr(self.language_model_service, "get_feature_model"):
                llm = self.language_model_service.get_feature_model("tool_selection")
                if llm is not None:
                    return llm
            if hasattr(self.language_model_service, "get_cheap_chat_model"):
                return self.language_model_service.get_cheap_chat_model()
        except Exception:
            logger.warning("获取工具选择器 LLM 失败", exc_info=True)
        return None

    def _invoke_with_probe(self, llm, messages) -> str:
        """调用 LLM 并监控活性，60s 无 token 产出则终止"""
        try:
            if hasattr(self.language_model_service, "invoke_messages_with_probe"):
                return self.language_model_service.invoke_messages_with_probe(
                    llm, messages, timeout_seconds=60,
                )
            response = llm.invoke(messages)
            return getattr(response, "content", str(response))
        except Exception:
            logger.warning("LLM invoke 失败", exc_info=True)
            return ""

    @staticmethod
    def _parse_selection(
        response_text: str,
        candidates: list[dict[str, object]],
        max_tools: int,
    ) -> list[dict[str, str]]:
        """解析 LLM 输出，返回选中的工具列表

        只返回候选列表中存在的工具，过滤 LLM 编造的工具名。
        """
        text = response_text.strip()
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []

        try:
            selected = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            logger.warning("LLM 工具选择输出 JSON 解析失败: %s", text[:200])
            return []

        if not isinstance(selected, list):
            return []

        # 构建候选工具的查找表：(source_type, provider_id, tool_name) -> candidate
        candidate_map: dict[str, dict[str, object]] = {}
        for cand in candidates:
            key = f"{cand.get('source_type', '')}:{cand.get('provider_id', '')}:{cand.get('tool_name', '')}"
            candidate_map[key] = cand

        result: list[dict[str, str]] = []
        seen_keys: set[str] = set()
        for item in selected:
            if not isinstance(item, dict):
                continue
            source_type = str(item.get("source_type", "")).strip()
            provider_id = str(item.get("provider_id", "")).strip()
            tool_name = str(item.get("tool_name", "")).strip()
            if not provider_id or not tool_name:
                continue
            key = f"{source_type}:{provider_id}:{tool_name}"
            if key not in candidate_map:
                continue
            if key in seen_keys:
                continue
            seen_keys.add(key)
            result.append({
                "source_type": source_type,
                "provider_id": provider_id,
                "tool_name": tool_name,
                "reason": str(item.get("reason", "")),
                "match_type": "llm",
            })
            if len(result) >= max_tools:
                break

        return result
