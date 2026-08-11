"""冷存储管理器（ColdStorageManager）。

管理 L3 冷记忆的归档与 Key 重建。提供三种冷存储激活策略：
全量遍历恢复、从值重建 Key、统计挖掘潜在模式。

存储后端适配:
    通过 DI 注入的 ``ObjectStoragePort`` 实例统一访问存储后端，
    由 ``STORAGE_BACKEND`` 环境变量分发到 local/cos/oss 等后端。
    上传走 ``upload_bytes_without_record``，下载通过 ``get_file_url`` 获取
    可访问 URL 后以 HTTP GET 拉取。统一端口暂不支持列举操作。

降级策略:
    - 存储服务不可用时 archive/read_archive 返回 None，list 返回空列表
    - Neo4j 不可用时 _restore_to_neo4j 跳过
    - gzip/JSON 异常时跳过单条，不影响整体

设计参考:
    docs/prd/memory-system/02-storage-and-retrieval.md §5.3
    docs/prd/memory-system/execution/03-track-b-storage-retrieval.md B2
"""

from __future__ import annotations

import gzip
import logging
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Optional

from internal.config.memory_settings import settings
from internal.model.memory_models import ColdStorageEntry, RebuildResult

logger = logging.getLogger(__name__)


# 英文停用词表（简化版）
_STOP_WORDS = frozenset(
    """
    a an the and or but in on at to for of with by from is are was were be been being
    have has had do does did will would could should may might must can this that these
    those i you he she it we they me him her us them my your his its our their what
    which who whom whose when where why how all each every both few more most other some
    such no nor not only own same so than too very s t can just don should now
    """.split()
)


