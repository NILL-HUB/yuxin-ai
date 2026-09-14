# 知识库产品形态 P2B · 大文件分片上传 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 解除单文件 15MB 上限，让用户可上传 GB 级视频素材：分片上传 + 秒传 + 断点续传，且服务端全程流式处理不把整文件读进内存。

**Architecture:** 新增「分片上传编排服务」：前端按固定大小切分并并发上传分片 → 服务端把分片暂存到共享磁盘（`storage/chunks/{session_id}/`）、会话状态存 Redis（API 有 2 个 uvicorn worker，必须共享状态）→ 完成后由服务端**流式合并**为最终对象、**增量计算 sha3_256**、调用既有 `UploadFileService.create_upload_file` 落库（复用配额与 UploadFile 记录）→ 知识库服务据此创建 `KnowledgeDocument` 并触发索引。秒传用「文件大小 + 抽样分片哈希」的轻量指纹按账号去重。

**Tech Stack:** Python 3.11+ / Quart / SQLAlchemy 2.0 / injector DI / Redis / Vue 3 + TypeScript（复用既有 XHR `upload()`）

**上游设计:** [knowledge-base-product-form-design.md](../../prd/knowledge-base-product-form-design.md) §八缺陷 2、§九 P2B、§十一待确认 5
**前置依赖:** P1（配额服务 `StorageQuotaService`、`PlanEntitlement` 权益机制、`UploadFile.size` 已为 BigInteger）、P2A（`upload_document` 媒体类型识别与索引分支）
**显式不含（后置 P2B-2）:** `cos` / `oss` 后端的原生 multipart 适配（需对接各云厂商分片 API，属独立集成）；本次分片仅支持 `local` 后端，其他后端在 init 时明确报错。

**已核实的部署事实（决定设计）**
- API 以 `ASGI_WORKER_AMOUNT=2` 跑 2 个 uvicorn worker → **分片会话状态不能放进程内存**，用 Redis
- `docker/docker-compose.yaml` 挂载 `./volumes/app/storage:/app/api/storage` → **共享磁盘**，分片文件跨 worker 可见
- Redis 封装：`from internal.extension.redis_extension import redis_client`（模块级单例，`decode_responses=False`，取值是 bytes）
- `local_storage_service` 的 `upload_file` 会 `file.stream.read()` **全量读入内存**并 `sha3_256` 全量哈希 → 大文件必须绕开此路径
- 前端 HTTP 层是 fetch（无进度）；但已有 XHR 版 `upload()`（`ui/src/utils/request.ts:576`），暴露 `onprogress`
- 知识库默认后端 `local`（`config.py` 的 `STORAGE_BACKEND` 默认 `local`）

---

## 文件结构

### 新增文件

| 文件 | 职责 |
|---|---|
| `api/internal/service/chunked_upload_session_service.py` | 分片会话状态（Redis）：init / get / mark_received / abort / 秒传指纹索引 |
| `api/internal/service/chunked_upload_service.py` | 分片上传编排：存分片、流式合并、落库、秒传判定 |
| `api/internal/schema/chunked_upload_schema.py` | 分片上传的请求/响应 schema |
| `api/app/http/chunked_upload_routes.py` | 分片上传 HTTP 路由（init / chunk / status / complete / abort） |
| `api/test/internal/service/test_chunked_upload_session_service.py` | 会话服务单测 |
| `api/test/internal/service/test_chunked_upload_service.py` | 编排服务单测 |
| `api/test/app/http/test_chunked_upload_routes.py` | 路由单测 |
| `ui/src/services/chunked-upload.ts` | 前端分片上传（切分/并发/进度/断点续传/秒传） |

### 修改文件

| 文件 | 改动 |
|---|---|
| `api/internal/entity/storage_quota_entity.py` | 新增 `MAX_SINGLE_FILE_FEATURE_KEY` / `DEFAULT_MAX_SINGLE_FILE_BYTES` |
| `api/internal/service/storage_quota_service.py` | 新增 `resolve_max_file_size_bytes(account_id)`；`_resolve_active_plan_quota_gb` 泛化为 `_resolve_entitlement_gb(feature_key)` |
| `api/internal/service/storage/local_storage_service.py` | 新增 `save_chunk` / `merge_chunks`（流式合并 + 增量哈希）；新增 `copy_object`（秒传服务端复制）；新增 `_get_chunk_upload_root` |
| `api/internal/schema/upload_file_schema.py` | 移除 15MB 硬编码，改为"绝对防滥用上限"（大文件走分片链路） |
| `api/app/http/asgi_app.py` | 注册 `chunked_upload_routes` |
| `api/internal/service/knowledge_base_service.py` | 新增按 `upload_file_id` 创建文档的入口，供分片完成后调用 |
| `ui/src/views/space/datasets/documents/ListView.vue` | 上传改走分片（大文件）/ 单次（小文件）分流 + 进度展示 |
| `ui/src/hooks/use-knowledge-base.ts` | 新增分片上传 hook（进度/断点续传） |

---

## Task 1: 单文件上限配置化与套餐分级

**Files:**
- Modify: `api/internal/entity/storage_quota_entity.py`
- Modify: `api/internal/service/storage_quota_service.py`
- Test: `api/test/internal/service/test_storage_quota_service.py` (append)

- [ ] **Step 1: Write the failing test**

在 `api/test/internal/service/test_storage_quota_service.py` 末尾追加（沿用该文件既有的 `_new_service` / `_QueryStub` / `_SessionStub` / `_fake_entitlement` 工具）：

```python
def test_max_file_size_falls_back_to_default_when_no_entitlement():
    service = _new_service(_SessionStub([_QueryStub(first_result=None), _QueryStub(all_result=[])]))
    assert service.resolve_max_file_size_bytes(uuid4()) == 15 * 1024 * 1024


def test_max_file_size_uses_plan_entitlement():
    plan_id = uuid4()
    membership = SimpleNamespace(plan_id=plan_id)
    entitlement = _fake_entitlement(1024)
    service = _new_service(_SessionStub([
        _QueryStub(first_result=membership),
        _QueryStub(all_result=[entitlement]),
        _QueryStub(all_result=[]),
    ]))
    assert service.resolve_max_file_size_bytes(uuid4()) == 1024 * (1024 ** 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_storage_quota_service.py -v --no-cov`
Expected: FAIL with `AttributeError: 'StorageQuotaService' object has no attribute 'resolve_max_file_size_bytes'`

- [ ] **Step 3: Write minimal implementation**

`api/internal/entity/storage_quota_entity.py` 追加常量：

```python
# 套餐权益中承载「单文件上传上限（GB）」的 feature_key
MAX_SINGLE_FILE_FEATURE_KEY = "max_single_file_gb"

# 无套餐权益时的单文件上限（字节）：默认 15MB，与历史行为一致
DEFAULT_MAX_SINGLE_FILE_BYTES = 15 * 1024 * 1024
```

`api/internal/service/storage_quota_service.py`：import 区补 `DEFAULT_MAX_SINGLE_FILE_BYTES`、`MAX_SINGLE_FILE_FEATURE_KEY`；新增方法（放在 `resolve_total_quota_bytes` 之后）：

```python
    def resolve_max_file_size_bytes(self, account_id: UUID) -> int:
        """解析账号的单文件上传上限（字节）。

        取「生效套餐的 max_single_file_gb 权益」，无权益时回退默认 15MB。
        大文件分片上传单分片不受此限制，本上限约束的是单次上传的总字节数。
        """
        plan_quota_gb = self._resolve_entitlement_gb(account_id, MAX_SINGLE_FILE_FEATURE_KEY)
        if plan_quota_gb > 0:
            return plan_quota_gb * BYTES_PER_GB
        return DEFAULT_MAX_SINGLE_FILE_BYTES
```

并把既有 `_resolve_active_plan_quota_gb` 泛化为可指定 feature_key 的 `_resolve_entitlement_gb`（保留旧方法名或直接替换调用点，二选一，保持 `resolve_total_quota_bytes` 行为不变）：

```python
    def _resolve_entitlement_gb(self, account_id: UUID, feature_key: str) -> int:
        """取当前生效会员套餐指定权益的整数值；无生效套餐返回 0。"""
        now = datetime.now(UTC).replace(tzinfo=None)
        membership = (
            self.db.session.query(Membership)
            .filter(
                Membership.account_id == account_id,
                Membership.status == "active",
                Membership.expires_at >= now,
            )
            .order_by(Membership.expires_at.desc())
            .first()
        )
        if membership is None:
            return 0
        entitlements = (
            self.db.session.query(PlanEntitlement)
            .filter_by(plan_id=membership.plan_id, feature_key=feature_key)
            .all()
        )
        if not entitlements:
            return 0
        return self._entitlement_gb(entitlements[0])
```

