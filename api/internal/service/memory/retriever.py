"""混合检索器（MemoryRetriever）。

融合语义/关键词/图/主题多通道，实现 System 1（Digest 缓存快速路径）与
System 2（TKG 粗召回 + 向量精召回 + Community 主题召回 + 图扩展 +
混合评分 + 早停）的双路架构。

双路架构:
    - System 1: Digest 缓存命中时直接返回，不触发深度搜索
    - System 2: TKG BM25 粗召回 → pgvector 向量精召回 → Community 主题召回
                → SpreadActivation 图扩展 → 混合评分 → 时间衰减 → 早停截断

Community 主题召回（P5 新皮层）:
    巩固阶段的 Community 归纳产出高层主题节点；检索时经 communityFullText
    命中主题，主题本身作为候选、其成员（语义/实体）由图扩展沿
    TOPIC_OF/MEMBER_OF 边拉起，形成「主题→成员」间接证据链。

策略路由（D1 PolicyRouter 接线，2026-10-04）:
    ``route_policy`` 用规则分类（``llm_available=False``，微秒级、不占对话预算）
    得到意图 → ``select_views`` 视图子集 + ``should_use_system2`` 选路；
    ``retrieve_for_chat`` 是用户侧与 admin 侧**共用的对话召回入口**：
    prefer_deep 时「深检优先、空则摘要兜底」，否则「摘要优先、空则深检」。
    视图子集经 ``RetrievalOptions.view_names`` 下推到四个召回分支
    （TKG 标签谓词 / pgvector memory_type / Community 标签 / 图扩展节点标签），
    不允许任何分支绕过。

机密记忆闸门（2026-10-05 结构化）:
    ``_split_confidential`` 是**唯一**的机密切分点：普通记忆直接注入；机密记忆按
    ``ConfidentialAccess``（对话中明确确认 → 全部放行；确认卡片授权 → id 白名单）
    决定是否注入，未放行的条目以结构化形式回填 ``status["withheld"]``，供上层发
    确认卡片（见 ``internal/entity/memory_recall_entity.py``）。

降级策略:
    - Neo4j 不可用时 TKG 召回返回空列表
    - pgvector 不可用时向量召回返回空列表
    - EmbeddingsService 不可用时向量召回跳过
    - System 1 未命中时自动降级到 System 2
    - 意图分类失败时退化为「不限视图 + 摘要优先」（与接线前行为一致）

设计参考:
    docs/prd/memory-system/02-storage-and-retrieval.md §6.2
    docs/prd/memory-system/03-consolidation-skill-policy-api.md §9.1
    docs/prd/memory-system/execution/03-track-b-storage-retrieval.md B3
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from typing import Optional

from internal.config.memory_settings import settings
from internal.entity.memory_owner_entity import MemoryOwnerKey, MemoryOwnerKeyError
from internal.entity.memory_recall_entity import ConfidentialAccess, WithheldConfidential
from internal.model.memory_models import (
    RetrievalConfig,
    RetrievalOptions,
    RetrievalResult,
    RetrievalScore,
    SpreadConfig,
)
from internal.service.memory.sensitivity import (
    PII_TYPE_LABELS,
    redacted_preview,
    sensitivity_label,
)
from internal.service.memory.spread_activation import SpreadActivation
from internal.service.memory.metrics import MetricsCollector

logger = logging.getLogger(__name__)


@dataclass
class RetrievalRoute:
    """一次查询的选路决策（规则分类，LLM 不参与）。"""

    intent: str
    views: list[str] = field(default_factory=list)
    prefer_deep: bool = False


def digest_has_substance(text: str) -> bool:
    """Digest 是否有实质内容（全"暂无/无"的占位摘要视为未命中）。

    依据真实样本：占位摘要形如「用户画像：暂无  已习得技能：暂无 …」——没有任何
    列表/表格行；有内容的摘要会出现以 "-" 或 "|" 开头的条目。占位摘要若被当作命中，
    会把「用户画像：暂无」注入提示词，反而诱导模型回答"我没有你的记录"。

    ⚠️ **元数据行不算实质**：旧模板会渲染成 `- 更新时间：2026-10-05 18:13`（带 `-`
    前缀），若被当作内容，占位摘要就会被误判为命中——真机缺陷（2026-10-05）：
    摘要优先的意图因此**不再深检**，记忆读回只拿到占位文本、机密确认卡片也拿不到。
    故按三类跳过：① 键名属元数据（更新/时间/规则/…）；② 值只是日期或数字；
    ③ 值只是 PII 类型枚举（模板固定的「机密记忆：身份证/手机号/…」说明行）。

    ③ 用 ``PII_TYPE_LABELS`` 判定而非再列关键词：模板改版时说明行的取值必然仍是
    这几个标签的组合，不会因为措辞变化而漏判（避免"加不完的关键词表"）。
    """
    if not text:
        return False
    meta_keys = ("更新", "时间", "日期", "版本", "规则", "说明", "总计", "统计", "date", "update", "version")
    # 模板说明行里的简称（身份证 / 银行卡）与标签（身份证号 / 银行卡号）不同形，
    # 故按「标签原子 + 去尾号 + 补尾号」三态展开后比对。
    label_atoms: set[str] = set()
    for label in PII_TYPE_LABELS.values():
        for atom in label.replace("、", "/").split("/"):
            atom = atom.strip()
            if not atom:
                continue
            label_atoms.update({atom, atom.rstrip("号"), f"{atom}号"})
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#=【>":
            continue
        if line[0] not in "-*|":
            continue
        body = line.lstrip("-*| ").strip()
        key, value = "", body
        for sep in ("：", ":"):
            if sep in body:
                key, value = body.split(sep, 1)
                break
        if any(token in key.lower() for token in meta_keys):
            continue
        residue = value.strip().strip("-—|* ").strip()
        for token in ("暂无", "无", "空", "None", "none"):
            residue = residue.replace(token, "")
        if len(residue) < 4:
            continue
        # 纯日期/时间/数字（如 2026-10-05 18:13）不是内容
        digits_only = (
            residue.replace("-", "")
            .replace(":", "")
            .replace("/", "")
            .replace(".", "")
            .replace(" ", "")
            .replace("T", "")
        )
        if digits_only.isdigit():
            continue
        # 只是 PII 类型枚举（如「身份证/手机号/银行卡/密码/验证码/密钥」）→ 模板说明行
        fragments = residue.replace("、", "/").replace("，", "/").replace(",", "/").split("/")
        fragments = [fragment.strip() for fragment in fragments if fragment.strip()]
        if fragments and all(fragment in label_atoms for fragment in fragments):
            continue
        return True
    return False


class MemoryRetriever:
    """混合检索器 System 1/2 双路。

    不使用 ``@inject``：无注入依赖，配置从 ``settings.retrieval`` 读取，
    Neo4j 驱动与 SQLAlchemy db 由构造函数传入或运行时获取。
    EmbeddingsService 通过 ``current_app.injector`` 获取。
    """

    def __init__(
        self,
        neo4j_driver=None,
        db=None,
        config: Optional[RetrievalConfig] = None,
        embeddings_service=None,
        digest_manager=None,
    ) -> None:
        """初始化混合检索器。

        Args:
            neo4j_driver: Neo4j 驱动
            db: SQLAlchemy 实例
            config: RetrievalConfig 实例，None 时使用 settings.retrieval
            embeddings_service: EmbeddingsService 实例（用于查询向量化）
            digest_manager: DigestManager 实例（System 1 快速路径用）
        """
        self._driver = neo4j_driver
        self._db = db
        self._config = config or settings.retrieval
        self._embeddings_service = embeddings_service
        self._digest_manager = digest_manager

    # =========================================================
    # 主入口
    # =========================================================

    def retrieve(
        self,
        query: str,
        owner_key: str,
        options: Optional[RetrievalOptions] = None,
    ) -> list[RetrievalResult]:
        """主检索入口，先尝试 System 1 快速路径，未命中则走 System 2 深度搜索。

        Args:
            query: 查询文本
            owner_key: 记忆主体键（用户主体为裸 UUID，见 MemoryOwnerKey）
            options: 检索选项，None 时使用默认值

        Returns:
            检索结果列表
        """
        import time as _time

        start = _time.perf_counter()

        if not query or not query.strip():
            MetricsCollector.record_retrieve(_time.perf_counter() - start, 0)
            return []

        if options is None:
            options = RetrievalOptions()

        # System 1 快速路径（``prefer_deep`` 时跳过：调用方已决定直连深检，
        # 避免重复读一次 Digest 缓存）
        if not options.prefer_deep:
            fast_result = self._system1_fast_path(query, owner_key)
            if fast_result is not None:
                results = [
                    RetrievalResult(
                        memory_id="digest",
                        content=fast_result,
                        score=1.0,
                        source="digest_cache",
                    )
                ]
                MetricsCollector.record_retrieve(_time.perf_counter() - start, len(results))
                return results

        # System 2 深度搜索
        results = self._system2_deep_search(query, owner_key, options)
        MetricsCollector.record_retrieve(_time.perf_counter() - start, len(results))
        return results

    # =========================================================
    # 策略路由与对话召回（用户侧 / admin 侧共用）
    # =========================================================

    def route_policy(self, query: str, owner_key: str) -> RetrievalRoute:
        """按意图决定「走哪条路 + 限定哪些视图」（规则分类，不调用 LLM）。

        规则关键词匹配是微秒级，放进对话召回的 1.2s 预算里可忽略；LLM 分类只在
        ``PolicyRouter`` 显式启用时才会发生，此处固定 ``llm_available=False``。
        任何异常退化为「不限视图 + 摘要优先」，与接线前的行为一致（fail-open）。

        Args:
            query: 用户查询文本
            owner_key: 记忆主体键（透传给 select_views；当前视图集合与主体无关）

        Returns:
            RetrievalRoute(intent, views, prefer_deep)
        """
        try:
            from internal.service.memory.policy_router import PolicyRouter

            router = PolicyRouter(llm_available=False)
            intent = router.classify_query(query)
            return RetrievalRoute(
                intent=str(getattr(intent.intent, "value", intent.intent)),
                views=router.select_views(intent, owner_key),
                prefer_deep=router.should_use_system2(intent),
            )
        except Exception:
            logger.warning("route_policy: 意图分类失败，退化为默认路由", exc_info=True)
            return RetrievalRoute(intent="unknown", views=[], prefer_deep=False)

    def retrieve_for_chat(
        self,
        query: str,
        owner_key: str,
        *,
        top_k: int = 5,
        max_chars: int = 600,
        access: Optional[ConfidentialAccess] = None,
        status: Optional[dict] = None,
    ) -> str:
        """对话召回（用户侧 / admin 侧共用入口）：策略路由 → 系统 1/2 → 文本组装。

        顺序由意图决定（``PolicyRouter.should_use_system2``）：
        - ``prefer_deep``：先深检（按意图限定视图），深检为空才回退 Digest 摘要；
        - 否则：先 Digest 摘要（命中即返回），为空才深检。

        任一步异常都向上抛出由调用方 fail-open 兜底（召回绝不阻断对话）。

        Args:
            query: 用户查询文本
            owner_key: 记忆主体键
            top_k: 深检返回上限
            max_chars: 组装文本的字符上限
            access: 机密记忆放行策略（见 ``ConfidentialAccess``）。默认不放行——
                机密条目被移出注入文本，并在 ``status["withheld"]`` 回填结构化条目
                （含 memory_id 与脱敏预览），供上层发确认卡片。
            status: 可选出参 dict；回填 intent/views/prefer_deep/withheld
                （withheld 为 ``WithheldConfidential.to_dict()`` 列表）

        Returns:
            可注入的召回文本；无命中返回空串
        """
        access = access or ConfidentialAccess()
        route = self.route_policy(query, owner_key)
        logger.info(
            "记忆召回路由 intent=%s views=%s prefer_deep=%s",
            route.intent,
            ",".join(route.views) or "-",
            route.prefer_deep,
        )
        if status is not None:
            status.update(
                {
                    "intent": route.intent,
                    "views": list(route.views),
                    "prefer_deep": route.prefer_deep,
                }
            )
        # 深检一律 prefer_deep=True：走到这里时路由已决定「要不要先看摘要」，
        # 由本方法自己控制顺序，不让 retrieve() 内部再插一次摘要快路径。
        options = RetrievalOptions(top_k=top_k, budget_tokens=0, view_names=route.views, prefer_deep=True)

        def _collect(results) -> tuple[list, list]:
            """切分机密并回填 status（withheld 是唯一的结构化出口）。"""
            allowed, withheld = self._split_confidential(results, access)
            if status is not None:
                status["withheld"] = [item.to_dict() for item in withheld]
            return allowed, withheld

        if route.prefer_deep:
            allowed, withheld = _collect(self.retrieve(query, owner_key, options))
            body = self._assemble_text(allowed, max_chars)
            if not body:
                body = (self._system1_fast_path(query, owner_key) or "")[:max_chars]
            return self._with_confidential_hint(body, withheld)

        digest = self._system1_fast_path(query, owner_key)
        if digest:
            if status is not None:
                status["withheld"] = []
            return digest[:max_chars]
        allowed, withheld = _collect(self.retrieve(query, owner_key, options))
        return self._with_confidential_hint(self._assemble_text(allowed, max_chars), withheld)

    @staticmethod
    def _split_confidential(results, access: ConfidentialAccess):
        """按敏感度分级切分召回结果（机密默认不注入，用户确认/授权后才读取）。

        机密 = 身份证号 / 手机号 / 银行卡号 / 密码 / 验证码 / 密钥（见 sensitivity 模块）。
        普通记忆**不受任何影响**——这是"不让用户为日常记忆反复确认"的落点。
        判定复用写入侧同一张正则表（单一事实源），因此无需改四条召回通道的 SQL/Cypher。

        放行判定统一走 ``ConfidentialAccess.allows(memory_id)``：对话中明确确认
        （allow_all）与卡片授权（id 白名单）在此汇合，只有一处判定。
        """
        from internal.service.memory.sensitivity import classify, is_confidential

        allowed: list = []
        withheld: list[WithheldConfidential] = []
        for item in results or []:
            content = str(getattr(item, "content", "") or "")
            memory_id = str(getattr(item, "memory_id", "") or "")
            level, types = classify(content)
            if is_confidential(level) and not access.allows(memory_id):
                withheld.append(
                    WithheldConfidential(
                        memory_id=memory_id,
                        types=tuple(types),
                        label=sensitivity_label(types),
                        preview=redacted_preview(content),
                    )
                )
                continue
            allowed.append(item)
        return allowed, withheld

    @staticmethod
    def _with_confidential_hint(text: str, withheld: list) -> str:
        """机密记忆被暂缓时给模型的提示：先请用户确认，别声称"没有任何记录"。"""
        if not withheld:
            return text

        labels = sensitivity_label([t for item in withheld for t in item.types])
        logger.warning(
            "记忆召回命中 %d 条机密记忆（%s），已按隐私策略暂不注入",
            len(withheld),
            labels,
        )
        hint = (
            f"（系统提示：本次命中 {len(withheld)} 条机密记忆（{labels}），按隐私策略已暂不注入；"
            "系统已向用户发出确认卡片，请提示他点「允许读取」后再问一次；他确认后系统会自动把该记忆注入你的上下文，"
            "你无需调用任何工具即可直接回答。不要声称\"没有任何记录\"。）"
        )
        joiner = chr(10)
        return (text + joiner + hint) if text else hint

    @staticmethod
    def _assemble_text(results, max_chars: int, per_item: int = 600) -> str:
        """把检索结果组装为可注入文本（保留命中原文，逐条截断）。"""
        lines = [
            str(getattr(item, "content", "") or "").strip()[:per_item]
            for item in (results or [])[:5]
        ]
        return "\n".join(line for line in lines if line)[:max_chars]

    @staticmethod
    def _resolve_view_filter(
        view_names: Optional[list[str]],
    ) -> Optional[tuple[set[str], set[str]]]:
        """``view_names`` → (允许的 Neo4j 节点标签集, 允许的 pg memory_type 集)。

        - 空/None → 返回 None，表示**不限视图**（保持接线前行为）；
        - 非空 → 开启限制：未知视图名忽略并告警；解析后标签集为空时
          （全部非法）返回空集，由各分支按「无候选」处理（fail-closed，避免
          静默退化成全量）。
        """
        names = [str(v).strip() for v in (view_names or []) if str(v).strip()]
        if not names:
            return None

        from internal.service.memory.policy_router import PREDEFINED_VIEWS

        labels: set[str] = set()
        pg_types: set[str] = set()
        for name in names:
            profile = PREDEFINED_VIEWS.get(name)
            if profile is None:
                logger.warning("_resolve_view_filter: 未知视图名已忽略: %s", name)
                continue
            labels.update(profile.node_labels)
            pg_types.update(profile.pg_memory_types)
        return labels, pg_types

    @staticmethod
    def _node_in_views(node_labels, view_filter: Optional[tuple[set[str], set[str]]]) -> bool:
        """图扩展节点的视图归属判定（view_filter 为 None 时一律放行）。"""
        if view_filter is None:
            return True
        allowed = view_filter[0]
        if not allowed:
            return False
        return bool(set(node_labels or []) & allowed)

    @staticmethod
    def _resolve_time_cutoff(time_range_days: Optional[int]) -> Optional[datetime]:
        """``time_range_days`` → 时间下界（UTC）；未设置返回 None（不限时间）。"""
        if not time_range_days or int(time_range_days) <= 0:
            return None
        from datetime import timedelta

        return datetime.now(UTC) - timedelta(days=int(time_range_days))

    @staticmethod
    def _view_label_clause(alias: str, view_filter: Optional[tuple[set[str], set[str]]]) -> str:
        """生成 Cypher 标签谓词（如 ``AND (node:`Episode` OR node:`Entity`)``）。

        标签取自 PREDEFINED_VIEWS 的内部常量（非用户输入），仍加反引号按标识符处理；
        view_filter 为 None 时返回空串（不限视图）。
        """
        if view_filter is None:
            return ""
        labels = sorted(view_filter[0])
        if not labels:
            return "AND false"
        parts = " OR ".join(f"{alias}:`{lbl}`" for lbl in labels)
        return f"AND ({parts})"

    # =========================================================
    # System 1: Digest 缓存快速路径
    # =========================================================

    def _system1_fast_path(self, query: str, owner_key: str) -> Optional[str]:
        """检查 Digest 缓存是否足够，足够则直接返回。

        若 digest_manager 可用，则返回 Digest 文本作为快速路径结果。
        对话链路（AssistantAgentService 的早启动句柄 / ``user_memory_recall``）
        与 REST /memory/retrieve 均会优先走本快速路径。

        Args:
            query: 查询文本
            owner_key: 记忆主体键（用户主体为裸 UUID，见 MemoryOwnerKey）

        Returns:
            Digest 文本或 None
        """
        if self._digest_manager is None:
            return None

        try:
            digest_text = self._digest_manager.get_digest(owner_key)
            if (
                digest_text
                and len(digest_text) > 50
                and digest_has_substance(digest_text)
            ):
                return digest_text
            if digest_text:
                logger.info(
                    "_system1_fast_path: Digest 无实质内容，按未命中处理 owner=%s", owner_key
                )
        except Exception:
            logger.warning(
                "_system1_fast_path: Digest 获取失败 owner=%s", owner_key, exc_info=True
            )

        return None

    # =========================================================
    # System 2: 深度搜索
    # =========================================================

    def _system2_deep_search(
        self,
        query: str,
        owner_key: str,
        options: RetrievalOptions,
    ) -> list[RetrievalResult]:
        """TKG 粗召回 + 向量精召回 + 主题召回 + 图扩展 + 混合评分 + 早停。

        步骤:
            ① TKG BM25 粗召回 → all_candidates dict
            ② 向量精召回 → 合并候选（同 id 取最大分，标记 hybrid）
            ③ Community 主题级召回 → 匹配主题并入候选作为图扩展起点
            ④ 图扩展 → 新增节点加入候选
            ⑤ 混合评分 + 时间衰减 → 最终 score
            ⑥ 排序 + 早停截断
        """
        top_k = options.top_k
        recall_k = top_k * 2
        # 视图限制（PolicyRouter.select_views 产出；None = 不限）
        view_filter = self._resolve_view_filter(options.view_names)
        # 时间窗（REST / 调用方显式设置；None = 不限）
        time_cutoff = self._resolve_time_cutoff(options.time_range_days)

        # ① TKG BM25 粗召回
        all_candidates: dict[str, RetrievalResult] = {}
        tkg_results = self._tkg_recall(query, owner_key, recall_k, view_filter, time_cutoff)
        for result in tkg_results:
            all_candidates[result.memory_id] = result

        # ② 向量精召回
        query_embedding = self._embed_query(query)
        if query_embedding:
            vector_results = self._vector_recall(
                query_embedding, owner_key, recall_k, view_filter, time_cutoff
            )
            for result in vector_results:
                mem_id = result.memory_id
                if mem_id in all_candidates:
                    # 合并：取最大分，标记 hybrid
                    existing = all_candidates[mem_id]
                    max_score = max(existing.score, result.score)
                    merged = RetrievalResult(
                        memory_id=mem_id,
                        content=result.content or existing.content,
                        score=max_score,
                        source="hybrid",
                        timestamp=result.timestamp,
                        metadata={**existing.metadata, **result.metadata},
                    )
                    merged.score_breakdown = RetrievalScore(
                        semantic=result.score,
                        keyword=existing.score,
                        total=max_score,
                    )
                    all_candidates[mem_id] = merged
                else:
                    all_candidates[mem_id] = result

        # ③ Community 主题级召回（P5 新皮层）：命中主题时一并纳入候选，
        #     后续图扩展从主题沿 TOPIC_OF/MEMBER_OF 拉起其成员作为间接证据。
        community_results = self._community_recall(
            query, owner_key, recall_k, view_filter, time_cutoff
        )
        for result in community_results:
            if result.memory_id not in all_candidates:
                all_candidates[result.memory_id] = result

        # ④ 图扩展
        if all_candidates:
            start_ids = list(all_candidates.keys())[:5]
            spread_results = self._graph_spread(start_ids, top_k=options.top_k, owner_key=owner_key)
            for node_id, activation in spread_results:
                if node_id not in all_candidates:
                    # 获取节点数据（带主体谓词，防跨主体取到他人节点）
                    node_data = self._get_node_data(node_id, owner_key=owner_key)
                    if not node_data:
                        continue
                    # 视图限制与时间窗同样作用于扩展节点：不允许有分支绕过；
                    # 节点无 created_at 时 `_get_node_data` 回落为当前时间（宽容放行，不静默丢数据）
                    if not self._node_in_views(node_data.get("labels"), view_filter):
                        continue
                    if time_cutoff is not None and node_data.get("timestamp") and node_data["timestamp"] < time_cutoff:
                        continue
                    all_candidates[node_id] = RetrievalResult(
                        memory_id=node_id,
                        content=node_data.get("content", ""),
                        score=activation * 0.8,
                        source="graph_spread",
                        timestamp=node_data.get("timestamp", datetime.now(UTC)),
                    )

        if not all_candidates:
            return []

        # ⑤ 混合评分 + 时间衰减
        query_text = query
        scored: list[RetrievalResult] = []
        for result in all_candidates.values():
            hybrid = self._hybrid_score(result, query_embedding, query_text)
            decay = self._time_decay(result.timestamp)
            final_score = hybrid * decay

            scored_result = RetrievalResult(
                memory_id=result.memory_id,
                content=result.content,
                score=final_score,
                source=result.source,
                timestamp=result.timestamp,
                metadata=result.metadata,
                evidence_chain=result.evidence_chain,
            )
            scored_result.score_breakdown = RetrievalScore(
                semantic=result.score_breakdown.semantic,
                keyword=result.score_breakdown.keyword,
                graph=result.score_breakdown.graph,
                time_decay=decay,
                total=final_score,
            )
            scored.append(scored_result)

        # ⑥ 排序 + 早停截断
        scored.sort(key=lambda x: x.score, reverse=True)
        scored = self._apply_early_stop(scored, top_k)

        return scored[:top_k]

    # =========================================================
    # 召回通道
    # =========================================================

    def _tkg_recall(
        self,
        query: str,
        owner_key: str,
        top_k: int,
        view_filter: Optional[tuple[set[str], set[str]]] = None,
        time_cutoff: Optional[datetime] = None,
    ) -> list[RetrievalResult]:
        """Neo4j 全文索引 BM25 粗召回。

        使用 ``db.index.fulltext.queryNodes("memoryFullText", $query)`` 查询，
        仅返回 HOT/WARM 层节点；``view_filter`` 非空时叠加节点标签谓词
        （Episode / Entity / SemanticMemory 等同挂 ``:MemoryNode`` 标签，
        按视图收窄时只保留该视图声明的标签）；``time_cutoff`` 非空时按
        ``created_at`` 收窄时间窗（无 created_at 的节点宽容放行）。

        Args:
            query: 查询文本
            owner_key: 记忆主体键
            top_k: 返回数量上限
            view_filter: ``(允许标签集, 允许 pg 类型集)``；None = 不限视图
            time_cutoff: 时间下界（UTC）；None = 不限时间

        Returns:
            RetrievalResult 列表，source="bm25"
        """
        driver = self._driver or self._get_driver()
        if driver is None:
            logger.warning("_tkg_recall: Neo4j 不可用")
            return []
        if view_filter is not None and not view_filter[0]:
            return []  # 视图限制下无允许标签（全部非法视图名）→ fail-closed

        try:
            owner = MemoryOwnerKey.parse(owner_key)
            label_clause = self._view_label_clause("node", view_filter)
            time_clause = ""
            time_binds: dict = {}
            if time_cutoff is not None:
                time_clause = "AND (node.created_at IS NULL OR node.created_at >= $cutoff)"
                time_binds["cutoff"] = time_cutoff
            cypher = f"""
            CALL db.index.fulltext.queryNodes("memoryFullText", $query)
            YIELD node, score
            WHERE {owner.neo4j_filter_condition("node")}
              AND (node.storage_tier IS NULL OR node.storage_tier IN ['hot', 'warm'])
              AND node.is_active <> false
              AND node.t_invalidated_at IS NULL
              AND (node.status IS NULL OR NOT (node.status IN ['superseded', 'deprecated']))
              {label_clause}
              {time_clause}
            WITH node, score
            ORDER BY score DESC
            LIMIT $top_k
            RETURN node.node_id AS node_id,
                   node.content AS content,
                   node.summary AS summary,
                   node.created_at AS created_at,
                   score
            """
            with driver.session() as session:
                result = session.run(
                    cypher,
                    {"query": query, "top_k": top_k, **owner.neo4j_props(), **time_binds},
                )
                records = list(result)

            results: list[RetrievalResult] = []
            for record in records:
                node_id = str(record.get("node_id", ""))
                content = record.get("content") or record.get("summary") or ""
                bm25_score = float(record.get("score", 0.0))
                created_at = record.get("created_at") or datetime.now(UTC)

                rr = RetrievalResult(
                    memory_id=node_id,
                    content=content,
                    score=bm25_score,
                    source="bm25",
                    timestamp=created_at if isinstance(created_at, datetime) else datetime.now(UTC),
                )
                rr.score_breakdown = RetrievalScore(keyword=bm25_score, total=bm25_score)
                results.append(rr)

            return results
        except MemoryOwnerKeyError:
            logger.warning(
                "_tkg_recall: 非法主体键，跳过召回 owner=%r", owner_key
            )
            return []
        except Exception:
            logger.warning("_tkg_recall: 全文检索失败", exc_info=True)
            return []

    def _vector_recall(
        self,
        query_embedding: list[float],
        owner_key: str,
        top_k: int,
        view_filter: Optional[tuple[set[str], set[str]]] = None,
        time_cutoff: Optional[datetime] = None,
    ) -> list[RetrievalResult]:
        """pgvector 向量检索精召回（按维度分表，HNSW 索引 + ``<=>`` 余弦距离）。

        从 user_memory_embedding_{dim} 表检索，JOIN user_memory 表获取元数据；
        ``view_filter`` 非空时叠加 ``user_memory.memory_type`` 过滤（视图声明的
        ``pg_memory_types``）；该集合为空（如 skills / knowledge 只存图内）时
        本分支直接返回空，而不是退化成全量。``time_cutoff`` 非空时按
        ``user_memory.created_at`` 收窄时间窗。

        Args:
            query_embedding: 查询向量
            owner_key: 记忆主体键（用户主体为裸 UUID，见 MemoryOwnerKey）
            top_k: 返回数量上限
            view_filter: ``(允许标签集, 允许 pg 类型集)``；None = 不限视图
            time_cutoff: 时间下界（UTC）；None = 不限时间

        Returns:
            RetrievalResult 列表，source="semantic"
        """
        if not query_embedding:
            return []

        pg_types: list[str] = []
        type_clause = ""
        type_binds: dict = {}
        if view_filter is not None:
            pg_types = sorted(view_filter[1])
            if not pg_types:
                return []  # 该视图没有向量行（skills / knowledge / themes）
            placeholders = ", ".join(f":mt_{i}" for i in range(len(pg_types)))
            type_clause = f" AND um.memory_type IN ({placeholders})"
            type_binds = {f"mt_{i}": t for i, t in enumerate(pg_types)}

        time_clause = ""
        time_binds: dict = {}
        if time_cutoff is not None:
            time_clause = " AND um.created_at >= :cutoff"
            time_binds["cutoff"] = time_cutoff

        db = self._db or self._get_db()
        if db is None:
            logger.warning("_vector_recall: 数据库不可用")
            return []

        try:
            from internal.service.embedding_table_router import EmbeddingTableRouter
            from sqlalchemy import text

            # 解析系统默认维度并确保维度表已创建
            router = EmbeddingTableRouter.get_instance()
            dimension = router.resolve_system_default_dimension()
            if not router.ensure_tables_for_dimension(dimension):
                logger.warning("_vector_recall: 维度 %d 表创建失败", dimension)
                return []
            table_name = router.get_user_memory_table_name(dimension)

            owner = MemoryOwnerKey.parse(owner_key)
            owner_where, owner_bind = owner.pg_sql_predicate("v")

            # 从维度分表检索 + JOIN user_memory 获取元数据
            # 绑定参数需 CAST 为 vector（同 knowledge_vector_service），
            # 否则 psycopg2 将 list 推断为 numeric[] 导致检索失败
            sql = text(f"""
                SELECT um.id AS memory_id,
                       um.content,
                       um.embedding_node_id,
                       um.created_at,
                       1 - (v.embedding <=> CAST(:embedding AS vector)) AS score
                FROM {table_name} v
                JOIN user_memory um ON v.memory_id = um.id
                WHERE {owner_where}
                  AND um.status = 'active'
                  {type_clause}
                  {time_clause}
                ORDER BY v.embedding <=> CAST(:embedding AS vector)
                LIMIT :top_k
            """)

            rows = db.session.execute(sql, {
                **owner_bind,
                **type_binds,
                **time_binds,
                "embedding": query_embedding,
                "top_k": top_k,
            }).all()

            results: list[RetrievalResult] = []
            for row in rows:
                mem_id = str(row.memory_id)
                if row.embedding_node_id:
                    mem_id = row.embedding_node_id

                content = row.content or ""
                semantic_score = float(row.score) if row.score is not None else 0.0

                rr = RetrievalResult(
                    memory_id=mem_id,
                    content=content,
                    score=semantic_score,
                    source="semantic",
                    timestamp=row.created_at or datetime.now(UTC),
                )
                rr.score_breakdown = RetrievalScore(semantic=semantic_score, total=semantic_score)
                results.append(rr)

            return results
        except MemoryOwnerKeyError:
            logger.warning(
                "_vector_recall: 非法主体键，跳过召回 owner=%r", owner_key
            )
            return []
        except Exception:
            logger.warning("_vector_recall: 向量检索失败", exc_info=True)
            return []

    def _graph_spread(
        self,
        start_ids: list[str],
        top_k: int = 20,
        owner_key: str = "",
    ) -> list[tuple[str, float]]:
        """调用 SpreadActivation 进行图扩展。

        Args:
            start_ids: 起始节点 ID 列表
            top_k: 返回最大数量
            owner_key: 记忆主体键（用户主体为裸 UUID）；透传给 SpreadActivation
                做主体约束（ADMIN-P3c-4 缺口一）。

        Returns:
            ``[(node_id, activation), ...]`` 列表
        """
        if not start_ids:
            return []

        try:
            spread = SpreadActivation(
                neo4j_driver=self._driver or self._get_driver(),
                config=SpreadConfig(),
            )
            return spread.activate(start_ids, top_k=top_k, owner_key=owner_key)
        except Exception:
            logger.warning("_graph_spread: 图扩展失败", exc_info=True)
            return []

    def _community_recall(
        self,
        query: str,
        owner_key: str,
        top_k: int = 10,
        view_filter: Optional[tuple[set[str], set[str]]] = None,
        time_cutoff: Optional[datetime] = None,
    ) -> list[RetrievalResult]:
        """Community 主题级召回（P5 新皮层枢纽）。

        用 communityFullText 全文索引在 Community 节点上做主题级粗召回，
        命中主题时把主题本身（source="community_theme"）返回为候选；
        其成员（语义/实体）由后续 SpreadActivation 沿 TOPIC_OF/MEMBER_OF
        边拉取，形成「主题→成员」的间接证据链。

        ``view_filter`` 非空时：只有视图集合包含 ``themes``（声明 Community 标签）
        才执行本分支；主题节点的成员仍由（同样受视图约束的）图扩展拉起。

        Args:
            query: 查询文本
            owner_key: 记忆主体键（用户主体为裸 UUID，见 MemoryOwnerKey）
            top_k: 返回数量上限
            view_filter: ``(允许标签集, 允许 pg 类型集)``；None = 不限视图
            time_cutoff: 时间下界（UTC）；None = 不限时间（无 created_at 的节点宽容放行）

        Returns:
            RetrievalResult 列表，source="community_theme"
        """
        if view_filter is not None and "Community" not in view_filter[0]:
            return []  # 视图不含 themes → 主题召回不参与

        driver = self._driver or self._get_driver()
        if driver is None:
            return []

        try:
            owner = MemoryOwnerKey.parse(owner_key)
            time_clause = ""
            time_binds: dict = {}
            if time_cutoff is not None:
                time_clause = "AND (node.created_at IS NULL OR node.created_at >= $cutoff)"
                time_binds["cutoff"] = time_cutoff
            cypher = f"""
            CALL db.index.fulltext.queryNodes("communityFullText", $query)
            YIELD node, score
            WHERE {owner.neo4j_filter_condition("node")}
              AND node.is_active <> false
              AND (node.status IS NULL OR node.status IN ['candidate', 'active'])
              {time_clause}
            WITH node, score
            ORDER BY score DESC
            LIMIT $top_k
            RETURN node.node_id AS node_id,
                   node.title AS title,
                   node.summary AS summary,
                   node.created_at AS created_at,
                   score
            """
            with driver.session() as session:
                result = session.run(
                    cypher,
                    {"query": query, "top_k": top_k, **owner.neo4j_props(), **time_binds},
                )
                records = list(result)

            results: list[RetrievalResult] = []
            for record in records:
                node_id = str(record.get("node_id", ""))
                title = record.get("title") or ""
                summary = record.get("summary") or ""
                content = f"{title}: {summary}" if title else (summary or "")
                if not content:
                    continue
                score = float(record.get("score", 0.0))
                created_at = record.get("created_at") or datetime.now(UTC)
                if not isinstance(created_at, datetime):
                    created_at = datetime.now(UTC)

                rr = RetrievalResult(
                    memory_id=node_id,
                    content=content,
                    score=score * 0.9,
                    source="community_theme",
                    timestamp=created_at,
                    metadata={"theme_title": title},
                )
                rr.score_breakdown = RetrievalScore(
                    keyword=score, graph=score * 0.1, total=score * 0.9
                )
                results.append(rr)

            return results
        except MemoryOwnerKeyError:
            logger.warning(
                "_community_recall: 非法主体键，跳过召回 owner=%r", owner_key
            )
            return []
        except Exception:
            logger.warning("_community_recall: Community 主题召回失败", exc_info=True)
            return []

    # =========================================================
    # 评分与早停
    # =========================================================

    def _hybrid_score(
        self,
        result: RetrievalResult,
        query_embed: Optional[list[float]],
        query_text: str,
    ) -> float:
        """混合评分：w_cosine * semantic + w_bm25 * keyword + w_graph * graph。

        根据 ``result.source`` 分配通道分数，缺失通道权重重分配到其余通道。

        Args:
            result: 检索结果
            query_embed: 查询向量（当前未直接使用，预留扩展）
            query_text: 查询文本（当前未直接使用，预留扩展）

        Returns:
            归一化到 [0, 1] 的混合分数
        """
        w_cosine = self._config.w_cosine
        w_bm25 = self._config.w_bm25
        w_graph = self._config.w_graph

        source = result.source or ""
        breakdown = result.score_breakdown

        # 根据来源分配通道分数
        if source == "hybrid":
            semantic = breakdown.semantic or result.score
            keyword = breakdown.keyword or result.score
            graph = breakdown.graph or 0.0
        elif source == "semantic":
            semantic = result.score
            keyword = 0.0
            graph = 0.0
        elif source == "bm25":
            semantic = 0.0
            keyword = result.score
            graph = 0.0
        elif source in ("graph_spread", "graph"):
            semantic = 0.0
            keyword = 0.0
            graph = result.score
        elif source == "community_theme":
            semantic = 0.0
            keyword = breakdown.keyword or result.score
            graph = breakdown.graph or 0.0
        else:
            semantic = breakdown.semantic or 0.0
            keyword = breakdown.keyword or 0.0
            graph = breakdown.graph or 0.0

        # 缺失通道权重重分配
        has_semantic = semantic > 0
        has_keyword = keyword > 0
        has_graph = graph > 0

        active_weights = []
        active_scores = []
        if has_semantic:
            active_weights.append(w_cosine)
            active_scores.append(semantic)
        if has_keyword:
            active_weights.append(w_bm25)
            active_scores.append(keyword)
        if has_graph:
            active_weights.append(w_graph)
            active_scores.append(graph)

        if not active_weights:
            return 0.0

        total_weight = sum(active_weights)
        if total_weight <= 0:
            return 0.0

        # 归一化权重并计算加权平均
        weighted_sum = sum(w * s for w, s in zip(active_weights, active_scores))
        score = weighted_sum / total_weight

        return max(0.0, min(1.0, score))

    def _time_decay(self, timestamp: datetime, now: Optional[datetime] = None) -> float:
        """时间衰减：exp(-ln2 * Δt / half_life)，Δt 以小时计。

        保留最低 0.01 防完全消失。

        Args:
            timestamp: 记忆时间戳
            now: 当前时间，None 时使用 UTC 当前时刻

        Returns:
            衰减因子 [0.01, 1.0]
        """
        if now is None:
            now = datetime.now(timezone.utc)

        ts = timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        delta_hours = (now - ts).total_seconds() / 3600.0
        delta_hours = max(delta_hours, 0.0)

        half_life = self._config.time_decay_half_life_hours
        if half_life <= 0:
            return 1.0

        decay = math.exp(-math.log(2) * delta_hours / half_life)
        return max(0.01, min(1.0, decay))

    def _apply_early_stop(
        self,
        scored: list[RetrievalResult],
        top_k: int,
    ) -> list[RetrievalResult]:
        """top_k + score_gap 判断，触发早停则截断。

        Args:
            scored: 已排序的检索结果（按 score 降序）
            top_k: 返回数量上限

        Returns:
            截断后的结果列表
        """
        if len(scored) <= top_k:
            return scored

        # 检查 cutoff 处与前一处的分数差
        cutoff = self._config.early_stop_top_k
        score_gap = self._config.early_stop_score_gap

        if cutoff >= len(scored):
            return scored

        score_at_cutoff = scored[cutoff].score
        score_before = scored[cutoff - 1].score

        if score_before - score_at_cutoff > score_gap:
            # 分差超过阈值，截断
            return scored[:cutoff]

        return scored

    # =========================================================
    # 辅助方法
    # =========================================================

    def _embed_query(self, query: str) -> Optional[list[float]]:
        """将查询文本转为向量。

        通过 EmbeddingsService.embeddings.embed_query() 获取向量。
        """
        embeddings_service = self._embeddings_service or self._get_embeddings_service()
        if embeddings_service is None:
            return None

        try:
            return embeddings_service.embeddings.embed_query(query)
        except Exception:
            logger.warning("_embed_query: 查询向量化失败", exc_info=True)
            return None

    def _get_node_data(self, node_id: str, owner_key: str = "") -> Optional[dict]:
        """从 Neo4j 获取节点数据（content、timestamp 等）。

        ADMIN-P3c-4（缺口一）：传 ``owner_key`` 时按主体谓词约束节点归属，
        防止跨主体取到他人节点；空串时不加谓词（历史行为等价）。
        """
        driver = self._driver or self._get_driver()
        if driver is None:
            return None

        try:
            owner_predicate = "true"
            owner_binds: dict = {}
            if owner_key:
                from internal.entity.memory_owner_entity import MemoryOwnerKey

                owner = MemoryOwnerKey.parse(owner_key)
                owner_predicate = owner.neo4j_filter_condition("n")
                owner_binds = dict(owner.neo4j_props())
            cypher = f"""
            MATCH (n {{node_id: $node_id}})
            WHERE {owner_predicate}
            RETURN n.content AS content,
                   n.summary AS summary,
                   n.created_at AS created_at,
                   n.user_id AS user_id,
                   labels(n) AS labels
            """
            with driver.session() as session:
                result = session.run(cypher, {"node_id": node_id, **owner_binds})
                record = result.single()

            if record is None:
                return None

            content = record.get("content") or record.get("summary") or ""
            created_at = record.get("created_at") or datetime.now(UTC)
            if not isinstance(created_at, datetime):
                created_at = datetime.now(UTC)

            return {
                "content": content,
                "timestamp": created_at,
                "labels": list(record.get("labels") or []),
            }
        except Exception:
            logger.warning("_get_node_data: 获取节点数据失败 node_id=%s", node_id, exc_info=True)
            return None

    def _get_driver(self):
        """获取 Neo4j 驱动，不可用时返回 None。"""
        try:
            from internal.context import current_app

            driver = current_app.extensions.get("neo4j")
            if driver is not None:
                return driver
        except RuntimeError:
            pass
        try:
            from internal.extension.neo4j_extension import get_driver

            return get_driver()
        except Exception:
            logger.warning("_get_driver: 获取 Neo4j 驱动失败", exc_info=True)
            return None

    def _get_db(self):
        """获取 SQLAlchemy 实例，不可用时返回 None。"""
        try:
            from internal.context import current_app

            db = current_app.extensions.get("database")
            if db is not None:
                return db
        except RuntimeError:
            pass
        try:
            from internal.extension.database_extension import db

            return db
        except Exception:
            logger.warning("_get_db: 获取数据库失败", exc_info=True)
            return None

    def _get_embeddings_service(self):
        """获取 EmbeddingsService 实例，不可用时返回 None。"""
        try:
            from internal.context import current_app

            injector = getattr(current_app, "injector", None)
            if injector is not None:
                from internal.service.embeddings_service import EmbeddingsService

                return injector.get(EmbeddingsService)
        except Exception:
            logger.warning("_get_embeddings_service: 获取失败", exc_info=True)
        return None
