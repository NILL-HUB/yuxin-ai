# ADMIN-P3c-2 admin 对话记忆接线（读取召回 + 写入 + 治理主体化）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 P3c-1 已具备但**零调用方**的 admin 记忆写入/读取能力接进 `AdminAgentChatService`（镜像用户端「先召回、后写入」），并让 `MemoryGovernor` 的治理路径支持 admin 主体，使 admin 记忆真正端到端可达。

**Architecture:** 三层接线——(1) **读**：新增 `recall_admin_agent_memory_for_chat()`，以 `MemoryOwnerKey.for_admin(admin_user_id, agent_id=...)` 走 `MemoryRetriever`/`DigestManager`（P3b 已主体化的读路径，无需改）；(2) **写**：`AdminAgentChatService` 回答后调 `MemoryWriteService`（新增 `owner_key` 入口）；(3) **治理**：`MemoryGovernor._verify_owner` / `_delete_all_pgvector_rows` / `gdpr_delete` 改走主体谓词。

**Tech Stack:** Python 3.12 / LangChain / Neo4j / PostgreSQL（pgvector）/ Redis / pytest

---

## 0. 前置实测结论（执行者必读）

| # | 事实 | 依据 |
| --- | --- | --- |
| 1 | **P3c-1 的 `owner_key` 参数目前零生产调用方**（断链） | `LedgerWriter.write_full_path/write_summary_path/write_stats_path` 的 `owner_key` 仅测试传入；`MemoryWriteService.write_from_conversation(account, ...)` 无 `owner_key` 入口 |
| 2 | admin 对话链路对记忆**零接线** | `admin_agent_chat_service.py` 无 memory import；`_build_tools` 只装配板块工具 |
| 3 | admin **没有 account**（`admin_user.account_id` 恒 NULL），只能 `for_admin` | `admin_agent_entity.py` 模块头明确 |
| 4 | `AdminAgentPrincipal` 同时携带 `admin_user_id` + `agent_id` | `admin_agent_entity.py` L34-L35 |
| 5 | 读路径（`retriever` / `digest_manager` / 巩固链）P3b **已主体化** | 均收 `owner_key: str` + `MemoryOwnerKey.parse()` |
| 6 | `AdminAgentChatService` 是 `@inject @dataclass`，DI 仅 `db`；`chat()` 是生成器，**所有可预期异常必须转 `event: error` 帧**，不得逃出生成器 | `test_admin_agent_chat_service.py` 锁定了该契约 |

**关键不变量（违反即回归）**：

1. **用户端零变化**：`recall_user_memory_for_chat` / `MemoryWriteService.write_from_conversation(account, ...)` 签名与行为**不得改动**（既有调用方众多）；admin 走**新增**路径。
2. **记忆不得拖慢/阻断对话**：召回 fail-open（超时/异常返回空串）；写入在线程内异步、异常吞掉——与用户端同策。
3. **异常帧契约**：新增的记忆接线若在 `chat()` 的 try 内抛出，必须已被自身 try 吞掉；**不得**让记忆失败导致整轮对话以 error 帧结束。

---

## 1. 文件结构规划

### 新建文件

| 文件 | 职责 |
| --- | --- |
| `api/internal/service/memory/admin_memory_recall.py` | admin/Agent 主体召回（镜像 `user_memory_recall`，但传 `owner_key`） |
| `api/test/internal/service/memory/test_admin_memory_recall.py` | 召回单测（替身隔离） |
| `api/test/internal/service/memory/test_memory_write_service_owner.py` | `MemoryWriteService` 的 `owner_key` 入口判别性用例 |

### 修改文件

| 文件 | 改动 |
| --- | --- |
| `api/internal/service/memory/memory_write_service.py` | 新增 `write_from_event` 的 owner 透传 + 便捷入口 `write_admin_conversation`；`_write_*` 透传 `owner_key` |
| `api/internal/service/admin_agent_chat_service.py` | `chat()` 召回注入 + 答后写入；新增 `_recall_memory` / `_write_memory` 可替换点 |
| `api/internal/service/memory/memory_governor.py` | `_verify_owner` / `_delete_all_pgvector_rows` / `gdpr_delete` 主体化 |
| `api/test/internal/service/memory/test_memory_governor_owner_scope.py` | 治理主体化判别性用例（新建或追加） |
| `docs/prd/memory-system/02-storage-and-retrieval.md` | 关闭缺口九 / 缺口十六（升级后的部分） |
| `docs/prd/execution-roadmap.md` | 记录 ADMIN-P3c-2 |

---

## Task 1: admin/Agent 主体记忆召回

**Files:**
- Create: `api/internal/service/memory/admin_memory_recall.py`
- Test: `api/test/internal/service/memory/test_admin_memory_recall.py`