**注意**：`resolve_total_quota_bytes` 中原先调用 `_resolve_active_plan_quota_gb(account_id)` 的位置改为 `_resolve_entitlement_gb(account_id, STORAGE_QUOTA_FEATURE_KEY)`，删除旧私有方法（避免双份实现）。既有 4 个配额测试必须仍然通过。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/service/test_storage_quota_service.py -v --no-cov`
Expected: PASS（既有 12 + 新增 2 = 14 passed）

- [ ] **Step 5: Commit**

```bash
git add api/internal/entity/storage_quota_entity.py api/internal/service/storage_quota_service.py api/test/internal/service/test_storage_quota_service.py
git commit -m "feat(storage): make single file size limit plan-aware"
```

---

## Task 2: 分片会话状态服务（Redis）

**Files:**
- Create: `api/internal/service/chunked_upload_session_service.py`
- Test: `api/test/internal/service/test_chunked_upload_session_service.py`

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/service/test_chunked_upload_session_service.py
import json
from types import SimpleNamespace
from uuid import uuid4

from internal.service.chunked_upload_session_service import (
    ChunkedUploadSession,
    ChunkedUploadSessionService,
)


class _FakeRedis:
    """最小 Redis 桩：仅实现本服务用到的命令。"""

    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.expires: dict[str, int] = {}

    def setex(self, key, ttl, value):
        self.store[key] = value if isinstance(value, bytes) else str(value).encode()
        self.expires[key] = int(ttl)

    def get(self, key):
        return self.store.get(key)

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)
            self.expires.pop(key, None)

    def exists(self, key):
        return 1 if key in self.store else 0


def _service(redis=None):
    return ChunkedUploadSessionService(redis=redis or _FakeRedis())


def _session_kwargs(**overrides):
    base = dict(
        session_id=str(uuid4()),
        account_id=str(uuid4()),
        filename="promo.mp4",
        total_size=20 * 1024 * 1024,
        chunk_size=5 * 1024 * 1024,
        total_chunks=4,
        fingerprint="abc123",
    )
    base.update(overrides)
    return base


def test_create_session_persists_state_and_returns_model():
    service = _service()
    session = service.create(**_session_kwargs())

    assert isinstance(session, ChunkedUploadSession)
    assert session.total_chunks == 4
    assert session.received_chunks == []

    loaded = service.get(session.session_id)
    assert loaded is not None
    assert loaded.filename == "promo.mp4"
    assert loaded.fingerprint == "abc123"


def test_create_session_sets_ttl():
    redis = _FakeRedis()
    service = _service(redis)
    session = service.create(**_session_kwargs())

    key = service._key(session.session_id)
    assert redis.expires[key] == 86400


def test_get_returns_none_for_unknown_session():
    assert _service().get("missing-session") is None


def test_mark_received_is_idempotent_and_ordered():
    service = _service()
    session = service.create(**_session_kwargs())

    service.mark_received(session.session_id, 0)
    service.mark_received(session.session_id, 1)
    service.mark_received(session.session_id, 1)

    loaded = service.get(session.session_id)
    assert loaded is not None
    assert loaded.received_chunks == [0, 1]
    assert loaded.is_complete is False


def test_mark_received_marks_complete_when_all_present():
    service = _service()
    session = service.create(**_session_kwargs(total_chunks=2, total_size=10 * 1024 * 1024))

    service.mark_received(session.session_id, 0)
    service.mark_received(session.session_id, 1)

    loaded = service.get(session.session_id)
    assert loaded is not None
    assert loaded.is_complete is True


def test_missing_chunks_reports_pending_indices():
    service = _service()
    session = service.create(**_session_kwargs(total_chunks=4))

    service.mark_received(session.session_id, 0)
    service.mark_received(session.session_id, 3)

    assert service.missing_chunks(session.session_id) == [1, 2]


def test_abort_removes_session():
    service = _service()
    session = service.create(**_session_kwargs())

    service.abort(session.session_id)

    assert service.get(session.session_id) is None


def test_register_and_lookup_fingerprint():
    service = _service()
    account_id = str(uuid4())
    upload_file_id = str(uuid4())

    service.register_fingerprint(account_id, "fp-1", upload_file_id)

    assert service.lookup_fingerprint(account_id, "fp-1") == upload_file_id
    assert service.lookup_fingerprint(account_id, "fp-unknown") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_chunked_upload_session_service.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'internal.service.chunked_upload_session_service'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/internal/service/chunked_upload_session_service.py
"""分片上传会话状态服务。

API 以多 uvicorn worker 运行，分片会话状态必须放在 Redis 而非进程内存。
本服务负责会话的创建、读取、分片登记、断点续传查询与销毁，
以及秒传指纹的登记与查询。
"""
import json
import logging
from dataclasses import asdict, dataclass, field
from uuid import uuid4

from injector import inject

from redis import Redis

logger = logging.getLogger(__name__)

# 会话与指纹的默认 TTL（秒）
_SESSION_TTL_SECONDS = 86400
_FINGERPRINT_TTL_SECONDS = 86400 * 7


@dataclass
class ChunkedUploadSession:
    """分片上传会话（可序列化到 Redis）。"""

    session_id: str
    account_id: str
    filename: str
    total_size: int
    chunk_size: int
    total_chunks: int
    fingerprint: str = ""
    received_chunks: list[int] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """所有分片都已收到。"""
        return len(self.received_chunks) >= self.total_chunks


@inject
@dataclass
class ChunkedUploadSessionService:
    """Redis 支撑的分片会话与秒传指纹管理。"""

    redis: Redis

    @staticmethod
    def _key(session_id: str) -> str:
        return f"chunked_upload:session:{session_id}"

    @staticmethod
    def _chunk_dir_key(session_id: str) -> str:
        return f"chunked_upload:dir:{session_id}"

    @staticmethod
    def _fingerprint_key(account_id: str, fingerprint: str) -> str:
        return f"chunked_upload:fingerprint:{account_id}:{fingerprint}"

    def create(
        self,
        *,
        account_id: str,
        filename: str,
        total_size: int,
        chunk_size: int,
        total_chunks: int,
        fingerprint: str = "",
        session_id: str | None = None,
    ) -> ChunkedUploadSession:
        """创建并持久化会话。"""
        session = ChunkedUploadSession(
            session_id=session_id or str(uuid4()),
            account_id=account_id,
            filename=filename,
            total_size=total_size,
            chunk_size=chunk_size,
            total_chunks=total_chunks,
            fingerprint=fingerprint,
        )
        self._save(session)
        return session

    def _save(self, session: ChunkedUploadSession) -> None:
        payload = json.dumps(asdict(session), ensure_ascii=False).encode("utf-8")
        self.redis.setex(self._key(session.session_id), _SESSION_TTL_SECONDS, payload)

    def get(self, session_id: str) -> ChunkedUploadSession | None:
        """读取会话；不存在或损坏时返回 None。"""
        raw = self.redis.get(self._key(session_id))
        if raw is None:
            return None
        try:
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            return ChunkedUploadSession(**data)
        except (ValueError, TypeError):
            logger.warning("分片会话数据损坏 session_id=%s", session_id, exc_info=True)
            return None

    def mark_received(self, session_id: str, index: int) -> ChunkedUploadSession | None:
        """登记某分片已收到（幂等）。"""
        session = self.get(session_id)
        if session is None:
            return None
        if index not in session.received_chunks:
            session.received_chunks.append(index)
            session.received_chunks.sort()
            self._save(session)
        return session

    def missing_chunks(self, session_id: str) -> list[int]:
        """返回尚未收到的分片下标（用于断点续传）。"""
        session = self.get(session_id)
        if session is None:
            return []
        received = set(session.received_chunks)
        return [index for index in range(session.total_chunks) if index not in received]

    def abort(self, session_id: str) -> None:
        """销毁会话（分片文件的清理由编排服务负责）。"""
        self.redis.delete(self._key(session_id))

    def register_fingerprint(self, account_id: str, fingerprint: str, upload_file_id: str) -> None:
        """登记秒传指纹 → UploadFile 映射（同账号有效）。"""
        if not fingerprint:
            return
        self.redis.setex(
            self._fingerprint_key(account_id, fingerprint),
            _FINGERPRINT_TTL_SECONDS,
            upload_file_id.encode("utf-8"),
        )

    def lookup_fingerprint(self, account_id: str, fingerprint: str) -> str | None:
        """按秒传指纹查同账号既有的 UploadFile id。"""
        if not fingerprint:
            return None
        raw = self.redis.get(self._fingerprint_key(account_id, fingerprint))
        if raw is None:
            return None
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
```

**注意**：Redis 类型注解用 `from redis import Redis`（与 `api/app/http/module.py:5` 的 `from redis import Redis` 及第 89 行 `binder.bind(Redis, to=redis_client, scope=singleton)` 一致）。**已核实**：仓库中**没有** `pkg.redis` 模块，Redis 客户端来自 `internal.extension.redis_extension.redis_client`。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/service/test_chunked_upload_session_service.py -v --no-cov`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/chunked_upload_session_service.py api/test/internal/service/test_chunked_upload_session_service.py
git commit -m "feat(storage): add redis-backed chunked upload session service"
```

---

## Task 3: local 后端分片存储能力（流式合并 + 增量哈希）

**Files:**
- Modify: `api/internal/service/storage/local_storage_service.py`
- Test: `api/test/internal/service/test_local_storage_chunks.py` (create)

**说明**：本任务是 P2B 的性能关键——**必须流式**，禁止把整个文件读进内存。合并时按分片顺序边读边写目标文件，同时增量更新 sha3_256。

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/service/test_local_storage_chunks.py
import hashlib
import os
from types import SimpleNamespace

import pytest

from internal.service.storage import local_storage_service as module
from internal.service.storage.local_storage_service import LocalStorageService


@pytest.fixture
def isolated_storage(monkeypatch, tmp_path):
    """把本地存储根与分片根都指向临时目录，避免污染真实 storage。"""
    upload_root = tmp_path / "uploads"
    chunk_root = tmp_path / "chunks"
    monkeypatch.setattr(module, "_get_local_storage_root", lambda: str(upload_root))
    monkeypatch.setattr(module, "_get_chunk_upload_root", lambda override=None: str(chunk_root))
    (upload_root / "2026" / "09" / "14").mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(upload_root=upload_root, chunk_root=chunk_root)


