import json
import logging
import re
from dataclasses import dataclass

import requests
from injector import inject
from langchain_core.documents import Document as LCDocument

from internal.core.agent.usage_utils import charge_for_feature, extract_token_usage
from .credit_service import CreditService
from .language_model_service import LanguageModelService

logger = logging.getLogger(__name__)

_MAX_LLM_RERANK_DOCS = 20
_MAX_DOC_CONTENT_CHARS = 500


@inject
@dataclass
class RerankService:
    """文档重排序服务，对检索结果做二次精排"""

    language_model_service: LanguageModelService
    credit_service: CreditService | None = None

    def rerank(
        self,
        query: str,
        documents: list[dict],
        top_n: int = 5,
        account_id=None,
    ) -> list[dict]:
        """对文档列表按与 query 的相关性重排序，失败时降级返回原始结果"""
        if not documents:
            return []
        if len(documents) == 1:
            return documents[: max(top_n, 1)]

        try:
            reranked = self._rerank_with_provider(query, documents, top_n)
            if reranked is not None:
                return reranked
        except Exception:
            logger.warning("Provider rerank 失败，降级到 LLM 打分", exc_info=True)

        try:
            reranked = self._rerank_with_llm(query, documents, top_n, account_id=account_id)
            if reranked is not None:
                return reranked
        except Exception:
            logger.warning("LLM 打分 rerank 失败，降级到原始 score 排序", exc_info=True)

        return self._rerank_by_original_score(documents, top_n)

    def rerank_documents(
        self,
        query: str,
        documents: list[LCDocument],
        top_n: int = 5,
        account_id=None,
    ) -> list[LCDocument]:
        """对 LangChain 文档列表重排序并返回新的文档列表"""
        if not documents:
            return []
        payload = [
            {
                "content": doc.page_content,
                "score": doc.metadata.get("score", 0) if doc.metadata else 0,
                "metadata": dict(doc.metadata or {}),
            }
            for doc in documents
        ]
        reranked = self.rerank(query, payload, top_n=top_n, account_id=account_id)
        result: list[LCDocument] = []
        for item in reranked:
            metadata = dict(item.get("metadata") or {})
            metadata["score"] = item.get("rerank_score", item.get("score", 0))
            result.append(LCDocument(page_content=item.get("content", ""), metadata=metadata))
        return result

    def _rerank_with_provider(self, query: str, documents: list[dict], top_n: int):
        """从数据库查询 rerank 模型凭证，调用 provider rerank API 做重排序。

        替代原来从环境变量 COHERE_API_KEY 读取的方式，统一走 admin 数据库管理。
        SiliconFlow rerank API 格式与 Cohere 类似，直接 HTTP 调用。
        """
        creds = LanguageModelService.get_provider_credentials(model_type="rerank")
        if not creds or not creds.get("api_key") or not creds.get("model"):
            return None

        api_key = creds["api_key"]
        base_url = (creds.get("base_url") or "").rstrip("/")
        model = creds["model"]
        if not base_url:
            return None

        endpoint = f"{base_url}/rerank"
        try:
            resp = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "query": query,
                    "documents": [str(doc.get("content", "")) for doc in documents],
                    "top_n": min(max(top_n, 1), len(documents)),
                    "return_documents": False,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                return None

            scored: list[dict] = []
            for item in results:
                idx = item.get("index")
                score = item.get("relevance_score")
                if idx is None or score is None:
                    continue
                try:
                    idx_int = int(idx)
                    score_float = float(score)
                except (TypeError, ValueError):
                    continue
                if 0 <= idx_int < len(documents):
                    scored.append({**documents[idx_int], "rerank_score": score_float})
            scored.sort(key=lambda d: d.get("rerank_score", 0), reverse=True)
            return scored[:top_n]
        except Exception:
            logger.warning("Provider rerank API 调用失败", exc_info=True)
            return None

    def _rerank_with_llm(self, query: str, documents: list[dict], top_n: int, account_id=None):
        if self.language_model_service is None:
            return None
        llm = LanguageModelService.get_feature_model("rerank_fallback")
        if llm is None:
            return None

        candidates = documents[:_MAX_LLM_RERANK_DOCS]
        lines = []
        for idx, doc in enumerate(candidates):
            content = str(doc.get("content", ""))[:_MAX_DOC_CONTENT_CHARS]
            lines.append(f"[{idx}] {content}")
        prompt = (
            "你是相关性评估助手。请根据用户问题为每个候选文档的相关性打分（1-10，10最相关）。\n"
            f"用户问题：{query}\n"
            "候选文档：\n" + "\n".join(lines) + "\n"
            "请只输出JSON数组，格式：[{\"index\": 0, \"score\": 9}, ...]，不要输出其他内容。"
        )
        response = llm.invoke(prompt)

        # 公共 AI 功能计费（非消息上下文）
        token_usage = extract_token_usage(response)
        if token_usage and account_id is not None:
            charge_for_feature(
                self.credit_service,
                account_id,
                "rerank_fallback",
                token_usage["total_tokens"],
            )

        text = self._extract_response_text(response)
        scores = self._parse_scores(text, len(candidates))
        if scores is None:
            return None

        scored: list[dict] = []
        for idx, doc in enumerate(candidates):
            score = scores.get(idx)
            if score is None:
                score = doc.get("score", 0)
            scored.append({**doc, "rerank_score": float(score)})
        scored.sort(key=lambda d: d.get("rerank_score", 0), reverse=True)
        return scored[:top_n]

    def _rerank_by_original_score(self, documents: list[dict], top_n: int) -> list[dict]:
        scored = sorted(documents, key=lambda d: d.get("score", 0), reverse=True)
        return scored[:top_n]

    def _extract_response_text(self, response) -> str:
        if response is None:
            return ""
        content = getattr(response, "content", None)
        if content is None:
            content = response
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            return "".join(parts)
        return str(content)

    def _parse_scores(self, text: str, count: int):
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except Exception:
            return None
        if not isinstance(data, list):
            return None
        scores: dict[int, float] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            score = item.get("score")
            if idx is None or score is None:
                continue
            try:
                idx_int = int(idx)
                score_float = float(score)
            except (TypeError, ValueError):
                continue
            if 0 <= idx_int < count:
                scores[idx_int] = score_float
        return scores if scores else None