**背景**：`recall_user_memory_for_chat` 内部写死 `MemoryOwnerKey.for_user(account_id)`，admin 无法表达主体。新建镜像函数，复用**同一套** System1/System2 策略，仅主体键构造不同。

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/service/memory/test_admin_memory_recall.py`：

```python
"""admin / Agent 主体记忆召回（ADMIN-P3c-2）。

不变量：
1. 主体键必须是 `admin:{admin_uuid}[:{agent_uuid}]`（属性/键分离，不得退化成 for_user）；
2. 召回是增强项：引擎关闭/异常/超时一律返回空串（fail-open），绝不抛出。
"""
from uuid import uuid4

import pytest


def test_returns_empty_when_engine_disabled(monkeypatch):
    from internal.config.memory_settings import settings as memory_settings
    from internal.service.memory import admin_memory_recall

    monkeypatch.setattr(memory_settings, "memory_engine_enabled", False, raising=False)
    assert admin_memory_recall.recall_admin_agent_memory_for_chat(
        admin_user_id=uuid4(), query="hi"
    ) == ""


def test_empty_query_returns_empty():
    from internal.service.memory import admin_memory_recall

    assert admin_memory_recall.recall_admin_agent_memory_for_chat(
        admin_user_id=uuid4(), query="   "
    ) == ""


def test_owner_key_is_admin_scoped(monkeypatch):
    """判别性：主体键必须是 admin 形态（含 agent 时三级）。"""
    from internal.service.memory import admin_memory_recall
    from internal.entity.memory_owner_entity import MemoryOwnerKey

    admin_id, agent_id = uuid4(), uuid4()
    captured = {}

    def _fake_retrieve(*, owner_key):
        captured["owner_key"] = owner_key
        return "召回文本"

    monkeypatch.setattr(
        admin_memory_recall, "_retrieve_digest", lambda owner_key, query: ""
    )
    monkeypatch.setattr(
        admin_memory_recall, "_retrieve_deep", _fake_retrieve
    )

    text = admin_memory_recall.recall_admin_agent_memory_for_chat(
        admin_user_id=admin_id, agent_id=agent_id, query="我的偏好"
    )

    assert text == "召回文本"
    assert captured["owner_key"] == MemoryOwnerKey.for_admin(
        admin_id, agent_id=agent_id
    ).to_key()
    assert captured["owner_key"].startswith("admin:")


def test_exception_is_swallowed_returns_empty(monkeypatch):
    """召回异常必须 fail-open（不得让 admin 对话挂掉）。"""
    from internal.service.memory import admin_memory_recall

    def _boom(*args, **kwargs):
        raise RuntimeError("neo4j down")

    monkeypatch.setattr(admin_memory_recall, "_retrieve_digest", _boom)

    assert admin_memory_recall.recall_admin_agent_memory_for_chat(
        admin_user_id=uuid4(), query="hi"
    ) == ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/memory/test_admin_memory_recall.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（`ModuleNotFoundError: internal.service.memory.admin_memory_recall`）

- [ ] **Step 3: 实现召回模块**

创建 `api/internal/service/memory/admin_memory_recall.py`：