def _service():
    return LocalStorageService(upload_file_service=SimpleNamespace())


def test_save_chunk_writes_bytes_and_returns_size(isolated_storage):
    service = _service()

    written = service.save_chunk("sess-1", 0, b"hello")

    assert written == 5
    path = service._chunk_path("sess-1", 0)
    assert os.path.isfile(path)
    with open(path, "rb") as fh:
        assert fh.read() == b"hello"


def test_save_chunk_overwrites_same_index(isolated_storage):
    service = _service()
    service.save_chunk("s", 0, b"first")
    service.save_chunk("s", 0, b"second")

    with open(service._chunk_path("s", 0), "rb") as fh:
        assert fh.read() == b"second"


def test_merge_chunks_produces_ordered_output_and_hash(isolated_storage):
    service = _service()
    session_id = "sess-merge"
    parts = [b"AAA", b"BBB", b"CCC"]
    for index, part in enumerate(parts):
        service.save_chunk(session_id, index, part)

    target_key = "2026/09/14/merged.mp4"
    size, digest = service.merge_chunks(session_id, len(parts), target_key)

    assert size == 9
    assert digest == hashlib.sha3_256(b"AAABBBCCC").hexdigest()

    with open(service._object_path(target_key), "rb") as fh:
        assert fh.read() == b"AAABBBCCC"


def test_merge_chunks_raises_when_chunk_missing(isolated_storage):
    from internal.exception import FailException

    service = _service()
    service.save_chunk("sess-x", 0, b"AAA")

    with pytest.raises(FailException):
        service.merge_chunks("sess-x", 3, "2026/09/14/x.mp4")


def test_cleanup_session_removes_chunk_dir(isolated_storage):
    service = _service()
    service.save_chunk("sess-clean", 0, b"data")
    assert os.path.isdir(service._chunk_dir("sess-clean"))

    service.cleanup_session("sess-clean")

    assert not os.path.isdir(service._chunk_dir("sess-clean"))


def test_copy_object_duplicates_file_server_side(isolated_storage):
    service = _service()
    source_key = "2026/09/14/source.mp4"
    source_path = service._object_path(source_key)
    os.makedirs(os.path.dirname(source_path), exist_ok=True)
    with open(source_path, "wb") as fh:
        fh.write(b"payload")

    target_key = "2026/09/14/copy.mp4"
    size = service.copy_object(source_key, target_key)

    assert size == 7
    with open(service._object_path(target_key), "rb") as fh:
        assert fh.read() == b"payload"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_local_storage_chunks.py -v --no-cov`
Expected: FAIL with `AttributeError: module ... has no attribute '_get_chunk_upload_root'` 或 `AttributeError: 'LocalStorageService' object has no attribute 'save_chunk'`

- [ ] **Step 3: Read then implement**

**已核实的事实（务必遵循）**：
- `LocalStorageService` 目前**只有一个字段** `upload_file_service`，是 `@inject @dataclass`
- 存储根目录由模块级 `_get_local_storage_root()` 用 `os.getenv("LOCAL_STORAGE_ROOT")` 读取（**不经过 `Config()`**），默认 `storage/uploads`
- 已有模块级 helper：`_build_object_key`、`_ensure_parent_dir`、`_safe_join`（防路径穿越）
- `FailException` 已导入

**实现要求**：

1. 模块级新增 helper（与 `_get_local_storage_root` 同风格，用 `os.getenv`）：
```python
# 分片暂存根目录（相对于容器工作目录）
DEFAULT_CHUNK_UPLOAD_ROOT = "storage/chunks"


def _get_chunk_upload_root(override: str | None = None) -> str:
    """读取分片暂存根目录，未配置时使用默认值。"""
    if override:
        return override.strip() or DEFAULT_CHUNK_UPLOAD_ROOT
    return (os.getenv("CHUNK_UPLOAD_ROOT") or DEFAULT_CHUNK_UPLOAD_ROOT).strip() or DEFAULT_CHUNK_UPLOAD_ROOT
```

**注意**：`_get_local_storage_root()` 返回的是**相对路径**（如 `storage/uploads`），`_safe_join` 直接拼接使用，即实际相对当前工作目录（容器内 `/app/api`）。本计划的 `_get_chunk_upload_root` 保持同样语义（相对路径），**不要**改成绝对路径或 `Config()` 读取——否则与既有 `_get_local_storage_root` 行为不一致，且测试无法通过 monkeypatch 注入。

2. 类中新增私有/公开方法（沿用既有 `_safe_join` / `_ensure_parent_dir`）：
```python
    def _chunk_dir(self, session_id: str) -> str:
        """分片暂存目录（防路径穿越）。"""
        return _safe_join(_get_chunk_upload_root(), session_id)

    def _chunk_path(self, session_id: str, index: int) -> str:
        """单个分片的路径。"""
        return os.path.join(self._chunk_dir(session_id), f"{index:06d}.part")

    def _object_path(self, key: str) -> str:
        """对象在本地存储中的路径。"""
        return _safe_join(_get_local_storage_root(), key)

    def save_chunk(self, session_id: str, index: int, content: bytes) -> int:
        """把分片写入暂存目录，返回字节数（同下标覆盖）。"""
        path = self._chunk_path(session_id, index)
        _ensure_parent_dir(path)
        with open(path, "wb") as fh:
            fh.write(content)
        return len(content)

    def merge_chunks(self, session_id: str, total_chunks: int, target_key: str) -> tuple[int, str]:
        """按序流式合并分片为最终对象，返回 (总字节数, sha3_256)。

        全程分块读写，不把整个文件载入内存；缺任一必需分片时抛 FailException。
        """
        target_path = self._object_path(target_key)
        _ensure_parent_dir(target_path)
        hasher = hashlib.sha3_256()
        total = 0
        with open(target_path, "wb") as out:
            for index in range(total_chunks):
                chunk_path = self._chunk_path(session_id, index)
                if not os.path.isfile(chunk_path):
                    raise FailException(f"分片 {index} 缺失，无法完成合并")
                with open(chunk_path, "rb") as src:
                    while True:
                        block = src.read(1024 * 1024)
                        if not block:
                            break
                        out.write(block)
                        hasher.update(block)
                        total += len(block)
        return total, hasher.hexdigest()

    def cleanup_session(self, session_id: str) -> None:
        """删除会话的分片暂存目录（幂等）。"""
        shutil.rmtree(self._chunk_dir(session_id), ignore_errors=True)

    def copy_object(self, source_key: str, target_key: str) -> int:
        """服务端复制对象（秒传用），返回目标字节数。"""
        source_path = self._object_path(source_key)
        if not os.path.isfile(source_path):
            raise FailException("源文件不存在，无法完成秒传")
        target_path = self._object_path(target_key)
        _ensure_parent_dir(target_path)
        shutil.copyfile(source_path, target_path)
        return os.path.getsize(target_path)
```

3. 顶部 import 补 `import shutil`（`hashlib` / `os` 已导入）。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/service/test_local_storage_chunks.py -v --no-cov`
Expected: PASS (6 passed)

- [ ] **Step 5: 确认既有上传无回归**

