"""C3 RepresentationRepulsion 单元测试。"""

from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from internal.service.memory.representation_repulsion import RepresentationRepulsion


class TestRepresentationRepulsion:
    def test_repulse_should_degrade_when_db_unavailable(self):
        """无数据库时应降级返回零值。"""
        repulsion = RepresentationRepulsion(db=None)
        result = repulsion.repulse(str(uuid4()))

        assert result == {"scanned": 0, "repulsed_pairs": 0}

    def test_repulse_should_handle_empty_user(self):
        """用户无向量时应返回零值。"""
        # 构造一个返回空列表的假 session
        class _EmptyQuery:
            def filter(self, *_a, **_k):
                return self

            def all(self):
                return []

        fake_db = SimpleNamespace(session=SimpleNamespace(query=lambda _m: _EmptyQuery()))
        repulsion = RepresentationRepulsion(db=fake_db)
        result = repulsion.repulse(str(uuid4()))

        assert result == {"scanned": 0, "repulsed_pairs": 0}

    def test_cosine_similarity_should_return_one_for_identical_vectors(self):
        """相同向量余弦相似度应为 1。"""
        vec = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        sim = RepresentationRepulsion._cosine_similarity(vec, vec)

        assert abs(sim - 1.0) < 1e-6

    def test_cosine_similarity_should_return_zero_for_orthogonal_vectors(self):
        """正交向量余弦相似度应为 0。"""
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        sim = RepresentationRepulsion._cosine_similarity(a, b)

        assert abs(sim) < 1e-6

    def test_normalize_should_return_unit_vector(self):
        """归一化后向量模长应为 1。"""
        vec = np.array([3.0, 4.0], dtype=np.float32)
        normalized = RepresentationRepulsion._normalize(vec)

        assert abs(np.linalg.norm(normalized) - 1.0) < 1e-6

    def test_normalize_should_handle_zero_vector(self):
        """零向量归一化不应抛异常。"""
        vec = np.zeros(3, dtype=np.float32)
        normalized = RepresentationRepulsion._normalize(vec)

        assert np.allclose(normalized, vec)