```python
"""管理端 Agent 长期记忆召回（ADMIN-P3c-2）。

与用户端 ``user_memory_recall`` 同策（System1 Digest 快路径 → System2 深度检索、
限时 fail-open），**唯一差别是主体键**：admin 走
``MemoryOwnerKey.for_admin(admin_user_id, agent_id=...)``——admin 没有 account，
绝不能伪造 ``for_user``。

读路径（``MemoryRetriever`` / ``DigestManager``）自 P3b 起已按主体键过滤，
故此处只负责构造正确的 ``owner_key`` 并组装文本，不重复实现检索。
"""
from __future__ import annotations

import logging
import threading
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)


def recall_admin_agent_memory_for_chat(
    *,
    admin_user_id: UUID,
    agent_id: Optional[UUID] = None,
    query: str,
    conversation_id: str = "",
    max_wait_seconds: float = 1.2,
    max_tokens: int = 1500,
) -> str:
    """召回 admin / Agent 主体记忆，组装为可注入提示词的文本。

    Args:
        admin_user_id: 发起管理员 id（主体键一级）。
        agent_id: 执行 Agent id；给出即为「每 Agent 一份记忆」的两级隔离。
        query: 本轮提问，用于 System 2 语义检索。
        conversation_id: 会话 id（当前仅日志/未来扩展）。
        max_wait_seconds: 召回超时上限，超时返回空串。
        max_tokens: 返回文本 token 量级上限（按 4 字符/token 估算）。

    Returns:
        记忆文本；任何异常或超时均返回空串（fail-open）。
    """
    from internal.config.memory_settings import settings as memory_settings

    if not memory_settings.memory_engine_enabled:
        return ""
    if not query or not str(query).strip():
        return ""

    from internal.entity.memory_owner_entity import MemoryOwnerKey

    owner_key = MemoryOwnerKey.for_admin(admin_user_id, agent_id=agent_id).to_key()
    char_budget = max(int(max_tokens) * 4, 500)
    result_box: dict = {"text": ""}

    def _do_retrieve() -> None:
        try:
            digest_text = _retrieve_digest(owner_key=owner_key, query=query)
            if digest_text:
                result_box["text"] = digest_text[:char_budget]
                return
            deep_text = _retrieve_deep(owner_key=owner_key, query=query)
            if deep_text:
                result_box["text"] = deep_text[:char_budget]
        except Exception:
            logger.warning("admin 记忆召回失败，静默降级", exc_info=True)

    worker = threading.Thread(target=_do_retrieve, daemon=True)
    worker.start()
    worker.join(timeout=max_wait_seconds)
    return result_box.get("text", "")


def _retrieve_digest(*, owner_key: str, query: str) -> str:
    """System 1：Digest 快路径（Redis 缓存）。

    ``DigestManager`` 依赖注入 ``redis_client``，**必须**经 DI 取得
    （`DigestManager()` 无参会缺 redis_client）——与 ``user_memory_recall`` 同法。
    """
    from app.http import asgi_app as a
    from internal.lib.runtime_context import app_session_scope
    from internal.service.memory.digest_manager import DigestManager
    from internal.service.memory.retriever import MemoryRetriever

    with app_session_scope():
        digest_manager = a._get_service(DigestManager)
        retriever = MemoryRetriever(digest_manager=digest_manager)
        return retriever._system1_fast_path(query, owner_key)


def _retrieve_deep(*, owner_key: str, query: str) -> str:
    """System 2：深度检索，命中原文拼接（top 5，每条 ≤600 字）。"""
    from app.http import asgi_app as a
    from internal.lib.runtime_context import app_session_scope
    from internal.model.memory_models import RetrievalOptions
    from internal.service.memory.digest_manager import DigestManager
    from internal.service.memory.retriever import MemoryRetriever

    with app_session_scope():
        digest_manager = a._get_service(DigestManager)
        retriever = MemoryRetriever(digest_manager=digest_manager)
        results = retriever.retrieve(
            query, owner_key, RetrievalOptions(top_k=5, budget_tokens=0)
        )
    lines = [
        str(getattr(item, "content", "") or "").strip()[:600]
        for item in (results or [])[:5]
    ]
    return "\n".join(line for line in lines if line)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/memory/test_admin_memory_recall.py -q --no-cov -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/memory/admin_memory_recall.py api/test/internal/service/memory/test_admin_memory_recall.py
git commit -m "feat(memory): add admin/agent subject memory recall"
```

---

## Task 2: `MemoryWriteService` 增加 owner 入口

**Files:**
- Modify: `api/internal/service/memory/memory_write_service.py`
- Test: `api/test/internal/service/memory/test_memory_write_service_owner.py`

**背景**：`write_from_conversation(account, ...)` 把 owner 写死为 `str(account.id)`；三层决策后调 `ledger_writer.write_full_path(...)` 也**未传** `owner_key`——这正是 P3c-1 断链点。本任务加 owner 透传，**不改变**用户端既有签名。

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/service/memory/test_memory_write_service_owner.py`：

```python
"""记忆写入的 owner 透传（ADMIN-P3c-2）。

不变量：
1. 传入 owner_key 时，三层决策后的 ledger_writer 调用必须带上它（否则 admin
   写路径退化成 for_user / 空主体——P3c-1 的断链点）；
2. 不传 owner_key 时（用户端既有路径）行为不变。
"""
from uuid import uuid4

import pytest

from internal.entity.memory_owner_entity import MemoryOwnerKey


class _SpyLedger:
    def __init__(self):
        self.calls = []

    def write_full_path(self, **kw):
        self.calls.append(("full", kw))
        return {"status": "full"}

    def write_summary_path(self, **kw):
        self.calls.append(("summary", kw))
        return {"status": "summary"}

    def write_stats_path(self, **kw):
        self.calls.append(("stats", kw))
        return {"status": "stats"}


def _service(monkeypatch, ledger):
    from internal.service.memory.memory_write_service import MemoryWriteService

    svc = MemoryWriteService.__new__(MemoryWriteService)
    svc.ledger_writer = ledger

    # 三层决策全部短路到 FULL，聚焦 owner 透传
    class _Det:
        is_explicit = False
        category = None
        polarity = None
        confidence = 0.0
        fallback_used = False
        subject = None

    class _Resolved:
        conflict_detected = False
        conflict_type = None
        resolved_count = 0
        superseded_ids = []

    class _Salience:
        write_path = type("W", (), {"value": "full"})()

        class _P:
            value = "full"

        total_score = 0.9

        def __init__(self):
            self.write_path = type("W", (), {"value": "full"})()

    svc.explicit_detector = type("D", (), {"detect": lambda self, e: _Det()})()
    svc.conflict_resolver = type("R", (), {"resolve": lambda self, e, d: _Resolved()})()
    svc.salience_scorer = type(
        "S", (), {"score": lambda self, e, explicitness: _Salience()}
    )()
    svc.entity_extractor = type(
        "E",
        (),
        {
            "extract_entities_and_relations": lambda self, c, max_entities=None: ([], []),
            "generate_summary": lambda self, c: "",
        },
    )()
    svc.embeddings_service = type(
        "M", (), {"embeddings": type("X", (), {"embed_query": lambda self, t: [0.1]})()}
    )()
    return svc


