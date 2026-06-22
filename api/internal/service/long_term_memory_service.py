import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from injector import inject
from pydantic import BaseModel, Field

from internal.exception import NotFoundException
from internal.model import Account, MemoryCandidate, UserMemory
from internal.service.language_model_service import LanguageModelService
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

logger = logging.getLogger(__name__)


class MemoryFact(BaseModel):
    memory_type: str = Field(description="记忆类型: profile/preference/relationship/event/project/secret")
    content: str = Field(description="记忆内容")
    candidate_key: str = Field(description="语义去重键，如 profile:job_title:frontend_engineer")
    confidence: int = Field(description="置信度 1-5", ge=1, le=5)


class MemoryExtractionResult(BaseModel):
    facts: list[MemoryFact] = Field(default_factory=list, description="抽取的记忆事实列表")


EXTRACTION_PROMPT_TEMPLATE = """你是一个记忆抽取专家。分析以下用户与AI的对话，提取值得长期记住的用户事实。

记忆类型说明：
- profile: 用户的身份/职业/技能（如"我是前端工程师""我擅长Python"）
- preference: 用户的偏好/风格/习惯（如"喜欢简洁的回答""用TypeScript"）
- relationship: 用户的人际关系（如"我的团队有5人""我的领导叫张三"）
- event: 用户的日程/截止日期/计划（如"周五要交付项目""下个月有会议"）
- project: 用户的项目背景/技术栈（如"在做电商系统""用React+Node"）
- secret: 凭证/密钥（需加密，暂不实现加密，标记类型即可）

抽取规则：
1. 只抽取明确表达的事实，不猜测
2. 只抽取有长期价值的，忽略临时性内容
3. 如果没有值得记住的事实，返回空列表
4. confidence: 5=非常明确(用户直接说"记住")，4=明确陈述，3=较强暗示，2=弱暗示，1=不确定

用户输入：{query}
AI回答：{ai_response}"""


@inject
@dataclass
class MemoryCandidateExtractor:
    language_model_service: LanguageModelService

    def extract(self, query: str, ai_response: str) -> list[dict]:
        try:
            llm = self.language_model_service.get_cheap_chat_model()
            structured = llm.with_structured_output(MemoryExtractionResult)
            prompt = EXTRACTION_PROMPT_TEMPLATE.format(query=query, ai_response=ai_response)
            result: MemoryExtractionResult = structured.invoke(prompt)
            return [
                {
                    "memory_type": fact.memory_type,
                    "content": fact.content,
                    "candidate_key": fact.candidate_key,
                    "confidence": fact.confidence,
                }
                for fact in result.facts
            ]
        except Exception:
            logger.warning("记忆抽取LLM调用失败，降级返回空列表", exc_info=True)
            return []


@inject
@dataclass
class MemoryConfidenceTracker(BaseService):
    db: SQLAlchemy

    def track(self, account: Account, extracted: dict, conversation_id=None) -> dict:
        if extracted is None:
            return {"should_prompt": False, "candidate": None}
        candidate = (
            self.db.session.query(MemoryCandidate)
            .filter_by(owner_account_id=account.id, candidate_key=extracted["candidate_key"])
            .one_or_none()
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        if candidate is None:
            candidate = self.create(
                MemoryCandidate,
                owner_account_id=account.id,
                candidate_key=extracted["candidate_key"],
                content=extracted["content"],
                confidence=extracted["confidence"],
                occurrences=1,
                status="pending",
                memory_type=extracted.get("memory_type", "preference"),
                source_conversation_id=conversation_id,
                extracted_at=now,
            )
            return {"should_prompt": False, "candidate": candidate}
        if candidate.status != "pending" or (candidate.metadata_ or {}).get("never_remind"):
            return {"should_prompt": False, "candidate": candidate}
        candidate.occurrences += 1
        candidate.confidence = max(candidate.confidence, int(extracted["confidence"]))
        if conversation_id is not None:
            candidate.source_conversation_id = conversation_id
        candidate.extracted_at = now
        should_prompt = candidate.occurrences >= 3 and candidate.confidence >= 3
        return {"should_prompt": should_prompt, "candidate": candidate}


@inject
@dataclass
class UserMemoryConfirmationService(BaseService):
    db: SQLAlchemy

    def confirm(self, candidate_id, account: Account, *, policy: str = "manual_confirm") -> UserMemory:
        candidate = self._get_candidate(candidate_id, account)
        candidate.status = "confirmed"
        candidate.metadata_ = {**(candidate.metadata_ or {}), "policy": policy}
        memory = self.create(
            UserMemory,
            owner_account_id=account.id,
            memory_type=candidate.memory_type or (candidate.metadata_ or {}).get("memory_type", "preference"),
            content=candidate.content,
            confidence=candidate.confidence,
            status="active",
            created_from="conversation_memory",
            metadata_={"source_candidate_id": str(candidate.id), "policy": policy},
        )
        try:
            self._index_memory_vector(memory)
        except Exception:
            logger.warning("确认记忆后写入向量库失败，不影响主流程", exc_info=True)
        return memory

    def ignore(
        self, candidate_id, account: Account, *, never_remind: bool = False
    ) -> MemoryCandidate:
        candidate = self._get_candidate(candidate_id, account)
        candidate.status = "ignored"
        candidate.metadata_ = {**(candidate.metadata_ or {}), "never_remind": never_remind}
        return candidate

    def _get_candidate(self, candidate_id, account: Account) -> MemoryCandidate:
        candidate = (
            self.db.session.query(MemoryCandidate)
            .filter_by(id=candidate_id)
            .one_or_none()
        )
        if candidate is None or candidate.owner_account_id != account.id:
            raise NotFoundException("记忆候选不存在")
        return candidate

    def _index_memory_vector(self, memory: UserMemory) -> None:
        from flask import current_app
        from internal.service.memory_vector_service import MemoryVectorService
        memory_vector_service = current_app.injector.get(MemoryVectorService)
        memory_vector_service.index_memory(memory)


@inject
@dataclass
class LongTermMemoryService(BaseService):
    db: SQLAlchemy
    memory_candidate_extractor: MemoryCandidateExtractor
    memory_confidence_tracker: MemoryConfidenceTracker

    def extract_and_store(
        self, account: Account, query: str, ai_response: str, conversation_id=None
    ) -> list[dict]:
        facts = self.memory_candidate_extractor.extract(query, ai_response)
        results: list[dict] = []
        for fact in facts:
            track_result = self.memory_confidence_tracker.track(account, fact, conversation_id)
            candidate = track_result["candidate"]
            results.append({
                "candidate_id": candidate.id if candidate else None,
                "candidate_key": fact["candidate_key"],
                "memory_type": fact["memory_type"],
                "content": fact["content"],
                "status": candidate.status if candidate else None,
                "created": bool(candidate and candidate.occurrences == 1),
                "should_prompt": track_result["should_prompt"],
            })
        return results