Run: `cd api && python -m pytest test/internal/service/test_cos_service.py test/internal/service/test_upload_file_service.py test/internal/service/test_storage_extension_whitelist.py -q --no-cov`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/storage/local_storage_service.py api/test/internal/service/test_local_storage_chunks.py
git commit -m "feat(storage): add streaming chunk merge and server-side copy to local backend"
```

---

## Task 4: 分片上传编排服务

**Files:**
- Create: `api/internal/service/chunked_upload_service.py`
- Test: `api/test/internal/service/test_chunked_upload_service.py`

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/service/test_chunked_upload_service.py
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import FailException, ValidateErrorException
from internal.service.chunked_upload_service import ChunkedUploadService


class _FakeSessionService:
    def __init__(self):
        self.sessions = {}
        self.fingerprints = {}

    def create(self, **kwargs):
        session = SimpleNamespace(**kwargs, received_chunks=[])
        self.sessions[session.session_id] = session
        return session

    def get(self, session_id):
        return self.sessions.get(session_id)

    def mark_received(self, session_id, index):
        session = self.sessions.get(session_id)
        if session is not None and index not in session.received_chunks:
            session.received_chunks.append(index)
        return session

    def missing_chunks(self, session_id):
        session = self.sessions.get(session_id)
        if session is None:
            return []
        return [
            i for i in range(session.total_chunks) if i not in session.received_chunks
        ]

    def abort(self, session_id):
        self.sessions.pop(session_id, None)

    def register_fingerprint(self, account_id, fingerprint, upload_file_id):
        self.fingerprints[(account_id, fingerprint)] = upload_file_id

    def lookup_fingerprint(self, account_id, fingerprint):
        return self.fingerprints.get((account_id, fingerprint))


class _FakeStorage:
    def __init__(self):
        self.chunks = {}
        self.merged = []
        self.cleaned = []
        self.copied = []

    def save_chunk(self, session_id, index, content):
        self.chunks[(session_id, index)] = content
        return len(content)

    def merge_chunks(self, session_id, total_chunks, target_key):
        self.merged.append((session_id, total_chunks, target_key))
        return 1234, "digest-abc"

    def cleanup_session(self, session_id):
        self.cleaned.append(session_id)

    def copy_object(self, source_key, target_key):
        self.copied.append((source_key, target_key))
        return 999


class _FakeUploadFileService:
    def __init__(self):
        self.created = []

    def create_upload_file(self, **kwargs):
        record = SimpleNamespace(id=uuid4(), **kwargs)
        self.created.append(kwargs)
        return record


def _service(*, storage=None, session_service=None, upload_file_service=None,
             max_size=100 * 1024 * 1024, quota_error=None):
    quota_calls = []

    class _Quota:
        def resolve_max_file_size_bytes(self, account_id):
            return max_size

        def check_quota(self, account_id, incoming_bytes):
            quota_calls.append((account_id, incoming_bytes))
            if quota_error:
                raise quota_error

        def add_usage(self, account_id, bytes_delta):
            return bytes_delta

    service = ChunkedUploadService(
        db=SimpleNamespace(),
        storage=storage or _FakeStorage(),
        session_service=session_service or _FakeSessionService(),
        upload_file_service=upload_file_service or _FakeUploadFileService(),
        storage_quota_service=_Quota(),
    )
    return service, quota_calls


def _account():
    return SimpleNamespace(id=uuid4())


def test_init_rejects_file_exceeding_plan_limit():
    service, _calls = _service(max_size=1024)

    with pytest.raises(ValidateErrorException):
        service.init(
            account=_account(), filename="big.mp4", total_size=2048,
            chunk_size=512, total_chunks=4, fingerprint="fp",
        )


def test_init_checks_quota_and_returns_session():
    service, calls = _service()
    account = _account()

    result = service.init(
        account=account, filename="ok.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-1",
    )

    assert result["session_id"]
    assert result["total_chunks"] == 2
    assert calls == [(account.id, 1024)]


def test_init_returns_instant_hit_when_fingerprint_matches():
    session_service = _FakeSessionService()
    existing_id = str(uuid4())
    session_service.register_fingerprint(str(uuid4()), "fp-hit", existing_id)
    account = _account()
    session_service.register_fingerprint(str(account.id), "fp-hit", existing_id)

    service, _calls = _service(session_service=session_service)

    result = service.init(
        account=account, filename="dup.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-hit",
    )

    assert result["instant"] is True
    assert result["upload_file_id"] == existing_id


def test_save_chunk_marks_session():
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp",
    )["session_id"]

    result = service.save_chunk(session_id=session_id, index=0, content=b"x" * 512)

    assert result["received"] == 1
    assert session_service.sessions[session_id].received_chunks == [0]


def test_save_chunk_rejects_unknown_session():
    service, _calls = _service()

    with pytest.raises(FailException):
        service.save_chunk(session_id="nope", index=0, content=b"x")


def test_save_chunk_rejects_out_of_range_index():
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="a.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp",
    )["session_id"]

    with pytest.raises(ValidateErrorException):
        service.save_chunk(session_id=session_id, index=5, content=b"x")


def test_complete_merges_persists_and_cleans_up():
    session_service = _FakeSessionService()
    storage = _FakeStorage()
    upload_file_service = _FakeUploadFileService()
    service, _calls = _service(
        storage=storage, session_service=session_service,
        upload_file_service=upload_file_service,
    )
    account = _account()
    session_id = service.init(
        account=account, filename="final.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-final",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512)

    result = service.complete(session_id=session_id, account=account)

    assert result["size"] == 1234
    assert storage.merged and storage.merged[0][1] == 2
    assert upload_file_service.created[0]["size"] == 1234
    assert upload_file_service.created[0]["hash"] == "digest-abc"
    assert upload_file_service.created[0]["storage_backend"] == "local"
    assert storage.cleaned == [session_id]
    assert session_service.get(session_id) is None
    assert session_service.lookup_fingerprint(str(account.id), "fp-final") is not None


def test_complete_rejects_when_chunks_missing():
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="partial.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512)

    with pytest.raises(FailException):
        service.complete(session_id=session_id, account=account)


def test_instant_upload_copies_object_and_records_fingerprint():
    session_service = _FakeSessionService()
    storage = _FakeStorage()
    upload_file_service = _FakeUploadFileService()

    class _Existing:
        id = uuid4()
        key = "2026/09/14/original.mp4"
        name = "original.mp4"
        extension = "mp4"
        mime_type = "video/mp4"
        size = 4096

    class _Query:
        def filter(self, *_a, **_kw):
            return self

        def first(self):
            return _Existing()

    service, _calls = _service(
        storage=storage, session_service=session_service,
        upload_file_service=upload_file_service,
    )
    service.db = SimpleNamespace(session=SimpleNamespace(query=lambda *_a, **_kw: _Query()))
    account = _account()

    result = service.instant_upload(
        account=account, upload_file_id=str(_Existing.id), fingerprint="fp-copy",
    )

    assert result["instant"] is True
    assert result["upload_file_id"]
    assert storage.copied and storage.copied[0][0] == _Existing.key
    assert upload_file_service.created[0]["hash"]
    assert session_service.lookup_fingerprint(str(account.id), "fp-copy") is not None


def test_abort_cleans_chunks_and_session():
    session_service = _FakeSessionService()
    storage = _FakeStorage()
    service, _calls = _service(storage=storage, session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="x.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp",
    )["session_id"]

    service.abort(session_id=session_id, account=account)

    assert storage.cleaned == [session_id]
    assert session_service.get(session_id) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_chunked_upload_service.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'internal.service.chunked_upload_service'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/internal/service/chunked_upload_service.py
"""分片上传编排服务。

职责：
- init：校验单文件上限与配额、创建分片会话、秒传命中则直接复用
- save_chunk：把分片交给存储后端暂存并登记会话
- complete：流式合并分片 → 落 UploadFile 记录 → 清理暂存 → 登记秒传指纹
- abort：清理暂存与会话

仅支持 local 后端（云后端原生 multipart 属后续 P2B-2）。
"""
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from injector import inject

from internal.exception import FailException, ValidateErrorException
from internal.model import UploadFile
from internal.service.chunked_upload_session_service import ChunkedUploadSessionService
from internal.service.storage.local_storage_service import LocalStorageService
from internal.service.storage_quota_service import StorageQuotaService
from internal.service.upload_file_service import UploadFileService
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

logger = logging.getLogger(__name__)


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _build_object_key(filename: str) -> str:
    """与 local 后端一致的最终对象 key：{yyyy}/{mm}/{dd}/{uuid}.{ext}。"""
    import uuid

    extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
    random_filename = str(uuid.uuid4()) + (f".{extension}" if extension else "")
    now = _utcnow_naive()
    return f"{now.year}/{now.month:02d}/{now.day:02d}/{random_filename}"


@inject
@dataclass
class ChunkedUploadService(BaseService):
    """分片上传编排。"""

    db: SQLAlchemy
    storage: LocalStorageService
    session_service: ChunkedUploadSessionService
    upload_file_service: UploadFileService
    storage_quota_service: StorageQuotaService

    def init(
        self,
        *,
        account,
        filename: str,
        total_size: int,
        chunk_size: int,
        total_chunks: int,
        fingerprint: str = "",
    ) -> dict:
        """创建分片上传会话；命中秒传指纹时直接返回既有文件。"""
        if total_size <= 0:
            raise ValidateErrorException("文件大小必须大于 0")

        max_bytes = self.storage_quota_service.resolve_max_file_size_bytes(account.id)
        if total_size > max_bytes:
            raise ValidateErrorException(
                f"单个文件不能超过 {max_bytes // (1024 * 1024)}MB，请升级套餐后重试",
                {"file": [f"当前上限 {max_bytes} 字节"]},
            )

        expected_chunks = (total_size + chunk_size - 1) // chunk_size
        if total_chunks != expected_chunks:
            raise ValidateErrorException(
                "分片数量与文件大小不匹配",
                {"total_chunks": [f"期望 {expected_chunks}"]},
            )

        existing_id = self.session_service.lookup_fingerprint(str(account.id), fingerprint)
        if existing_id:
            return {"instant": True, "upload_file_id": existing_id}

        self.storage_quota_service.check_quota(account.id, total_size)

        session = self.session_service.create(
            account_id=str(account.id),
            filename=filename,
            total_size=total_size,
            chunk_size=chunk_size,
            total_chunks=total_chunks,
            fingerprint=fingerprint,
        )
        return {
            "instant": False,
            "session_id": session.session_id,
            "chunk_size": chunk_size,
            "total_chunks": total_chunks,
            "received_chunks": [],
        }

    def save_chunk(self, *, session_id: str, index: int, content: bytes) -> dict:
        """暂存一个分片并登记会话。"""
        session = self.session_service.get(session_id)
        if session is None:
            raise FailException("上传会话不存在或已过期，请重新开始上传")
        if index < 0 or index >= session.total_chunks:
            raise ValidateErrorException(
                "分片下标越界", {"index": [f"应在 0~{session.total_chunks - 1}"]}
            )
        if not content:
            raise ValidateErrorException("分片内容为空")

        self.storage.save_chunk(session_id, index, content)
        updated = self.session_service.mark_received(session_id, index)
        received = len(updated.received_chunks) if updated is not None else 0
        return {
            "received": received,
            "total_chunks": session.total_chunks,
            "missing_chunks": self.session_service.missing_chunks(session_id),
        }

    def complete(self, *, session_id: str, account) -> dict:
        """合并分片、落库并清理暂存。"""
        session = self.session_service.get(session_id)
        if session is None:
            raise FailException("上传会话不存在或已过期，请重新开始上传")

        missing = self.session_service.missing_chunks(session_id)
        if missing:
            raise FailException(f"仍有 {len(missing)} 个分片未上传，无法完成")

        if session.account_id != str(account.id):
            raise FailException("无权完成该上传会话")

        target_key = _build_object_key(session.filename)
        try:
            total_size, digest = self.storage.merge_chunks(
                session_id, session.total_chunks, target_key
            )
        except Exception:
            logger.exception("分片合并失败 session_id=%s", session_id)
            raise

        extension = (
            session.filename.rsplit(".", 1)[-1].lower() if "." in session.filename else ""
        )
        upload_file = self.upload_file_service.create_upload_file(
            account_id=account.id,
            name=session.filename,
            key=target_key,
            size=total_size,
            extension=extension,
            mime_type="",
            hash=digest,
            storage_backend="local",
        )

        self.storage_quota_service.add_usage(account.id, total_size)
        self.storage.cleanup_session(session_id)
        self.session_service.abort(session_id)
        self.session_service.register_fingerprint(
            str(account.id), session.fingerprint, str(upload_file.id)
        )

        return {
            "upload_file_id": str(upload_file.id),
            "size": total_size,
            "hash": digest,
            "key": target_key,
            "name": session.filename,
        }

    def instant_upload(self, *, account, upload_file_id: str, fingerprint: str) -> dict:
        """秒传：服务端复制既有对象并生成新的 UploadFile 记录。"""
        source = (
            self.db.session.query(UploadFile)
            .filter(UploadFile.id == UUID(upload_file_id))
            .first()
        )
        if source is None:
            raise FailException("秒传源文件不存在")

        target_key = _build_object_key(source.name or "material.bin")
        size = self.storage.copy_object(source.key, target_key)

        upload_file = self.upload_file_service.create_upload_file(
            account_id=account.id,
            name=source.name,
            key=target_key,
            size=size,
            extension=source.extension,
            mime_type=source.mime_type,
            hash="",
            storage_backend="local",
        )
        self.storage_quota_service.add_usage(account.id, size)
        self.session_service.register_fingerprint(
            str(account.id), fingerprint, str(upload_file.id)
        )
        return {
            "instant": True,
            "upload_file_id": str(upload_file.id),
            "size": size,
            "key": target_key,
            "name": source.name,
        }

    def abort(self, *, session_id: str, account) -> None:
        """放弃上传：清理暂存与会话。"""
        session = self.session_service.get(session_id)
        if session is None:
            return
        if session.account_id != str(account.id):
            raise FailException("无权取消该上传会话")
        self.storage.cleanup_session(session_id)
        self.session_service.abort(session_id)

    def status(self, *, session_id: str, account) -> dict:
        """查询会话进度（断点续传用）。"""
        session = self.session_service.get(session_id)
        if session is None:
            raise FailException("上传会话不存在或已过期")
        if session.account_id != str(account.id):
            raise FailException("无权查询该上传会话")
        return {
            "session_id": session.session_id,
            "filename": session.filename,
            "total_chunks": session.total_chunks,
            "chunk_size": session.chunk_size,
            "received_chunks": session.received_chunks,
            "missing_chunks": self.session_service.missing_chunks(session_id),
            "is_complete": len(session.received_chunks) >= session.total_chunks,
        }
```