def test_write_from_event_passes_owner_key(monkeypatch):
    from internal.config.memory_settings import settings
    from internal.model.memory_models import EventSource, MemoryEvent

    monkeypatch.setattr(settings, "memory_engine_enabled", True, raising=False)
    ledger = _SpyLedger()
    svc = _service(monkeypatch, ledger)
    admin_id = uuid4()
    event = MemoryEvent(
        content="内容", source=EventSource.SYSTEM_OBSERVATION, user_id="ignored"
    )

    svc.write_from_event(event, owner_key=MemoryOwnerKey.for_admin(admin_id))

    assert ledger.calls, "必须下推到 ledger_writer"
    _kind, kw = ledger.calls[0]
    assert kw["owner_key"] == MemoryOwnerKey.for_admin(admin_id)


def test_write_from_event_without_owner_key_keeps_legacy(monkeypatch):
    from internal.config.memory_settings import settings
    from internal.model.memory_models import EventSource, MemoryEvent

    monkeypatch.setattr(settings, "memory_engine_enabled", True, raising=False)
    ledger = _SpyLedger()
    svc = _service(monkeypatch, ledger)
    event = MemoryEvent(
        content="内容", source=EventSource.USER_MESSAGE, user_id=str(uuid4())
    )

    svc.write_from_event(event)

    _kind, kw = ledger.calls[0]
    assert kw.get("owner_key") is None, "用户端既有路径不得被强行注入 admin 键"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/memory/test_memory_write_service_owner.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（`write_from_event() got an unexpected keyword argument 'owner_key'`）

- [ ] **Step 3: 加 owner 透传**

修改 `api/internal/service/memory/memory_write_service.py`：

1. `write_from_event` 签名加 `owner_key: Optional[MemoryOwnerKey] = None`（放在 `event` 之后），并把 `owner_key` 透传给三个 `_write_*`；
2. `_write_full` / `_write_summary` / `_write_sketch` 各加 `owner_key` 参数，调用 `self.ledger_writer.write_*(..., owner_key=owner_key)`；
3. 头部 import `MemoryOwnerKey`（`from internal.entity.memory_owner_entity import MemoryOwnerKey`）；
4. 新增便捷入口（供 admin 对话调用）：

```python
    def write_admin_conversation(
        self,
        *,
        admin_user_id,
        agent_id=None,
        query: str,
        ai_response: str,
        conversation_id: str,
    ) -> Optional[dict[str, Any]]:
        """admin / Agent 对话后写入记忆（主体为 admin，非 account）。

        与 ``write_from_conversation`` 同策，仅主体键不同——admin 没有 account，
        不能走 ``for_user``。
        """
        if not settings.memory_engine_enabled:
            logger.warning("记忆引擎已禁用（memory_engine_enabled=False），跳过写入")
            return None
        if not query or not ai_response:
            return None

        from internal.entity.memory_owner_entity import MemoryOwnerKey

        owner_key = MemoryOwnerKey.for_admin(admin_user_id, agent_id=agent_id)
        event = MemoryEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            source=EventSource.SYSTEM_OBSERVATION,
            content=f"Admin: {query}\nAgent: {ai_response}",
            context_messages=[],
            metadata={"query": query, "conversation_id": conversation_id},
            session_id=str(conversation_id),
            user_id=owner_key.to_key(),
        )
        return self.write_from_event(event, owner_key=owner_key)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/memory/test_memory_write_service_owner.py test/internal/service/memory/ -q --no-cov -p no:cacheprovider`
