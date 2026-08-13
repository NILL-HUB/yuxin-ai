"""审批历史挖掘与拒绝熔断。

移植自 NousResearch/hermes-agent `hermes_cli/approvals_suggest.py`
（MIT License）的安全策略：

- 只从“已确认”的审批记录中挖掘可安全放行的 allowlist 建议；
- 破坏性/提权/凭证类工具永不进入建议；
- 建议是 dry-run 输出，不自动生效；
- 同一工具 + 同一参数签名连续被拒时触发熔断信号，阻止坏循环反复请求。

按本项目 `tool_confirmation` 表结构调整为纯函数 + 薄服务两层。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ConfirmationRecord:
    """tool_confirmation 记录的只读投影，便于脱离 ORM 测试。"""

    tool_name: str
    status: str
    tool_input: dict[str, Any] = field(default_factory=dict)
    execution_summary: str = ""
    reason: str = ""
    created_at: datetime | None = None


@dataclass
class AllowlistProposal:
    tool_name: str
    approved_count: int
    summary: str
    sample_input: dict[str, Any] = field(default_factory=dict)
    suggested_policy: str = "session"


@dataclass
class CircuitBreakerSignal:
    tool_name: str
    denial_count: int
    signature: str
    action: str = "block_loop"


@dataclass
class ApprovalMiningResult:
    proposals: list[AllowlistProposal] = field(default_factory=list)
    circuit_breakers: list[CircuitBreakerSignal] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


# 永不建议放行的工具族：破坏性、提权、凭证、磁盘/系统级操作。
_NEVER_PROPOSE_PATTERNS = (
    "delete",
    "drop",
    "format",
    "wipe",
    "shred",
    "chmod",
    "chown",
    "sudo",
    "credential",
    "secret",
    "password",
    "transfer_funds",
    "modify_billing",
    "deploy_application",
    "execute_shell",
)

_MIN_CONFIRMATIONS_FOR_PROPOSAL = 3
_CIRCUIT_BREAKER_THRESHOLD = 3


def _never_propose(tool_name: str) -> bool:
    normalized = tool_name.lower()
    return any(pattern in normalized for pattern in _NEVER_PROPOSE_PATTERNS)


def _normalize_input_signature(tool_input: dict[str, Any] | None) -> str:
    payload = dict(tool_input or {})
    # 忽略易变/敏感字段，避免把每次不同的 approval_token 当成不同签名。
    for key in ("approval_token", "requester", "timeout", "working_dir"):
        payload.pop(key, None)
    try:
        import json

        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        raw = str(sorted((str(k), str(v)) for k, v in payload.items()))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _build_summary(record: ConfirmationRecord) -> str:
    summary = (record.execution_summary or "").strip()
    if summary:
        return summary[:160]
    reason = (record.reason or "").strip()
    if reason:
        return reason[:160]
    return record.tool_name


def mine_approval_history(records: list[ConfirmationRecord]) -> ApprovalMiningResult:
    """从审批记录中生成 allowlist 建议与熔断信号。

    - proposals：同工具确认 >= 3 次且不属于永不建议族的 dry-run 建议；
    - circuit_breakers：同工具同参数签名连续拒绝 >= 3 次。
    """
    confirmed: dict[str, list[ConfirmationRecord]] = {}
    denied_signatures: dict[str, dict[str, int]] = {}
    total_confirmed = 0
    total_denied = 0

    for record in records:
        if record.status == "confirmed":
            confirmed.setdefault(record.tool_name, []).append(record)
            total_confirmed += 1
        elif record.status == "cancelled":
            total_denied += 1
            signature = _normalize_input_signature(record.tool_input)
            denied_signatures.setdefault(record.tool_name, {})[signature] = (
                denied_signatures.get(record.tool_name, {}).get(signature, 0) + 1
            )

    proposals: list[AllowlistProposal] = []
    for tool_name, records_for_tool in confirmed.items():
        if _never_propose(tool_name):
            continue
        if len(records_for_tool) < _MIN_CONFIRMATIONS_FOR_PROPOSAL:
            continue
        latest = records_for_tool[-1]
        proposals.append(
            AllowlistProposal(
                tool_name=tool_name,
                approved_count=len(records_for_tool),
                summary=_build_summary(latest),
                sample_input=latest.tool_input or {},
            )
        )

    breakers: list[CircuitBreakerSignal] = []
    for tool_name, signatures in denied_signatures.items():
        for signature, count in signatures.items():
            if count >= _CIRCUIT_BREAKER_THRESHOLD:
                breakers.append(
                    CircuitBreakerSignal(
                        tool_name=tool_name,
                        denial_count=count,
                        signature=signature,
                    )
                )

    proposals.sort(key=lambda p: p.approved_count, reverse=True)
    breakers.sort(key=lambda b: b.denial_count, reverse=True)
    return ApprovalMiningResult(
        proposals=proposals,
        circuit_breakers=breakers,
        stats={
            "total_records": len(records),
            "total_confirmed": total_confirmed,
            "total_denied": total_denied,
            "proposal_count": len(proposals),
            "circuit_breaker_count": len(breakers),
        },
    )


def as_serializable(result: ApprovalMiningResult) -> dict[str, Any]:
    return {
        "proposals": [
            {
                "tool_name": p.tool_name,
                "approved_count": p.approved_count,
                "summary": p.summary,
                "sample_input": p.sample_input,
                "suggested_policy": p.suggested_policy,
            }
            for p in result.proposals
        ],
        "circuit_breakers": [
            {
                "tool_name": b.tool_name,
                "denial_count": b.denial_count,
                "signature": b.signature,
                "action": b.action,
            }
            for b in result.circuit_breakers
        ],
        "stats": result.stats,
    }
