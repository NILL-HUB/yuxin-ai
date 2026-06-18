from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field


class ExternalDataRetrievalInput(BaseModel):
    query: str = Field(description="检索问题，用于在外部数据源知识库中检索相关内容")


class ExternalDataRetrievalTool(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "external_data_retrieval"
    description: str = "检索用户连接的外部数据源内容"
    args_schema: type[BaseModel] = ExternalDataRetrievalInput

    flask_app: Any = None
    account_id: Any = None
    knowledge_base_ids: list[UUID] = Field(default_factory=list)
    retrieval_service: Any = None

    def _run(self, query: str, **kwargs: Any) -> str:
        if not self.knowledge_base_ids or self.retrieval_service is None:
            return "外部数据源未配置可用知识库"
        with self.flask_app.app_context():
            documents = self.retrieval_service.search_in_knowledge_base(
                knowledge_base_ids=self.knowledge_base_ids,
                query=query,
                account_id=self.account_id,
            )
        if not documents:
            return "外部数据源未检索到对应内容"
        return "\n\n".join(doc.page_content for doc in documents)

    async def _arun(self, query: str, **kwargs: Any) -> str:
        return self._run(query, **kwargs)


def create_external_data_retrieval_tool(
    *,
    flask_app: Any,
    account_id: UUID,
    knowledge_base_ids: list[UUID],
    retrieval_service: Any,
) -> BaseTool:
    return ExternalDataRetrievalTool(
        flask_app=flask_app,
        account_id=account_id,
        knowledge_base_ids=list(knowledge_base_ids),
        retrieval_service=retrieval_service,
    )