Expected: PASS（含既有 memory 测试，证明用户端未回归）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/memory/memory_write_service.py api/test/internal/service/memory/test_memory_write_service_owner.py
git commit -m "feat(memory): thread owner_key through memory write service"
```

---

## Task 3: `AdminAgentChatService` 接线（先召回、后写入）

**Files:**
- Modify: `api/internal/service/admin_agent_chat_service.py`
- Test: `api/test/internal/service/test_admin_agent_chat_service.py`（追加）

**背景**：这是本计划的核心接线。镜像用户端顺序——**先召回注入提示词，答后异步写入**。两个调用点必须是**可替换的薄方法**（便于单测隔离），且**自身吞错**，绝不让记忆失败影响对话。

- [ ] **Step 1: 写失败的测试**

在 `api/test/internal/service/test_admin_agent_chat_service.py` 末尾追加：

```python
def test_chat_injects_admin_memory_into_system_prompt(monkeypatch):
    """召回文本必须进入 system prompt（否则读路径等于没接）。"""
    llm = _FakeLLM([SimpleNamespace(content="好的。", tool_calls=[])])
    service = _service(_principal(), llm, [])
    captured = {}

    def _fake_build_prompt(p, prompt_key, *, memory_text=""):
        captured["memory_text"] = memory_text
        return "系统提示词"

    service._build_system_prompt = _fake_build_prompt
    service._recall_memory = lambda **kw: "管理员上次说过：偏好简洁"

    list(
        service.chat(
            agent_id=uuid4(),
            admin_user_id=uuid4(),
            admin_permissions=["builtin_tool:read"],
            query="你好",
        )
    )

    assert "偏好简洁" in captured["memory_text"], "召回文本必须注入提示词"


def test_chat_writes_admin_memory_after_answer(monkeypatch):
    llm = _FakeLLM([SimpleNamespace(content="回答内容", tool_calls=[])])
    service = _service(_principal(), llm, [])
    captured = {}

    def _fake_write(**kw):
        captured.update(kw)

    service._recall_memory = lambda **kw: ""
    service._write_memory = _fake_write

    list(
        service.chat(
            agent_id=uuid4(),
            admin_user_id=uuid4(),
            admin_permissions=["builtin_tool:read"],
            query="记住我偏好简洁",
        )
    )

    assert captured.get("query") == "记住我偏好简洁"
    assert captured.get("ai_response") == "回答内容"


def test_memory_recall_failure_does_not_break_chat(monkeypatch):
    """召回失败必须不影响对话（fail-open）。"""
    llm = _FakeLLM([SimpleNamespace(content="正常回答", tool_calls=[])])
    service = _service(_principal(), llm, [])

    def _boom(**kwargs):
        raise RuntimeError("memory down")

    service._recall_memory = _boom

    frames = list(
        service.chat(
            agent_id=uuid4(),
            admin_user_id=uuid4(),
            admin_permissions=["builtin_tool:read"],
            query="你好",
        )
    )

    body = "".join(frames)
    assert "event: answer" in body
    assert "正常回答" in body


def test_memory_write_failure_does_not_break_chat(monkeypatch):
    llm = _FakeLLM([SimpleNamespace(content="正常回答", tool_calls=[])])
    service = _service(_principal(), llm, [])

    def _boom(**kwargs):
        raise RuntimeError("write down")

    service._recall_memory = lambda **kw: ""
    service._write_memory = _boom

    frames = list(
        service.chat(
            agent_id=uuid4(),
            admin_user_id=uuid4(),
            admin_permissions=["builtin_tool:read"],
            query="你好",
        )
    )

    body = "".join(frames)
    assert "event: answer" in body
    assert "event: end" in body
```

> **注意**：既有 `_service()` 替身替换了 `_build_system_prompt`，签名是
> `lambda p, prompt_key: ...`。为避免破坏既有 8 个用例，实现里
> `_build_system_prompt` 的 `memory_text` 必须是**带默认值的关键字参数**，
> 且既有测试的 2 参 lambda 调用方式不变——因此 `chat()` 必须用
> `self._build_system_prompt(principal, prompt_key, memory_text=...)` 调用，
> 既有替身因不接受 kwargs 会失败。**故需同步把既有 `_service()` 替身与
> `test_resume_rejects_conversation_of_another_agent` 里的
> `_build_system_prompt` lambda 改为 `lambda p, prompt_key, memory_text="": "系统提示词"`。**

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_admin_agent_chat_service.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（`_recall_memory` 属性不存在）

- [ ] **Step 3: 接线实现**

修改 `api/internal/service/admin_agent_chat_service.py`：

1. `chat()` 中，`agent = self._load_agent(...)` 之后、`_build_system_prompt` 之前插入召回：

```python
            # 记忆读回（ADMIN-P3c-2）：admin/Agent 主体召回，fail-open。
            # 召回复用的是 P3b 已主体化的读路径（retriever/digest），此处只构造
            # admin 主体键并注入提示词；失败返回空串，绝不阻断对话。
            memory_text = self._recall_memory(
                admin_user_id=principal.admin_user_id,
                agent_id=principal.agent_id,
                query=text,
                conversation_id=str(conversation.id),
            )
            system_prompt = self._build_system_prompt(
                principal, getattr(agent, "prompt_key", None), memory_text=memory_text
            )
```

2. 在 `yield self._frame(AdminAgentChatEvent.ANSWER, ...)` **之前**（即 `append_message(assistant)` 之后）加写入：

```python
        # 对话后写入记忆（ADMIN-P3c-2）：异步、吞错，不影响已产出的答复。
        self._write_memory(
            admin_user_id=principal.admin_user_id,
            agent_id=principal.agent_id,
            query=text,
            ai_response=answer,
            conversation_id=str(conversation.id),
        )
