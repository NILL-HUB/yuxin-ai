from types import SimpleNamespace
from uuid import uuid4

from internal.service.external_data_retrieval_tool import (
    ExternalDataRetrievalTool,
    create_external_data_retrieval_tool,
)


class _FakeApp:
    def __init__(self):
        self.entered = False

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def app_context(self):
        return self._Ctx()


class _FakeRetrievalService:
    def __init__(self, documents):
        self._documents = documents
        self.calls = []

    def search_in_knowledge_base(self, *, knowledge_base_ids, query, account_id):
        self.calls.append({"query": query, "account_id": account_id})
        return self._documents


def test_external_data_retrieval_tool_metadata():
    tool = ExternalDataRetrievalTool()
    assert tool.name == "external_data_retrieval"
    assert tool.description == "检索用户连接的外部数据源内容"


def test_external_data_retrieval_tool_run_should_return_combined_content():
    account_id = uuid4()
    knowledge_base_ids = [uuid4()]
    app = _FakeApp()
    documents = [
        SimpleNamespace(page_content="文档内容1"),
        SimpleNamespace(page_content="文档内容2"),
    ]
    retrieval_service = _FakeRetrievalService(documents)

    tool = create_external_data_retrieval_tool(
        flask_app=app,
        account_id=account_id,
        knowledge_base_ids=knowledge_base_ids,
        retrieval_service=retrieval_service,
    )

    result = tool._run(query="测试查询")

    assert result == "文档内容1\n\n文档内容2"
    assert retrieval_service.calls[0]["query"] == "测试查询"
    assert retrieval_service.calls[0]["account_id"] == account_id


def test_external_data_retrieval_tool_run_should_return_empty_message_when_no_hits():
    app = _FakeApp()
    retrieval_service = _FakeRetrievalService([])

    tool = create_external_data_retrieval_tool(
        flask_app=app,
        account_id=uuid4(),
        knowledge_base_ids=[uuid4()],
        retrieval_service=retrieval_service,
    )

    result = tool._run(query="无结果查询")

    assert result == "外部数据源未检索到对应内容"


def test_external_data_retrieval_tool_run_should_return_message_without_config():
    tool = ExternalDataRetrievalTool()

    result = tool._run(query="任意查询")

    assert result == "外部数据源未配置可用知识库"