**注意**：
- `storage` 字段必须用**具体类型 `LocalStorageService`**（injector 依据类型注解解析依赖；写 `object` 或 `Any` 会导致无法注入）。测试直接构造并传桩对象即可（Python 不做运行时类型检查）。
- `ChunkedUploadSessionService` 与 `UploadFileService`、`StorageQuotaService` 均需在 `module.py` 注册（Task 5 统一处理）。
- 可能存在循环导入：`knowledge_base_service` 与本服务互相引用，故 `_knowledge_base_service()` 用**方法内延迟导入**（见 Task 6）。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/service/test_chunked_upload_service.py -v --no-cov`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/chunked_upload_service.py api/test/internal/service/test_chunked_upload_service.py
git commit -m "feat(storage): add chunked upload orchestration service"
```

---

## Task 5: HTTP 路由与 DI 注册

**Files:**
- Create: `api/internal/schema/chunked_upload_schema.py`
- Create: `api/app/http/chunked_upload_routes.py`
- Modify: `api/app/http/module.py`（DI 绑定）
- Modify: `api/app/http/asgi_app.py`（路由注册）
- Test: `api/test/app/http/test_chunked_upload_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# api/test/app/http/test_chunked_upload_routes.py
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.fixture
def app_with_stubbed_service(monkeypatch):
    from app.http import app as app_module

    recorded = {}

    class _StubService:
        def init(self, **kwargs):
            recorded["init"] = kwargs
            return {"session_id": "s-1", "chunk_size": 5242880, "total_chunks": 2}

        def save_chunk(self, **kwargs):
            recorded["save_chunk"] = kwargs
            return {"received": 1, "total_chunks": 2, "missing_chunks": [1]}

        def status(self, **kwargs):
            recorded["status"] = kwargs
            return {"session_id": "s-1", "received_chunks": [0], "missing_chunks": [1]}

        def complete(self, **kwargs):
            recorded["complete"] = kwargs
            return {"upload_file_id": "u-1", "size": 100, "key": "k", "name": "a.mp4"}

        def abort(self, **kwargs):
            recorded["abort"] = kwargs
            return None

    monkeypatch.setattr(app_module, "_get_service", lambda _cls: _StubService(), raising=False)
    return app_module, recorded


def test_init_route_rejects_missing_fields(app_with_stubbed_service):
    app_module, _recorded = app_with_stubbed_service
    client = app_module.app.test_client()

    response = client.post("/space/chunked-uploads/init", json={})

    assert response.status_code == 400


def test_init_route_returns_session(app_with_stubbed_service):
    app_module, recorded = app_with_stubbed_service
    client = app_module.app.test_client()

    response = client.post(
        "/space/chunked-uploads/init",
        json={
            "filename": "promo.mp4",
            "total_size": 10,
            "chunk_size": 5,
            "total_chunks": 2,
            "fingerprint": "fp",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["session_id"] == "s-1"
    assert recorded["init"]["filename"] == "promo.mp4"
```

**注意**：若该仓库路由测试的统一风格不同（如使用 `app.test_app`、或需要登录态/`_resolve_account` 桩），请**先读 `api/test/app/http/` 下一个既有路由测试文件**（如 `test_admin_routes_*.py` 或涉及 `/space/` 的测试），严格沿用同样的 fixture 与断言风格重写本测试。`/space/` 路由通常需要登录态，若测试夹具无法直接通过，可改为直接调用路由函数并断言返回体（与既有同类测试保持一致）。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/app/http/test_chunked_upload_routes.py -v --no-cov`
Expected: FAIL（路由未注册，返回 404）

- [ ] **Step 3: Write minimal implementation**

`api/internal/schema/chunked_upload_schema.py`：

```python
"""分片上传请求/响应 schema。"""
from marshmallow import Schema, fields


class ChunkedInitReq(Schema):
    """初始化分片会话。"""

    filename = fields.String(required=True)
    total_size = fields.Integer(required=True)
    chunk_size = fields.Integer(required=True)
    total_chunks = fields.Integer(required=True)
    fingerprint = fields.String(load_default="")
    knowledge_base_id = fields.String(load_default="")


class ChunkedCompleteReq(Schema):
    """完成分片上传。"""

    session_id = fields.String(required=True)
    knowledge_base_id = fields.String(load_default="")
```

`api/app/http/chunked_upload_routes.py`：

```python
"""分片上传路由。

提供 init / chunk / status / complete / abort 五个接口，
由前端在大文件上传时按分片调用，支持断点续传与秒传。

沿用 app.http.support 的统一 helper（_ok / _ok_msg / _json_resp / _resolve_account / _to_thread），
与 knowledge_mcp_routes.py 的写法保持一致。
"""
import logging

from quart import Response, request

from app.http import support as _support
from app.http.support import _json_resp, _ok, _resolve_account, _to_thread

logger = logging.getLogger(__name__)

_registered = False


def _get_service(cls):
    return _support._get_service(cls)


