from dataclasses import dataclass

from injector import inject

from internal.exception import NotFoundException
from internal.model import Account, MemoryCandidate, UserMemory
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


class MemoryCandidateExtractor:
    def extract(self, text: str) -> dict[str, object] | None:
        normalized = (text or "").strip()
        if "中文" in normalized and ("回答" in normalized or "回复" in normalized):
            return {
                "candidate_key": "language_preference:zh",
                "memory_type": "preference",
                "content": "用户偏好使用中文回答",
                "confidence": 3,
            }
        return None


@inject
@dataclass
class MemoryConfidenceTracker(BaseService):
    db: SQLAlchemy

    def track(self, account: Account, extracted: dict[str, object] | None) -> dict[str, object]:
        if extracted is None:
            return {"should_prompt": False, "candidate": None}
        candidate = (
            self.db.session.query(MemoryCandidate)
            .filter_by(owner_account_id=account.id, candidate_key=extracted["candidate_key"])
            .one_or_none()
        )
        if candidate is None:
            candidate = self.create(
                MemoryCandidate,
                owner_account_id=account.id,
                candidate_key=extracted["candidate_key"],
                content=extracted["content"],
                confidence=extracted["confidence"],
                occurrences=1,
                status="pending",
                metadata_={"memory_type": extracted["memory_type"]},
            )
            return {"should_prompt": False, "candidate": candidate}
        if candidate.status != "pending" or candidate.metadata_.get("never_remind"):
            return {"should_prompt": False, "candidate": candidate}
        candidate.occurrences += 1
        candidate.confidence = max(candidate.confidence, int(extracted["confidence"]))
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
        return self.create(
            UserMemory,
            owner_account_id=account.id,
            memory_type=candidate.metadata_.get("memory_type", "preference"),
            content=candidate.content,
            confidence=candidate.confidence,
            status="active",
            created_from="conversation_memory",
            metadata_={"source_candidate_id": str(candidate.id), "policy": policy},
        )

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


@inject
@dataclass
class LongTermMemoryService(BaseService):
    db: SQLAlchemy

    def extract_and_store(self, account: Account, text: str) -> dict[str, object] | None:
        extracted = MemoryCandidateExtractor().extract(text)
        if extracted is None:
            return None
        candidate = (
            self.db.session.query(MemoryCandidate)
            .filter_by(owner_account_id=account.id, candidate_key=extracted["candidate_key"])
            .one_or_none()
        )
        if candidate is not None:
            candidate.occurrences += 1
            candidate.confidence = max(candidate.confidence, int(extracted["confidence"]))
            return {
                "candidate_id": candidate.id,
                "candidate_key": candidate.candidate_key,
                "status": candidate.status,
                "created": False,
            }
        candidate = self.create(
            MemoryCandidate,
            owner_account_id=account.id,
            candidate_key=extracted["candidate_key"],
            content=extracted["content"],
            confidence=extracted["confidence"],
            occurrences=1,
            status="pending",
            metadata_={"memory_type": extracted["memory_type"]},
        )
        return {
            "candidate_id": candidate.id,
            "candidate_key": candidate.candidate_key,
            "status": candidate.status,
            "created": True,
        }
