"""表征排斥（RepresentationRepulsion）。

对语义过近但实际不同的记忆拉开嵌入距离，避免灾难性遗忘。灵感来自神经科学的
反向重播（reverse replay）——在学习新记忆时，系统会"反向重播"相关记忆以区分
新旧表征。当两条记忆的向量余弦相似度超过阈值时，在嵌入空间中沿连线方向将两者
推开。

降级策略:
    - 数据库不可用时返回 ``{"scanned": 0, "repulsed_pairs": 0}``
    - numpy 不可用时降级跳过

设计参考:
    docs/prd/memory-system/03-consolidation-skill-policy-api.md §7.3
    docs/prd/memory-system/execution/04-track-c-consolidation.md C3
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


class RepresentationRepulsion:
    """表征排斥器。

    不使用 ``@inject``：无注入依赖，通过构造函数接收 db（SQLAlchemy）。
    操作 pgvector ``user_memory.embedding`` 列。
    """

    def __init__(
        self,
        db=None,
        table_name: str = "user_memory",
        embedding_column: str = "embedding",
    ) -> None:
        """初始化表征排斥器。

        Args:
            db: SQLAlchemy 实例，None 时从 current_app 获取
            table_name: pgvector 表名
            embedding_column: 向量列名
        """
        self._db = db
        self._table_name = table_name
        self._embedding_column = embedding_column

    def repulse(
        self,
        user_id: str,
        threshold: float = 0.95,
        gamma: float = 0.1,
    ) -> dict:
        """找到余弦相似度 > threshold 的向量对，沿排斥方向微调。

        步骤:
            1. 查询 user_memory 表该用户全部向量行（含 id 与 embedding 列）
            2. 对每对计算余弦相似度，超过 threshold 的标记
            3. 沿连线方向各推 gamma/2 距离，归一化后批量 UPDATE

        Args:
            user_id: 用户标识
            threshold: 相似度阈值（默认 0.95）
            gamma: 排斥力度（默认 0.1）

        Returns:
            ``{"scanned": int, "repulsed_pairs": int}``
        """
        db = self._db or self._get_db()
        if db is None:
            logger.warning("RepresentationRepulsion.repulse: 数据库不可用")
            return {"scanned": 0, "repulsed_pairs": 0}

        # 1. 查询该用户全部向量行
        try:
            from internal.model.knowledge import UserMemory

            rows = (
                db.session.query(
                    UserMemory.id,
                    UserMemory.embedding,
                )
                .filter(UserMemory.owner_account_id == user_id)
                .filter(UserMemory.embedding.isnot(None))
                .all()
            )
        except Exception:
            logger.warning(
                "RepresentationRepulsion.repulse: 查询向量失败",
                exc_info=True,
            )
            return {"scanned": 0, "repulsed_pairs": 0}

        if not rows:
            return {"scanned": 0, "repulsed_pairs": 0}

        # 2. 构造 id → embedding 映射
        point_map: dict = {}
        for row in rows:
            if row.embedding is None:
                continue
            vec = np.array(row.embedding, dtype=np.float32)
            point_map[str(row.id)] = vec

        point_ids = list(point_map.keys())
        scanned = len(point_ids)

        if scanned == 0:
            return {"scanned": 0, "repulsed_pairs": 0}

        # 3. 双重循环遍历所有点对 (i, j), i < j
        updates: list[tuple[str, np.ndarray]] = []
        repulsed_pairs = 0

        for i in range(scanned):
            for j in range(i + 1, scanned):
                vec_a = point_map[point_ids[i]]
                vec_b = point_map[point_ids[j]]

                # 计算余弦相似度
                cos_sim = self._cosine_similarity(vec_a, vec_b)
                if cos_sim < threshold:
                    continue

                # 计算排斥方向：a - b（a 远离 b 的方向）
                direction = vec_a - vec_b
                norm_dir = np.linalg.norm(direction)
                if norm_dir < 1e-10:
                    continue
                norm_direction = direction / norm_dir

                # 各推 gamma/2 距离
                new_a = vec_a + norm_direction * (gamma / 2)
                new_b = vec_b - norm_direction * (gamma / 2)

                # 归一化到单位长度
                new_a = self._normalize(new_a)
                new_b = self._normalize(new_b)

                point_map[point_ids[i]] = new_a
                point_map[point_ids[j]] = new_b

                updates.append((point_ids[i], new_a))
                updates.append((point_ids[j], new_b))
                repulsed_pairs += 1

        # 4. 批量更新数据库
        if updates:
            try:
                self._batch_update_embeddings(db, updates)
            except Exception:
                logger.warning(
                    "RepresentationRepulsion.repulse: 批量更新向量失败",
                    exc_info=True,
                )

        return {"scanned": scanned, "repulsed_pairs": repulsed_pairs}

    # =========================================================
    # 内部方法
    # =========================================================

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """计算两个向量的余弦相似度。"""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a < 1e-10 or norm_b < 1e-10:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    @staticmethod
    def _normalize(vec: np.ndarray) -> np.ndarray:
        """归一化向量到单位长度。"""
        norm = np.linalg.norm(vec)
        if norm < 1e-10:
            return vec
        return vec / norm

    def _batch_update_embeddings(
        self,
        db,
        updates: list[tuple[str, np.ndarray]],
    ) -> None:
        """批量更新 user_memory.embedding 列。"""
        from internal.model.knowledge import UserMemory

        for memory_id, vec in updates:
            # 将 numpy 数组转为列表写入
            vec_list = vec.tolist()
            (
                db.session.query(UserMemory)
                .filter(UserMemory.id == memory_id)
                .update({UserMemory.embedding: vec_list})
            )

        db.session.commit()

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