class ColdStorageManager:
    """冷存储管理器。

    不使用 ``@inject``：无注入依赖，配置从 ``settings.cold_storage`` 读取，
    存储服务通过 DI 注入的 ``ObjectStoragePort`` 实例获取（分发到当前
    ``STORAGE_BACKEND`` 配置的后端），Neo4j 驱动由构造函数传入或运行时获取。
    """

    def __init__(
        self,
        cos_client=None,
        bucket: Optional[str] = None,
        config=None,
        neo4j_driver=None,
    ) -> None:
        """初始化冷存储管理器。

        Args:
            cos_client: （已废弃）保留参数向后兼容，不再使用
            bucket: （已废弃）保留参数向后兼容，不再使用
            config: ColdStorageConfig 实例，None 时使用 settings.cold_storage
            neo4j_driver: Neo4j 驱动（可选，用于回热时回写）
        """
        self._config = config or settings.cold_storage
        self._driver = neo4j_driver

    # =========================================================
    # 归档与读取
    # =========================================================

    def archive(self, entry: ColdStorageEntry) -> Optional[str]:
        """将冷记忆条目写入冷存储归档（gzip 压缩 JSON）。

        Args:
            entry: 冷存储条目

        Returns:
            归档对象的访问 URL，失败时返回 None
        """
        storage = self._get_storage_service()
        if storage is None:
            logger.warning("archive: 存储服务不可用，跳过归档")
            return None

        # 构造对象键 {prefix}{user_id}/{year}/{month}/{memory_id}.json.gz
        now = entry.archived_at or datetime.now(UTC)
        s3_key = (
            f"{self._config.s3_prefix}{entry.user_id}/"
            f"{now.year}/{now.month:02d}/{entry.node_id}.json.gz"
        )

        try:
            payload = entry.model_dump_json().encode("utf-8")
            compressed = gzip.compress(payload)
            url = storage.upload_bytes_without_record(
                filename=s3_key.rsplit("/", 1)[-1] if "/" in s3_key else s3_key,
                content=compressed,
                folder="memory-cold",
            )
            entry.s3_key = url
            return url
        except Exception:
            logger.warning("archive: 写入存储失败 key=%s", s3_key, exc_info=True)
            return None

    def read_archive(self, s3_key: str) -> Optional[ColdStorageEntry]:
        """从冷存储读取并解压冷记忆条目。

        Args:
            s3_key: 冷存储对象键或访问 URL

        Returns:
            ColdStorageEntry，对象不存在或异常时返回 None
        """
        storage = self._get_storage_service()
        if storage is None:
            logger.warning("read_archive: 存储服务不可用")
            return None

        try:
            # 兼容新版 URL 与旧版存储键
            if isinstance(s3_key, str) and s3_key.startswith(("http://", "https://")):
                url = s3_key
            else:
                url = storage.get_file_url(s3_key)
            if not url:
                return None
            import requests as _requests
            resp = _requests.get(url, timeout=30)
            resp.raise_for_status()
            raw = resp.content
            decompressed = gzip.decompress(raw)
            return ColdStorageEntry.model_validate_json(decompressed)
        except Exception:
            # 对象不存在或其他异常均返回 None
            logger.debug("read_archive: 读取失败 key=%s", s3_key, exc_info=True)
            return None

    def list_user_archives(
        self,
        user_id: str,
        year: Optional[int] = None,
    ) -> list[str]:
        """列出用户的所有冷归档键，可按年份限定。

        Args:
            user_id: 用户标识
            year: 可选年份过滤

        Returns:
            对象键列表
        """
        storage = self._get_storage_service()
        if storage is None:
            return []

        # 统一存储端口（ObjectStoragePort）不支持列举操作，降级返回空列表。
        # 原 COS SDK 的 list_objects 已不再可用，遍历类策略（global_traverse /
        # statistical_mining）在无列举能力时返回空结果，与存储不可用时的降级行为一致。
        logger.debug("list_user_archives: 统一存储端口不支持列举，返回空列表 user=%s", user_id)
        return []

    # =========================================================
    # 三种激活策略
    # =========================================================

    def global_traverse(
        self,
        user_id: str,
        threshold_weight: float = 0.5,
    ) -> RebuildResult:
        """策略 1：全量遍历冷存储，将权重回升的条目恢复到 Neo4j 热层。

        Args:
            user_id: 用户标识
            threshold_weight: 恢复阈值

        Returns:
            RebuildResult 重建结果
        """
        started = datetime.now(UTC)
        result = RebuildResult(success=True)

        keys = self.list_user_archives(user_id)
        result.rebuilt_count = 0  # 先用字段暂存 scanned 计数

        for key in keys:
            try:
                entry = self.read_archive(key)
                if entry is None:
                    continue
                # 计算恢复潜力分
                cooccurrence = entry.metadata.get("cooccurrence_count", 0)
                recovery_score = entry.weight + cooccurrence * 0.05

                if recovery_score >= threshold_weight:
                    self._restore_to_neo4j(entry)
                    result.rebuilt_count += 1
            except Exception:
                result.errors.append(f"读取/恢复失败: {key}")

        result.duration_s = (datetime.now(UTC) - started).total_seconds()
        return result

    def rebuild_key_from_value(self, entry: ColdStorageEntry) -> Optional[str]:
        """策略 2：从值内容重建 Key（主题/关键词提取）。

        Args:
            entry: 冷存储条目

        Returns:
            Top-3 关键词以 ``|`` 连接的字符串，空内容返回 None
        """
        content = (entry.content or "").strip()
        if not content:
            return None

        # 取前 500 字符，正则提取英文词
        sample = content[:500]
        words = re.findall(r"[A-Za-z]{2,}", sample.lower())
        # 过滤停用词
        filtered = [w for w in words if w not in _STOP_WORDS]
        if not filtered:
            return None

        # Top-3 关键词
        counter = Counter(filtered)
        top_keywords = [word for word, _ in counter.most_common(3)]
        if not top_keywords:
            return None

        return "|".join(top_keywords)

    def statistical_mining(
        self,
        user_id: str,
        min_support: int = 3,
    ) -> list[dict]:
        """策略 3：统计挖掘冷存储中的潜在技能模式。

        Args:
            user_id: 用户标识
            min_support: 最小支持度

        Returns:
            ``[{"pattern": str, "count": int, "keys": list[str]}]`` 按 count 降序
        """
        keys = self.list_user_archives(user_id)
        pattern_counter: dict[str, list[str]] = {}

        for key in keys:
            entry = self.read_archive(key)
            if entry is None:
                continue
            pattern = self.rebuild_key_from_value(entry)
            if pattern is None:
                continue
            if pattern not in pattern_counter:
                pattern_counter[pattern] = []
            pattern_counter[pattern].append(key)

        # 按 min_support 过滤，按 count 降序
        results = [
            {
                "pattern": pattern,
                "count": len(ks),
                "keys": ks,
            }
            for pattern, ks in pattern_counter.items()
            if len(ks) >= min_support
        ]
        results.sort(key=lambda x: x["count"], reverse=True)
        return results

    # =========================================================
    # 内部方法
    # =========================================================

    def _restore_to_neo4j(self, entry: ColdStorageEntry) -> None:
        """将冷条目恢复到 Neo4j 热层（storage_tier=hot）。"""
        driver = self._driver or self._get_driver()
        if driver is None:
            return

        try:
            cypher = """
            MERGE (n) WHERE (n:MemoryNode OR n:Episode OR n:Entity) AND n.node_id = $node_id
            SET n.content = $content,
                n.weight = $weight,
                n.storage_tier = 'hot',
                n.restored_at = $now,
                n.is_active = true,
                n.user_id = $user_id
            """
            with driver.session() as session:
                session.run(
                    cypher,
                    {
                        "node_id": str(entry.node_id),
                        "content": entry.content[:2000],
                        "weight": entry.weight,
                        "now": datetime.now(UTC).isoformat(),
                        "user_id": entry.user_id,
                    },
                ).consume()
        except Exception:
            logger.warning(
                "_restore_to_neo4j: 恢复失败 node_id=%s",
                entry.node_id,
                exc_info=True,
            )

    def _get_storage_service(self):
        """获取统一存储服务实例（ObjectStoragePort），不可用时返回 None。

        不再直接调用 CosService._get_client() 硬编码 COS，而是通过 DI 注入的
        ObjectStoragePort 实例分发到当前 STORAGE_BACKEND 配置的后端。
        """
        try:
            from internal.context import current_app
            current_app._get_current_object()
        except RuntimeError:
            return None

        try:
            from app.http.module import injector
            from internal.core.ports.storage_port import ObjectStoragePort
            return injector.get(ObjectStoragePort)
        except Exception:
            logger.warning("_get_storage_service: 获取存储服务失败", exc_info=True)
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