```

3. 新增两个可替换薄方法（放在 `_build_system_prompt` 附近）：

```python
    def _recall_memory(
        self, *, admin_user_id, agent_id, query: str, conversation_id: str
    ) -> str:
        """召回 admin/Agent 主体记忆（fail-open：任何异常返回空串）。"""
        try:
            from internal.service.memory.admin_memory_recall import (
                recall_admin_agent_memory_for_chat,
            )

            return recall_admin_agent_memory_for_chat(
                admin_user_id=admin_user_id,
                agent_id=agent_id,
                query=query,
                conversation_id=conversation_id,
            )
        except Exception:
            logger.warning("管理端 Agent 记忆召回失败，静默降级", exc_info=True)
            return ""

    def _write_memory(
        self, *, admin_user_id, agent_id, query: str, ai_response: str, conversation_id: str
    ) -> None:
        """对话后写入 admin/Agent 主体记忆（后台线程 + 吞错）。"""
        if not ai_response:
            return
        try:
            from internal.config.memory_settings import settings as memory_settings

            if not memory_settings.memory_engine_enabled:
                return

            def _bg_write() -> None:
                from internal.lib.runtime_context import app_session_scope

                with app_session_scope():
                    try:
                        from app.http.app import injector
                        from internal.service.memory.memory_write_service import (
                            MemoryWriteService,
                        )

                        injector.get(MemoryWriteService).write_admin_conversation(
                            admin_user_id=admin_user_id,
                            agent_id=agent_id,
                            query=query,
                            ai_response=ai_response,
                            conversation_id=conversation_id,
                        )
                    except Exception:
                        logger.warning("管理端 Agent 记忆写入失败", exc_info=True)

            from threading import Thread

            Thread(target=_bg_write, daemon=True).start()
        except Exception:
            logger.warning("管理端 Agent 记忆写入调度失败", exc_info=True)
```

4. `_build_system_prompt` 增加 `memory_text` 参数并注入提示词：

```python
    def _build_system_prompt(
        self, principal: AdminAgentPrincipal, prompt_key, *, memory_text: str = ""
    ) -> str:
        from internal.service.admin_agent_prompt_service import AdminAgentPromptService

        prompt = AdminAgentPromptService().build_system_prompt(
            principal, prompt_key=prompt_key
        )
        if memory_text:
            prompt = f"{prompt}\n\n## 你记得的相关信息\n{memory_text}"
        return prompt
```

5. 同步更新既有测试替身（见 Step 1 注记）。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_admin_agent_chat_service.py -q --no-cov -p no:cacheprovider`
Expected: PASS（新增 4 个 + 既有 9 个）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/admin_agent_chat_service.py api/test/internal/service/test_admin_agent_chat_service.py
git commit -m "feat(admin-agent): wire admin/agent memory recall and write into chat"
```

---

## Task 4: `MemoryGovernor` 治理主体化

**Files:**
- Modify: `api/internal/service/memory/memory_governor.py`
- Test: `api/test/internal/service/memory/test_memory_governor_owner_scope.py`

**背景**：`_verify_owner` 只读 `n.user_id`（admin 恒 False）；`_delete_all_pgvector_rows` 只比 `owner_account_id`（admin 漏删）。P3c-1 修复缺口二后 admin 行可落库，漏删已从「无害 fail-safe」升级为「admin 记忆无法被 GDPR 删除」。

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/service/memory/test_memory_governor_owner_scope.py`：

