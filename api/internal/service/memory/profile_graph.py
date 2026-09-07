"""Profile 画像落库模块（ProfileGraphService）。

将用户显式陈述记忆从实时扫描 Episode 升级为持久化画像节点：

    (:User {id, user_id, name, last_active_at, created_at, is_active})
    (:Trait {key, user_id})            — habit / identity / capability 类画像
    (:Preference {key, user_id})       — preference / aversion / goal 类画像
    (u:User)-[:HAS_TRAIT]->(t:Trait)
    (u:User)-[:HAS_PREFERENCE]->(p:Preference)
    (u:User)-[:HAS_EXPLICIT_MEMORY]->(e:Episode)

节点与边不使用 :MemoryNode / storage_tier，避开 memorynode_id_unique 约束。

User 节点 id 唯一（MERGE on id），供 GDPR / 治理按 ``u.id`` 定位删除。

分组语义与 Digest 渲染保持一致:
    preference+positive / meta_instruction → Preference 偏好
    preference+negative / aversion          → Preference 厌恶（polarity=negative）
    habit / identity / capability           → Trait
    goal                                   → Preference（polarity=goal）

提升阈值由 settings.consolidation.profile_promote_min_episodes 控制（默认 2）:
    同一 key 引用的活跃 Episode 数达到阈值 → 持久画像；否则作为近期画像照常写入。

设计参考:
    docs/prd/memory-system/03-consolidation-skill-policy-api.md（PolicyRouter profile 视图）
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from internal.config.memory_settings import settings

logger = logging.getLogger(__name__)

_GROUP_CN = ("偏好", "厌恶", "习惯", "身份", "目标", "能力")
_EPISODE_INVALID_STATUSES = ("superseded", "deprecated")


def _slug(text: str, max_len: int = 64) -> str:
    """确定性 slug：去空白/标点/emoji，小写，截断到 max_len。"""
    cleaned = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    return cleaned.lower()[:max_len]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ProfileGraphService:
    """用户画像落库服务。

    Neo4j 驱动获取优先级：构造参数 neo4j_driver →
    current_app.extensions['neo4j'] → neo4j_extension.get_driver()。
    """

    def __init__(self, neo4j_driver=None) -> None:
        self._driver = neo4j_driver

    # =========================================================
    # 驱动
    # =========================================================

    def _get_driver(self):
        if self._driver is not None:
            return self._driver
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
            logger.warning("ProfileGraphService: 获取 Neo4j 驱动失败", exc_info=True)
            return None

    # =========================================================
    # 公开方法
    # =========================================================

    def ensure_user(self, user_id: str) -> None:
        """MERGE (:User {id})，更新 last_active_at/name。"""
        driver = self._get_driver()
        if driver is None:
            return
        try:
            with driver.session() as session:
                session.run(
                    """
                    MERGE (u:User {id: $user_id})
                    SET u.user_id = $user_id,
                        u.name = COALESCE(u.name, ''),
                        u.last_active_at = $now,
                        u.created_at = COALESCE(u.created_at, $now),
                        u.is_active = COALESCE(u.is_active, true)
                    """,
                    user_id=user_id,
                    now=_now_iso(),
                ).consume()
        except Exception:
            logger.warning("ensure_user: 失败 user=%s", user_id, exc_info=True)

    def sync_from_explicit_episodes(self, user_id: str) -> dict:
        """从显式 Episode 同步 Trait/Preference 画像节点。

        Returns:
            {"user": bool, "traits": int, "preferences": int, "linked": int, "errors": [..]}
        """
        result: dict = {
            "user": False,
            "traits": 0,
            "preferences": 0,
            "linked": 0,
            "errors": [],
        }
        driver = self._get_driver()
        if driver is None:
            return result

        self.ensure_user(user_id)
        result["user"] = True

        try:
            with driver.session() as session:
                fetched = session.run(
                    """
                    MATCH (e:Episode {user_id: $user_id})
                    WHERE e.explicit_category IS NOT NULL
                      AND e.t_invalidated_at IS NULL
                      AND (e.status IS NULL OR NOT (e.status IN $invalid_statuses))
                      AND e.is_active <> false
                    WITH e
                    ORDER BY e.created_at DESC
                    RETURN e.explicit_category AS category,
                           e.explicit_polarity AS polarity,
                           e.content AS content,
                           e.summary AS summary,
                           e.node_id AS node_id,
                           e.id AS id
                    """,
                    user_id=user_id,
                    invalid_statuses=list(_EPISODE_INVALID_STATUSES),
                )
                records = [record for record in fetched]
        except Exception:
            logger.warning(
                "sync_from_explicit_episodes: 查询失败 user=%s", user_id, exc_info=True
            )
            result["errors"].append("episode_query_failed")
            return result

        buckets: dict[str, dict] = {}

        for record in records:
            category = record.get("category") or ""
            polarity = record.get("polarity") or ""
            content = (record.get("content") or "").strip()
            summary = (record.get("summary") or content or "").strip()
            episode_id = str(record.get("node_id") or record.get("id") or "")

            if not content or not category:
                continue

            node_type, node_key, label, group, node_polarity = self._map_category(
                category, polarity, content
            )
            if node_type is None:
                continue

            bucket_key = (node_type, node_key)
            bucket = buckets.setdefault(
                bucket_key,
                {
                    "type": node_type,
                    "key": node_key,
                    "label": label,
                    "category": group,
                    "polarity": node_polarity,
                    "value": content,
                    "sources": [],
                    "episode_count": 0,
                },
            )
            if not bucket["sources"]:
                bucket["value"] = content
            if episode_id and episode_id not in bucket["sources"]:
                bucket["sources"].append(episode_id)
                bucket["episode_count"] += 1

        errors = []
        traits = 0
        preferences = 0
        linked = 0
        with driver.session() as session:
            for (node_type, node_key), bucket in buckets.items():
                try:
                    session.run(
                        self._upsert_cypher(node_type),
                        self._upsert_params(user_id, bucket),
                    ).consume()
                    if node_type == "Trait":
                        traits += 1
                    else:
                        preferences += 1
                except Exception:
                    logger.warning(
                        "sync_from_explicit_episodes: upsert 失败 user=%s key=%s",
                        user_id,
                        node_key,
                        exc_info=True,
                    )
                    errors.append(f"upsert:{node_key}")
                    continue

                try:
                    session.run(
                        """
                        MATCH (u:User {id: $user_id})
                        MATCH (e:Episode)
                        WHERE e.user_id = $user_id
                          AND (e.node_id IN $source_ids OR e.id IN $source_ids)
                        WITH u, e
                        MERGE (u)-[:HAS_EXPLICIT_MEMORY]->(e)
                        """,
                        user_id=user_id,
                        source_ids=bucket["sources"],
                    ).consume()
                    linked += 1
                except Exception:
                    logger.warning(
                        "sync_from_explicit_episodes: HAS_EXPLICIT_MEMORY 失败 user=%s key=%s",
                        user_id,
                        node_key,
                        exc_info=True,
                    )
                    errors.append(f"link:{node_key}")

        result["traits"] = traits
        result["preferences"] = preferences
        result["linked"] = linked
        result["errors"] = errors
        return result

    def get_profile_text(self, user_id: str) -> str:
        """从 Trait/Preference 节点渲染六组画像文本（与 Digest 输出兼容）。

        无数据或 Neo4j 不可用时返回空字符串，让 digest 回退到旧路径。
        """
        driver = self._get_driver()
        if driver is None:
            return ""

        try:
            with driver.session() as session:
                rows = list(
                    session.run(
                        """
                        MATCH (n)
                        WHERE n.user_id = $user_id
                          AND (n:Trait OR n:Preference)
                          AND n.is_active <> false
                        RETURN n.category AS category,
                               n.polarity AS polarity,
                               n.label AS label,
                               n.value AS value,
                               n.key AS key
                        """,
                        user_id=user_id,
                    )
                )
        except Exception:
            logger.warning(
                "get_profile_text: 查询失败 user=%s", user_id, exc_info=True
            )
            return ""

        groups: dict[str, list[str]] = {name: [] for name in _GROUP_CN}
        for row in rows:
            category = row.get("category") or ""
            text = row.get("label") or row.get("value") or ""
            if not text:
                continue
            group = self._group_of(category, row.get("polarity") or "")
            if group is not None:
                groups[group].append(text)

        lines = [
            f"【{name}】{'、'.join(items)}"
            for name, items in groups.items()
            if items
        ]
        return "\n".join(lines)

    def mark_user_inactive(self, user_id: str) -> None:
        """用户下线：User 置 is_active=false，并级联 Trait/Preference 置 is_active=false。"""
        driver = self._get_driver()
        if driver is None:
            return
        try:
            with driver.session() as session:
                session.run(
                    """
                    MATCH (u:User {id: $user_id})
                    SET u.is_active = false
                    WITH u
                    OPTIONAL MATCH (u)-[:HAS_TRAIT|HAS_PREFERENCE]->(n)
                    SET n.is_active = false
                    """,
                    user_id=user_id,
                ).consume()
        except Exception:
            logger.warning(
                "mark_user_inactive: 失败 user=%s", user_id, exc_info=True
            )

    # =========================================================
    # 内部辅助
    # =========================================================

    def _map_category(self, category: str, polarity: str, content: str):
        """把 Episode 的 explicit_category/polarity 映射为 Trait/Preference 描述。"""
        cleaned = _slug(content)
        if category == "preference" and polarity == "negative":
            return "Preference", f"aversion_{cleaned}", content, "厌恶", "negative"
        if category == "aversion":
            return "Preference", f"aversion_{cleaned}", content, "厌恶", "negative"
        if category == "preference":
            return "Preference", f"pref_{cleaned}", content, "偏好", "positive"
        if category == "habit":
            return "Trait", f"habit_{cleaned}", content, "习惯", "neutral"
        if category == "identity":
            return "Trait", f"identity_{cleaned}", content, "身份", "neutral"
        if category == "capability":
            return "Trait", f"capability_{cleaned}", content, "能力", "neutral"
        if category == "goal":
            return "Preference", f"goal_{cleaned}", content, "目标", "goal"
        if category == "meta_instruction":
            return "Preference", f"pref_{cleaned}", content, "偏好", "positive"
        return None, None, None, None, None

    def _upsert_cypher(self, node_type: str) -> str:
        rel = "HAS_TRAIT" if node_type == "Trait" else "HAS_PREFERENCE"
        return f"""
        MERGE (n:{node_type} {{key: $key, user_id: $user_id}})
        SET n.label = $label,
            n.category = $category,
            n.polarity = $polarity,
            n.value = $value,
            n.sources = $sources,
            n.episode_count = $episode_count,
            n.last_updated_at = $now,
            n.created_at = COALESCE(n.created_at, $now),
            n.is_active = COALESCE(n.is_active, true),
            n.node_id = COALESCE(n.node_id, $node_id)
        WITH n
        MATCH (u:User {{id: $user_id}})
        MERGE (u)-[:{rel}]->(n)
        """

    def _upsert_params(self, user_id: str, bucket: dict) -> dict:
        now = _now_iso()
        return {
            "user_id": user_id,
            "key": bucket["key"],
            "label": bucket["label"],
            "category": bucket["category"],
            "polarity": bucket["polarity"],
            "value": bucket["value"],
            "sources": list(bucket["sources"])[:20],
            "episode_count": bucket["episode_count"],
            "now": now,
            "node_id": f"{bucket['type']}:{user_id}:{bucket['key']}",
        }

    def _group_of(self, category: str, polarity: str):
        if category in _GROUP_CN:
            return category
        if category == "preference":
            return "厌恶" if polarity == "negative" else "偏好"
        if category == "aversion":
            return "厌恶"
        if category == "habit":
            return "习惯"
        if category == "identity":
            return "身份"
        if category == "goal":
            return "目标"
        if category == "capability":
            return "能力"
        if category == "meta_instruction":
            return "偏好"
        return None