def register_routes(quart_app) -> None:
    """注册分片上传路由（幂等）。"""
    global _registered
    if _registered:
        return
    _registered = True

    @quart_app.post("/space/chunked-uploads/init")
    async def chunked_upload_init() -> Response:
        """初始化分片会话（含秒传判定）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(silent=True) or {}
        missing = [
            key for key in ("filename", "total_size", "chunk_size", "total_chunks")
            if payload.get(key) in (None, "", 0)
        ]
        if missing:
            return _json_resp(
                code="validate_error",
                message="参数不完整",
                data={key: ["该字段必填"] for key in missing},
                status=400,
            )

        from internal.service.chunked_upload_service import ChunkedUploadService

        result = await _to_thread(
            _get_service(ChunkedUploadService).init,
            account=account,
            filename=payload["filename"],
            total_size=int(payload["total_size"]),
            chunk_size=int(payload["chunk_size"]),
            total_chunks=int(payload["total_chunks"]),
            fingerprint=payload.get("fingerprint", ""),
        )
        return _ok(result)

    @quart_app.post("/space/chunked-uploads/chunk")
    async def chunked_upload_chunk() -> Response:
        """上传单个分片。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        form = await request.form
        session_id = form.get("session_id") or ""
        index_raw = form.get("index")
        if not session_id or index_raw is None:
            return _json_resp(
                code="validate_error",
                message="会话与分片下标必填",
                data={"session_id": ["会话与分片下标必填"]},
                status=400,
            )

        files = await request.files
        chunk = files.get("chunk")
        if chunk is None:
            return _json_resp(
                code="validate_error",
                message="分片内容不能为空",
                data={"chunk": ["分片内容不能为空"]},
                status=400,
            )
        content = chunk.stream.read()

        from internal.service.chunked_upload_service import ChunkedUploadService

        result = await _to_thread(
            _get_service(ChunkedUploadService).save_chunk,
            session_id=session_id,
            index=int(index_raw),
            content=content,
        )
        return _ok(result)

    @quart_app.get("/space/chunked-uploads/<session_id>/status")
    async def chunked_upload_status(session_id: str) -> Response:
        """查询会话进度（断点续传）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service.chunked_upload_service import ChunkedUploadService

        result = await _to_thread(
            _get_service(ChunkedUploadService).status,
            session_id=session_id,
            account=account,
        )
        return _ok(result)

    @quart_app.post("/space/chunked-uploads/complete")
    async def chunked_upload_complete() -> Response:
        """合并分片并（可选）创建知识库文档。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(silent=True) or {}
        session_id = payload.get("session_id") or ""
        if not session_id:
            return _json_resp(
                code="validate_error",
                message="会话必填",
                data={"session_id": ["会话必填"]},
                status=400,
            )

        from internal.service.chunked_upload_service import ChunkedUploadService

        result = await _to_thread(
            _get_service(ChunkedUploadService).complete,
            session_id=session_id,
            account=account,
            knowledge_base_id=payload.get("knowledge_base_id", ""),
        )
        return _ok(result)

    @quart_app.post("/space/chunked-uploads/abort")
    async def chunked_upload_abort() -> Response:
        """放弃上传并清理暂存。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(silent=True) or {}
        session_id = payload.get("session_id") or ""
        if not session_id:
            return _json_resp(
                code="validate_error",
                message="会话必填",
                data={"session_id": ["会话必填"]},
                status=400,
            )

        from internal.service.chunked_upload_service import ChunkedUploadService

        await _to_thread(
            _get_service(ChunkedUploadService).abort,
            session_id=session_id,
            account=account,
        )
        return _ok_msg("已取消上传")
```

**已核实的事实（务必遵循，勿臆测）**：
- 响应 helper 来自 `app.http.support`，实际为 `_ok(data)` / `_ok_msg(message)` / `_json_resp(code=..., message=..., data=..., status=...)`——**不存在** `success_json` / `validate_error_json`
- 鉴权用 `from app.http.support import _resolve_account`（返回 `(account, err)` 二元组）
- 同步 service 调用必须经 `_to_thread(...)` 移入线程池（Quart 异步环境下阻塞 DB/文件 IO 会卡事件循环）
- 取 service 用 `app.http.support._get_service(Cls)`（该模块有 service 缓存）

`api/app/http/module.py` 追加绑定（**放在文件顶部 import 区**，与该文件既有风格一致——该文件在顶部集中 import 各 service）：

```python
from internal.service.chunked_upload_service import ChunkedUploadService
from internal.service.chunked_upload_session_service import ChunkedUploadSessionService
from internal.service.storage.local_storage_service import LocalStorageService
```

并在 `configure` 方法内（`binder.bind(CosService, ...)` 附近）追加：

```python
        binder.bind(ChunkedUploadSessionService, to=ChunkedUploadSessionService, scope=singleton)
        binder.bind(LocalStorageService, to=LocalStorageService, scope=singleton)
        binder.bind(ChunkedUploadService, to=ChunkedUploadService, scope=singleton)
```

**注意**：`CosService` 与 `ObjectStoragePort` 当前绑定到 `RuntimeStorageProxy`（`module.py` 已有）。`LocalStorageService` 需独立绑定，因为分片能力（`save_chunk`/`merge_chunks`/`copy_object`）只在 local 后端提供，且 `ChunkedUploadService.storage` 的类型注解就是 `LocalStorageService`。

路由注册（**已核实真实模式**）：所有路由模块统一暴露 `register_routes(quart_app)`，由 `api/app/http/asgi_app.py` 集中注册。需在该文件：
1. import 区（第 218-232 行的同类 import 附近）追加：
```python
from app.http.chunked_upload_routes import register_routes as _register_chunked_upload_routes
```
2. 注册区（第 234-258 行）追加：
```python
_register_chunked_upload_routes(quart_app)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/app/http/test_chunked_upload_routes.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: 验证 DI 全链路可解析**

Run: `cd api && python -c "import sys; sys.path.insert(0,'.'); from pkg.env_loader import load_project_env; load_project_env(); from app.http.app import app; from internal.service.chunked_upload_service import ChunkedUploadService; from internal.service.chunked_upload_session_service import ChunkedUploadSessionService; print('upload:', app.injector.get(ChunkedUploadService) is not None); print('session:', app.injector.get(ChunkedUploadSessionService) is not None)"`
Expected: 两行 `True`

- [ ] **Step 6: Commit**

```bash
git add api/internal/schema/chunked_upload_schema.py api/app/http/chunked_upload_routes.py api/app/http/module.py api/test/app/http/test_chunked_upload_routes.py
git commit -m "feat(storage): add chunked upload http routes and di bindings"
```

---

## Task 6: 知识库接线（分片完成后建档并触发索引）

**Files:**
- Modify: `api/internal/service/knowledge_base_service.py`
- Modify: `api/app/http/chunked_upload_routes.py`（complete 分支支持 `knowledge_base_id`）
- Modify: `api/internal/service/chunked_upload_service.py`（complete 接受可选 `knowledge_base_id`）
- Test: `api/test/internal/service/test_knowledge_document_from_upload.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/service/test_knowledge_document_from_upload.py
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.service.knowledge_base_service import KnowledgeBaseService


def _service(monkeypatch):
    created = []
    indexed = []
    service = KnowledgeBaseService(
        db=SimpleNamespace(),
        retrieval_service=SimpleNamespace(),
        icon_generator_service=SimpleNamespace(),
    )
    service.get_accessible_base = lambda _id, _account: SimpleNamespace(id=_id)
    service.create = lambda model, **kwargs: created.append(kwargs) or SimpleNamespace(
        id=uuid4(), **kwargs
    )
    service._get_knowledge_indexing_service = lambda: SimpleNamespace(
        build_document=lambda doc_id, account: indexed.append(doc_id)
    )
    return service, created, indexed


def test_create_document_from_upload_file_records_media_type(monkeypatch):
    service, created, indexed = _service(monkeypatch)
    account = SimpleNamespace(id=uuid4())
    knowledge_base_id = uuid4()
    upload_file = SimpleNamespace(
        id=uuid4(), name="promo.mp4", extension="mp4", size=2048
    )

    document = service.create_document_from_upload_file(
        knowledge_base_id=knowledge_base_id,
        upload_file=upload_file,
        account=account,
    )

    assert created[0]["media_type"] == "video"
    assert created[0]["upload_file_id"] == upload_file.id
    assert created[0]["parse_profile"] == {}
    assert indexed == [document.id]


def test_create_document_from_upload_file_enforces_base_type(monkeypatch):
    from internal.exception import ValidateErrorException

    service, created, indexed = _service(monkeypatch)
    service.get_accessible_base = lambda _id, _account: SimpleNamespace(
        id=_id, base_type="video"
    )
    account = SimpleNamespace(id=uuid4())
    upload_file = SimpleNamespace(id=uuid4(), name="doc.pdf", extension="pdf", size=10)

    with pytest.raises(ValidateErrorException):
        service.create_document_from_upload_file(
            knowledge_base_id=uuid4(), upload_file=upload_file, account=account
        )

    assert created == []
    assert indexed == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_document_from_upload.py -v --no-cov`
Expected: FAIL with `AttributeError: 'KnowledgeBaseService' object has no attribute 'create_document_from_upload_file'`

- [ ] **Step 3: Implement**

**先读** `api/internal/service/knowledge_base_service.py` 的 `upload_document`（Task 6/P2A 已改）与 `_assert_media_type_allowed`，然后**抽出共用逻辑**：新增 `create_document_from_upload_file`，并让 `upload_document` 复用它在落盘后建档的部分（消除重复）。

```python
    def create_document_from_upload_file(
            self,
            *,
            knowledge_base_id,
            upload_file: UploadFile,
            account: Account,
            partition_id=None,
    ) -> KnowledgeDocument:
        """由已存在的 UploadFile 创建知识库文档并触发索引。

        用于分片上传完成后的建档；会做板块类型硬约束校验。
        """
        knowledge_base = self.get_accessible_base(knowledge_base_id, account)

        extension = (upload_file.extension or "").lower()
        self._assert_media_type_allowed(knowledge_base, extension)
        media_type = media_type_for_extension(extension)

        document = self.create(
            KnowledgeDocument,
            knowledge_base_id=knowledge_base.id,
            owner_account_id=account.id,
            name=upload_file.name,
            content_type="document",
            source_type=KnowledgeCreatedFrom.MANUAL_UPLOAD.value,
            source_id=str(upload_file.id),
            upload_file_id=upload_file.id,
            partition_id=partition_id,
            media_type=media_type,
            parse_profile={},
            metadata_={
                "upload_file_id": str(upload_file.id),
                "operation_context": OperationContext.USER.value,
            },
            character_count=0,
            status=DocumentStatus.WAITING.value,
        )

        indexing_service = self._get_knowledge_indexing_service()
        indexing_service.build_document(document.id, account)

        return document
```

并把 `upload_document` 的落盘后续部分改为调用它：

```python
        upload_file = cos_service.upload_file(file=file, only_image=False, account=account)
        return self.create_document_from_upload_file(
            knowledge_base_id=knowledge_base.id,
            upload_file=upload_file,
            account=account,
        )
```

（`_assert_media_type_allowed` 的"先校验后落盘"逻辑保留在 `upload_document` 开头不变；`create_document_from_upload_file` 内的校验用于分片路径。）

`api/internal/service/chunked_upload_service.py` 的 `complete` 增加可选参数并透传：

```python
    def complete(self, *, session_id: str, account, knowledge_base_id: str = "") -> dict:
```
在返回前，若 `knowledge_base_id` 非空，则调用知识库服务建档。由于会引入对 `KnowledgeBaseService` 的依赖（可能循环导入），**用延迟导入**：

```python
        if knowledge_base_id:
            from internal.service.knowledge_base_service import KnowledgeBaseService

            knowledge_service = self._knowledge_base_service()
            document = knowledge_service.create_document_from_upload_file(
                knowledge_base_id=knowledge_base_id,
                upload_file=upload_file,
                account=account,
            )
            result["document_id"] = str(document.id)
```

其中 `self._knowledge_base_service()` 通过 DI 容器获取（与 `recycle_bin_handlers._get_knowledge_vector_service` 同样的延迟注入范式）：

```python
    def _knowledge_base_service(self):
        from app.http.module import injector

        from internal.service.knowledge_base_service import KnowledgeBaseService

        return injector.get(KnowledgeBaseService)
```

在 `api/test/internal/service/test_chunked_upload_service.py` 的 `test_complete_merges_persists_and_cleans_up` 中，`complete` 调用不带 `knowledge_base_id`，故不受影响；再追加一个测试验证透传：

```python
def test_complete_registers_document_when_knowledge_base_given(monkeypatch):
    session_service = _FakeSessionService()
    service, _calls = _service(session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="kb.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-kb",
    )["session_id"]
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512)

    recorded = {}

    class _Knowledge:
        def create_document_from_upload_file(self, **kwargs):
            recorded.update(kwargs)
            return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(service, "_knowledge_base_service", lambda: _Knowledge())

    result = service.complete(
        session_id=session_id, account=account, knowledge_base_id=str(uuid4())
    )

    assert "document_id" in result
    assert recorded["upload_file"].size == 1234
```

`api/app/http/chunked_upload_routes.py` 的 complete 分支把 `knowledge_base_id` 透传：

```python
        result = service.complete(
            session_id=session_id,
            account=account,
            knowledge_base_id=payload.get("knowledge_base_id", ""),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_document_from_upload.py test/internal/service/test_chunked_upload_service.py test/internal/service/test_knowledge_base_service.py test/internal/service/test_knowledge_upload_media_type.py -v --no-cov`
Expected: PASS（新 2 + 新 1 + 既有无回归）

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/knowledge_base_service.py api/internal/service/chunked_upload_service.py api/app/http/chunked_upload_routes.py api/test/internal/service/test_knowledge_document_from_upload.py api/test/internal/service/test_chunked_upload_service.py
git commit -m "feat(knowledge): create document from chunked upload result"
```

---

## Task 7: 前端分片上传

**Files:**
- Create: `ui/src/services/chunked-upload.ts`
- Modify: `ui/src/hooks/use-knowledge-base.ts`
- Modify: `ui/src/views/space/datasets/documents/ListView.vue`
- Modify: i18n 消息文件（zh-CN / en-US）

- [ ] **Step 1: 读现有前端实现**

先读：
- `ui/src/utils/request.ts` 的 `upload()`（约 576-685 行）与 `UploadOptions` 类型，确认 `onprogress` 用法
- `ui/src/services/knowledge-base.ts` 的 `uploadKnowledgeDocument`
- `ui/src/hooks/use-knowledge-base.ts` 的 `useUploadKnowledgeDocument`（约 406-423 行）
- `ui/src/views/space/datasets/documents/ListView.vue` 的 `handleFileChange` / `triggerFileInput` / 模板中的隐藏 input（约 451-457 行）
- `ui/src/utils/request.ts` 的 `post` / `get` 签名

- [ ] **Step 2: 新建 `ui/src/services/chunked-upload.ts`**

```ts
import { get, post, upload } from '@/utils/request'
import type { BaseResponse } from '@/types/response'

/** 分片大小：5MB（与后端默认一致） */
const CHUNK_SIZE = 5 * 1024 * 1024
/** 直接单次上传的阈值：小于该值走原有单次接口 */
export const SINGLE_UPLOAD_THRESHOLD = CHUNK_SIZE
/** 并发上传分片数 */
const CONCURRENCY = 3

export interface ChunkedUploadProgress {
  uploadedChunks: number
  totalChunks: number
  percent: number
}

export interface ChunkedUploadResult {
  uploadFileId: string
  name: string
  size: number
  documentId?: string
}

/**
 * 计算秒传指纹：文件大小 + 首/中/尾分片内容的哈希。
 * 全文件哈希在浏览器端对 GB 级文件过慢，故采用抽样指纹。
 */
const computeFingerprint = async (file: File): Promise<string> => {
  const sampleSize = 256 * 1024
  const offsets = [
    0,
    Math.max(0, Math.floor(file.size / 2) - sampleSize / 2),
    Math.max(0, file.size - sampleSize),
  ]
  const parts: ArrayBuffer[] = []
  for (const offset of offsets) {
    const slice = file.slice(offset, offset + sampleSize)
    parts.push(await slice.arrayBuffer())
  }

  const totalLength = parts.reduce((sum, buf) => sum + buf.byteLength, 0)
  const merged = new Uint8Array(totalLength)
  let cursor = 0
  for (const buf of parts) {
    merged.set(new Uint8Array(buf), cursor)
    cursor += buf.byteLength
  }

  const digest = await crypto.subtle.digest('SHA-256', merged)
  const hex = Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
  return `${file.size}-${hex}`
}

/** 需要断点续传时保留的会话缓存键 */
const sessionCacheKey = (fingerprint: string) => `chunked-upload-session:${fingerprint}`

/**
 * 上传单个文件（自动选择单次上传或分片上传）。
 */
export const uploadFileChunked = async (
  knowledgeBaseId: string,
  file: File,
  onProgress?: (progress: ChunkedUploadProgress) => void,
): Promise<ChunkedUploadResult> => {
  const fingerprint = await computeFingerprint(file)
  const cachedSessionId = localStorage.getItem(sessionCacheKey(fingerprint))

  const initResponse = await post<BaseResponse<Record<string, unknown>>>(
    '/space/chunked-uploads/init',
    {
      body: {
        filename: file.name,
        total_size: file.size,
        chunk_size: CHUNK_SIZE,
        total_chunks: Math.ceil(file.size / CHUNK_SIZE),
        fingerprint,
        knowledge_base_id: knowledgeBaseId,
      },
    },
  )
  const initData = initResponse.data as Record<string, unknown>

  // 秒传命中：服务端已复制好文件
  if (initData.instant) {
    localStorage.removeItem(sessionCacheKey(fingerprint))
    const completed = await completeUpload(String(initData.upload_file_id), initData, knowledgeBaseId)
    onProgress?.({ uploadedChunks: 1, totalChunks: 1, percent: 100 })
    return completed
  }

  const sessionId = String(initData.session_id ?? cachedSessionId ?? '')
  const totalChunks = Number(initData.total_chunks)
  localStorage.setItem(sessionCacheKey(fingerprint), sessionId)

  // 断点续传：查询已收到的分片
  let received = new Set<number>()
  try {
    const statusResponse = await get<BaseResponse<Record<string, unknown>>>(
      `/space/chunked-uploads/${sessionId}/status`,
    )
    const statusData = statusResponse.data as Record<string, unknown>
    received = new Set((statusData.received_chunks as number[]) ?? [])
  } catch {
    received = new Set<number>()
  }

  const pending: number[] = []
  for (let index = 0; index < totalChunks; index += 1) {
    if (!received.has(index)) pending.push(index)
  }

  let uploaded = received.size
  const reportProgress = () => {
    onProgress?.({
      uploadedChunks: uploaded,
      totalChunks,
      percent: Math.floor((uploaded / totalChunks) * 100),
    })
  }
  reportProgress()

  const uploadOne = async (index: number) => {
    const start = index * CHUNK_SIZE
    const blob = file.slice(start, Math.min(start + CHUNK_SIZE, file.size))
    const formData = new FormData()
    formData.append('session_id', sessionId)
    formData.append('index', String(index))
    formData.append('chunk', blob, `${file.name}.part${index}`)

    await upload<BaseResponse<Record<string, unknown>>>('/space/chunked-uploads/chunk', {
      data: formData,
      onprogress: (event) => {
        // 分片内部进度可选：此处仅按完成分片数上报
        void event
      },
    })
    uploaded += 1
    reportProgress()
  }

  // 并发上传，失败则抛出，已上传分片会保留（断点续传）
  for (let cursor = 0; cursor < pending.length; cursor += CONCURRENCY) {
    const batch = pending.slice(cursor, cursor + CONCURRENCY)
    await Promise.all(batch.map((index) => uploadOne(index)))
  }

  const completed = await completeUpload(sessionId, { session_id: sessionId }, knowledgeBaseId)
  localStorage.removeItem(sessionCacheKey(fingerprint))
  return completed
}

/** 调用 complete 接口，返回统一结果结构。 */
const completeUpload = async (
  sessionIdOrFileId: string,
  initData: Record<string, unknown>,
  knowledgeBaseId: string,
): Promise<ChunkedUploadResult> => {
  const isInstant = Boolean(initData.instant)
  const response = await post<BaseResponse<Record<string, unknown>>>(
    '/space/chunked-uploads/complete',
    {
      body: {
        session_id: sessionIdOrFileId,
        knowledge_base_id: knowledgeBaseId,
        upload_file_id: isInstant ? sessionIdOrFileId : undefined,
      },
    },
  )
  const data = response.data as Record<string, unknown>
  return {
    uploadFileId: String(data.upload_file_id),
    name: String(data.name),
    size: Number(data.size),
    documentId: data.document_id ? String(data.document_id) : undefined,
  }
}
```

**注意**：
- `post` 的 `body` 传 JSON 时是否被 `baseFetch` 自动序列化、`Content-Type` 是否为 `application/json`——**必须先读 `ui/src/utils/request.ts` 的 `baseFetch` 确认**；若该封装只接受 FormData 或需要显式 `headers: { 'Content-Type': 'application/json' }`，按实际调整。
- 秒传命中时 `complete` 需要一个"仅建档"的路径：后端 `complete` 的 `session_id` 为空时无法建档。**因此需在 Task 6 的 complete 路由/branch 中支持 `upload_file_id` 直传建档**（当 `session_id` 为空且 `upload_file_id` 非空时，跳过会话校验，直接按该 upload_file 建档）。请在实现 Task 7 时补齐 Task 6 的该分支，或改为秒传时前端直接调用一个独立的 `POST /space/chunked-uploads/instant-complete`。**二选一，并在实现时保持一致。**

- [ ] **Step 3: 接入 hook 与视图**

`ui/src/hooks/use-knowledge-base.ts` 新增：

```ts
export const useChunkedUploadKnowledgeDocument = () => {
  const loading = ref(false)
  const progress = ref<ChunkedUploadProgress>({ uploadedChunks: 0, totalChunks: 0, percent: 0 })

  const uploadDocument = async (knowledgeBaseId: string, file: File) => {
    loading.value = true
    progress.value = { uploadedChunks: 0, totalChunks: 0, percent: 0 }
    try {
      return await uploadFileChunked(knowledgeBaseId, file, (next) => {
        progress.value = next
      })
    } finally {
      loading.value = false
    }
  }

  return { loading, progress, uploadDocument }
}
```

`ui/src/views/space/datasets/documents/ListView.vue`：
- 把 `handleFileChange` 改为：文件小于 `SINGLE_UPLOAD_THRESHOLD` 时仍调原 `handleUploadDocument`；否则调 `uploadDocument`（分片）
- 上传中展示进度（若视图已有 `a-progress` 或 loading 文案，复用之；否则用一个简单的百分比文案）
- `accept` 属性补上音视频扩展名：`.mp4,.mov,.avi,.mkv,.webm,.mp3,.wav,.m4a,.aac,.flac`

**先读该文件确认**：
- 是否已引入 `a-upload` / `a-progress` 等组件
- i18n 使用方式（`t('...')` 的命名空间），新增文案需同时加 `zh-CN` 与 `en-US`

- [ ] **Step 4: 验证前端**

Run: `cd ui && npx vue-tsc --noEmit`（或仓库实际的 typecheck 命令，读 `ui/package.json` 的 `scripts` 确认）
Expected: 无类型错误

Run: `cd ui && npm run lint`（若存在）
Expected: 通过

- [ ] **Step 5: Commit**

```bash
git add ui/src/services/chunked-upload.ts ui/src/hooks/use-knowledge-base.ts ui/src/views/space/datasets/documents/ListView.vue
git commit -m "feat(knowledge): chunked upload with resume and instant upload in ui"
```

---

## Task 8: 单次上传上限放宽与归档

**Files:**
- Modify: `api/internal/schema/upload_file_schema.py`
- Modify: `docs/prd/modules/06-file-storage.md`
- Modify: `docs/prd/knowledge-base-product-form-design.md`

- [ ] **Step 1: 放宽单次接口的硬编码上限**

`upload_file_schema.py` 中的 `FileSize(max_size=15*1024*1024, ...)` 是**绝对防滥用上限**（大文件应走分片链路）。将其提升为一个明确的"防御上限"常量并注明用途：

```python
# 单次 multipart 上传的绝对上限（防御滥用）；大文件请走分片上传接口
MAX_SINGLE_REQUEST_BYTES = 64 * 1024 * 1024


class UploadFileReq(Form):
    """上传文件请求"""

    file = FileField("file", validators=[
        FileRequired("上传文件不能为空"),
        FileSize(max_size=MAX_SINGLE_REQUEST_BYTES, message=f"单次上传不能超过{MAX_SINGLE_REQUEST_BYTES // (1024 * 1024)}MB，大文件请使用分片上传"),
        FileAllowed(ALLOWED_DOCUMENT_EXTENSION, message=f"仅允许上传{'/'.join(ALLOWED_DOCUMENT_EXTENSION)}文件")
    ])
```

`UploadImageReq` 保持不变（图片 15MB 上限合理）。

**注意**：`upload_file_schema.py` 的 `FileAllowed(ALLOWED_DOCUMENT_EXTENSION)` 仍只允许文档扩展名。**若该 Req 被 image/video 路径复用，需一并放宽为 `allowed_extensions_for_base_type("mixed")`**——请先读代码确认 `UploadFileReq` 的实际使用位置（前面调研显示路由层**未实例化**该 Req，即它是"备用"校验），据实决定：若确实无人使用，只更新常量与注释并在提交信息中说明。

- [ ] **Step 2: 回归验证**

Run: `cd api && python -m pytest test/internal/service/test_chunked_upload_service.py test/internal/service/test_chunked_upload_session_service.py test/internal/service/test_local_storage_chunks.py test/internal/service/test_knowledge_document_from_upload.py test/internal/schema test/app/http/test_chunked_upload_routes.py -q --no-cov`
Expected: PASS

Run: `cd api && python -m pytest -q --no-cov 2>&1 | Select-Object -Last 15`
Expected: 无**新增**失败（对照改动前基线；已知 `test_home_integration.py` 的 3 个 error 与 `schedule_task` 相关失败属工作区其他在途改动）

- [ ] **Step 3: 更新架构文档**

`docs/prd/modules/06-file-storage.md`：新增一节「分片上传（P2B 已落地）」，说明：
- 分片大小 5MB、并发 3、会话状态存 Redis（多 worker 共享）、分片暂存 `storage/chunks/{session_id}/`
- 完整流程：init（校验单文件上限与配额、秒传命中）→ chunk（暂存+登记）→ complete（**流式合并** + 增量 sha3_256 + 落 UploadFile 记录 + 清理暂存 + 登记秒传指纹）
- 秒传：文件大小 + 抽样分片哈希的指纹，同账号去重，服务端复制（保证删除语义独立）
- 断点续传：`status` 接口返回 `received_chunks`/`missing_chunks`
- **单文件上限按套餐分级**（`PlanEntitlement` 的 `max_single_file_gb`，默认 15MB）
- **明确标注**：仅支持 `local` 后端；`cos`/`oss` 的原生 multipart 属 P2B-2

`docs/prd/knowledge-base-product-form-design.md`：把 §八缺陷 2 与 §九 P2B 标为已完成，附计划链接 `docs/superpowers/plans/2026-09-14-knowledge-base-p2b-chunked-upload.md`，并把 §十一待确认第 5 项（分片规格）写定（5MB / 3 并发 / Redis 会话 / 24h TTL）。

- [ ] **Step 4: 更新知识图谱**

Run: `cd d:\DEMO\openagent-main && python -m graphify update .`
Expected: 成功更新

- [ ] **Step 5: Commit**

```bash
git add api/internal/schema/upload_file_schema.py docs/prd/modules/06-file-storage.md docs/prd/knowledge-base-product-form-design.md
git commit -m "docs(storage): document chunked upload and relax single request cap"
```

---

## 验收清单

| # | 验收项 | 验证方式 |
|---|---|---|
| 1 | 单文件上限可按套餐分级 | `test_storage_quota_service.py` 的 max_file_size 用例 |
| 2 | 分片会话状态存 Redis 且支持断点续传查询 | `test_chunked_upload_session_service.py` |
| 3 | 分片可暂存、可覆盖、可清理 | `test_local_storage_chunks.py` |
| 4 | **合并为流式**（不整文件入内存）且增量算 sha3_256 | `test_local_storage_chunks.py` 的 merge 用例（用 1MB 分块读写断言） |
| 5 | 秒传命中不传输字节 | `test_chunked_upload_service.py` 的 instant 用例 |
| 6 | 秒传走服务端复制，删除语义独立 | `copy_object` 用例 + `instant_upload` 断言新 key |
| 7 | 缺分片时 complete 明确报错 | `test_chunked_upload_service.py` 的 partial 用例 |
| 8 | 配额在 init 预校验、complete 累加 | `test_chunked_upload_service.py` 的 quota 断言 |
| 9 | 五个路由可用且做登录态校验 | `test_chunked_upload_routes.py` |
| 10 | 分片完成后自动建档并触发索引 | `test_knowledge_document_from_upload.py` |
| 11 | 前端可切分/并发/进度/断点续传 | `vue-tsc` + 手工验证「传 1GB 视频不中断」 |
| 12 | 无新增回归 | Task 8 Step 2 |

## 已知限制（需在文档标注）

1. **仅 `local` 后端支持分片**：`cos`/`oss` 需各自的原生 multipart 适配，属 P2B-2。
2. **分片暂存目录无自动清理**：`abort`/`complete` 会清理；但客户端中途放弃且不调 `abort` 时，分片文件会残留至手动清理。建议后续加一个定时任务清理超过 TTL 的暂存目录（P2B-2）。
3. **秒传为同账号去重**：跨账号不复用（避免删除语义与隐私问题）。
4. **单分片大小固定 5MB**：不支持动态/自适应分片。
5. **前端并发固定 3**：未做网络自适应。
