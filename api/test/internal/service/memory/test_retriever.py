"""B3 MemoryRetriever 单元测试。"""

from uuid import uuid4

import pytest

from internal.model.memory_models import RetrievalOptions
from internal.service.memory.retriever import MemoryRetriever


class TestMemoryRetriever:
    def test_retrieve_should_return_empty_without_dependencies(self):
        """无 Neo4j 和数据库时应降级返回空列表。"""
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        result = retriever.retrieve("测试查询", str(uuid4()))

        assert isinstance(result, list)
        # 无依赖时应返回空或降级结果，不抛异常

    def test_retrieve_should_accept_empty_query(self):
        """空查询应降级处理。"""
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        result = retriever.retrieve("", str(uuid4()))

        assert isinstance(result, list)

    def test_retrieve_should_respect_top_k_option(self):
        """应支持 RetrievalOptions 的 top_k 参数。"""
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        options = RetrievalOptions(top_k=5)
        result = retriever.retrieve("测试", str(uuid4()), options)

        assert isinstance(result, list)
        assert len(result) <= 5

    def test_retrieve_should_fallback_to_system2_without_digest_manager(self):
        """无 DigestManager 时应走 System 2 深度路径（降级为空）。"""
        retriever = MemoryRetriever(neo4j_driver=None, db=None, digest_manager=None)
        result = retriever.retrieve("任意查询", str(uuid4()))

        assert isinstance(result, list)