```python
"""治理层主体化（ADMIN-P3c-2）。

不变量：
1. `_verify_owner` 必须按主体属性判定（admin 不得恒 False）；
2. `_delete_all_pgvector_rows` 必须带 owner_type 谓词（否则 admin 行漏删）。
"""
from uuid import uuid4

import pytest

from internal.entity.memory_owner_entity import MemoryOwnerKey
from internal.service.memory.memory_governor import MemoryGovernor


class _Session:
    def __init__(self, sink):
        self._sink = sink

    def run(self, cypher, params=None, **kwargs):
        self._sink.append((cypher, params or kwargs))
        return self

    def single(self):
        return None

    def consume(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Driver:
    def __init__(self):
        self.calls = []

    def session(self):
        return _Session(self.calls)


def test_verify_owner_admin_uses_admin_props(monkeypatch):
    """admin 主体：校验谓词必须含 admin_user_id，而非只读 user_id。"""
    driver = _Driver()
    gov = MemoryGovernor.__new__(MemoryGovernor)

    gov._verify_owner("m-1", MemoryOwnerKey.for_admin(uuid4()).to_key(), driver)

    cypher, params = driver.calls[0]
    assert "admin_user_id" in cypher
    assert params.get("admin_user_id") is not None


def test_verify_owner_user_unchanged(monkeypatch):
    driver = _Driver()
    gov = MemoryGovernor.__new__(MemoryGovernor)
    account_id = uuid4()

    gov._verify_owner("m-1", MemoryOwnerKey.for_user(account_id).to_key(), driver)

    _cypher, params = driver.calls[0]
    assert params.get("user_id") == str(account_id)


def test_delete_all_pgvector_rows_filters_owner_type():
    """删除必须带 owner_type 谓词（admin 行 owner_account_id 为 NULL）。"""
    gov = MemoryGovernor.__new__(MemoryGovernor)
    captured = {}

    class _Q:
        def filter(self, *conds):
            captured["conds"] = [str(c) for c in conds]
            return self

        def delete(self):
            return 3

    class _S:
        def query(self, *a, **k):
            return _Q()

        def commit(self):
            pass

    gov._get_db = lambda: type("D", (), {"session": _S()})()

    gov._delete_all_pgvector_rows(MemoryOwnerKey.for_admin(uuid4()).to_key())

    rendered = " ".join(captured["conds"])
    assert "owner_type" in rendered
    assert "owner_admin_user_id" in rendered
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/memory/test_memory_governor_owner_scope.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（cypher 里无 `admin_user_id`；删除无条件）

- [ ] **Step 3: 主体化实现**

修改 `api/internal/service/memory/memory_governor.py`：

1. `_verify_owner` 改为按主体解析键后用访问器产谓词：

```python
    def _verify_owner(self, memory_id: str, owner_key: str, driver) -> bool:
        """验证记忆节点 owner 是否为指定主体（按主体类型取对应归属属性）。

        P3c-2：用户态取 ``n.user_id``；admin 态取 ``n.admin_user_id``
        （+ ``agent_id`` 哨兵/真实 UUID）。不再对 admin 恒返回 False。
        """
        from internal.entity.memory_owner_entity import MemoryOwnerKey

        try:
            owner = MemoryOwnerKey.parse(owner_key)
        except Exception:
            logger.warning("_verify_owner: 主体键非法 owner=%s", owner_key)
            return False

        try:
            where = owner.neo4j_filter_condition("n")
            with driver.session() as session:
                result = session.run(
                    f"""
                    MATCH (n) WHERE (n:MemoryNode OR n:Episode OR n:Entity OR n:Community)
                      AND (n.node_id = $memory_id OR n.id = $memory_id)
                      AND {where}
                    RETURN count(n) AS c
                    """,
                    {"memory_id": memory_id, **owner.neo4j_props()},
                ).single()
                return bool(result and result.get("c"))
        except Exception:
            logger.warning("_verify_owner: 查询失败", exc_info=True)
            return False
```

2. `_delete_all_pgvector_rows` 改为主体谓词：

```python
    def _delete_all_pgvector_rows(self, owner_key: str) -> int:
        """删除主体全部 pgvector 行（按主体谓词，含 owner_type）。"""
        from internal.entity.memory_owner_entity import MemoryOwnerKey
        from internal.model.knowledge import UserMemory

        db = self._get_db()
        if db is None:
            return 0
        try:
            owner = MemoryOwnerKey.parse(owner_key)
            conditions = owner.pg_filter_conditions(UserMemory)
            count = (
                db.session.query(UserMemory).filter(*conditions).delete()
            )
            db.session.commit()
            return count
        except Exception:
            logger.warning(
                "_delete_all_pgvector_rows: 删除失败 owner=%s", owner_key, exc_info=True
            )
            return 0
```

3. `gdpr_delete` 的 Neo4j 侧改用主体谓词（原 `MATCH (u:User {id: $owner_key})`）：

```python
                owner = MemoryOwnerKey.parse(owner_key)
                props = owner.neo4j_props()
                where = owner.neo4j_filter_condition("n")
                with driver.session() as session:
                    result = session.run(
                        f"""
                        MATCH (n) WHERE {where}
                        OPTIONAL MATCH (n)-[r]-(m)
                        WITH collect(DISTINCT n) AS nodes, collect(DISTINCT r) AS rels
                        FOREACH (x IN nodes | DETACH DELETE x)
                        RETURN size(nodes) AS node_count, size(rels) AS edge_count
                        """,
                        {"owner_key": owner_key, **props},
                    ).single()
                    ...
```

> **诚实披露要求**：admin 主体在 Neo4j 的 `agent_id` 管理员级写的是哨兵
> `"__admin_level__"`，`neo4j_props()` 已正确产出，故谓词天然命中两类。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/memory/ -q --no-cov -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/memory/memory_governor.py api/test/internal/service/memory/test_memory_governor_owner_scope.py
git commit -m "feat(memory): subjectize governor verify/delete for admin owners"
```

---

## Task 5: 接线审查 + 全量回归

**Files:**（无代码改动，仅验证）

- [ ] **Step 1: 逐个新符号点名入口**

| 新符号 | 必须存在的入口 | 复核方式 |
| --- | --- | --- |
| `recall_admin_agent_memory_for_chat` | `AdminAgentChatService._recall_memory` | `test_chat_injects_admin_memory_into_system_prompt` |
| `MemoryWriteService.write_admin_conversation` | `AdminAgentChatService._write_memory` | `test_chat_writes_admin_memory_after_answer` |
| `write_from_event(owner_key=)` | `write_admin_conversation` + 三个 `_write_*` | `test_write_from_event_passes_owner_key` |
| `LedgerWriter.write_*(owner_key=)`（P3c-1 遗留断链） | `MemoryWriteService._write_*` | Task 2 单测 |
| `_verify_owner` / `_delete_all_pgvector_rows` 主体化 | `edit_memory` / `gdpr_delete` | Task 4 单测 |

- [ ] **Step 2: 全仓搜索新符号的调用方（排除测试）**

```bash
cd d:/DEMO/openagent-main
grep -rn "recall_admin_agent_memory_for_chat\|write_admin_conversation" --include=*.py api/ | grep -v "/test/"
```

Expected: 每个符号都能在非测试代码中找到「定义处 + 调用处」。只命中定义处即为断链。

- [ ] **Step 3: 全量回归**

Run: `cd api && python -m pytest -q --no-header --no-cov 2>&1 | Select-String -Pattern "passed|failed" | Select-Object -Last 3`
Expected: 全部通过（既有环境性失败需逐条确认与本改动无关）

- [ ] **Step 4: 真机验证（可选但推荐）**

```bash
docker exec -w /app/api -e PYTHONPATH=/app/api llmops-api sh -c "python -m pytest test/internal/service/memory/ test/internal/service/test_admin_agent_chat_service.py -q --no-cov | tail -3"
```

- [ ] **Step 5: 提交（若有文档更新）**

```bash
git add docs/
git commit -m "docs(memory): record admin p3c-2 chat memory wiring"
```

---

## Task 6: 文档同步

**Files:**
- Modify: `docs/prd/memory-system/02-storage-and-retrieval.md`
- Modify: `docs/prd/execution-roadmap.md`

- [ ] **Step 1: 关闭缺口九**

「缺口九：`_verify_owner` / `edit_memory` / `gdpr_delete` 的 Neo4j 侧仅支持用户主体」改为「（已修复，ADMIN-P3c-2）」，写明改走 `neo4j_filter_condition`。

- [ ] **Step 2: 关闭缺口十六**

「缺口十六：`_delete_all_pgvector_rows` 仅按 `owner_account_id` 过滤」改为「（已修复，ADMIN-P3c-2）」，写明改走 `pg_filter_conditions`（含 `owner_type`）。

- [ ] **Step 3: 更新 roadmap**

补一节「ADMIN-P3c-2」交付物与验证；缺口计数相应下调；并更正 P3c-1 节里「仍无生产调用方」的披露——本阶段后 admin 记忆**已端到端可达**。

- [ ] **Step 4: 提交**

```bash
git add docs/
git commit -m "docs(memory): record admin p3c-2 chat memory wiring"
```

---

## 自检清单（执行者收尾逐项打勾）

- [ ] 用户端 `recall_user_memory_for_chat` / `write_from_conversation(account, ...)` **签名与行为未变**
- [ ] admin 主体键是 `for_admin(...)`（含 agent 时三级），**绝不** `for_user`
- [ ] 召回与写入均 **fail-open / 吞错**，记忆失败不影响对话产出 answer
- [ ] `_build_system_prompt` 的 `memory_text` 为带默认值的关键字参数，既有测试替身已同步更新
- [ ] 写入在**后台线程 + app_session_scope**（防 idle in transaction 泄漏）
- [ ] 治理层谓词用访问器（`neo4j_filter_condition` / `pg_filter_conditions`），无手写死 `user_id`
- [ ] admin 态 `_verify_owner` 不再恒 False
- [ ] 全仓搜索新符号有真实调用方（非仅定义处）
- [ ] 全量回归通过
- [ ] 文档缺口九、十六已关闭；roadmap 记录了 P3c-2
- [ ] 运行 `python -m graphify update .`

---

## 附：与后续阶段的边界

| 阶段 | 范围 | 本阶段是否覆盖 |
| --- | --- | --- |
| **P3c-2（本计划）** | admin 对话记忆**读写接线** + 治理层主体化（缺口九/十六） | ✅ |
| P3c-3 | 配置与存储：`DigestConfig` 死副本（C2）、`ColdStorageManager.list_user_archives`（C4）、冷存储主体化、Redis 键分隔约定（缺口十）、巩固任务 admin 主体（ADMIN-P4 `schedule_task.agent_id`） | ❌ 另写 |
