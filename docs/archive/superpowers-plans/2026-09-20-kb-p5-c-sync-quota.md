# KB-P5-C 外部数据源同步纳入配额校验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让外部数据源手动/自动同步的产物纳入用户存储配额：同步前按本次内容字节预占配额（超限拒绝并标 FAILED），写入成功后按实际字节入账；失败回滚预占。与用户自传/分片上传同一配额口径。

**Architecture:** [external_data_source_service.py](../../../api/internal/service/external_data_source_service.py) `manual_sync()` 当前零配额调用。改造：在写第一个 `KnowledgeDocument` 前，统计本次 `documents` 全部内容字节（`sum(len((content or "").encode("utf-8")) for d in documents)`），调 `StorageQuotaService.consume_quota(account.id, incoming_bytes)`（原子「校验+累加」，超限抛 `ForbiddenException` → 标记 `sync_status=FAILED` + `last_error`）；写库成功后在 `finally`/正常路径按**实际写入字节**修正入账（实际内容字符数）。复用 `chunked_upload_service` 的预占-回滚范式（`consume_quota` + `release_usage`）。

**Tech Stack:** Python 3.12 / injector / pytest

---

## 0. 现状核对摘要（2026-09-20 实测）

| 事实 | 依据 |
| --- | --- |
| `manual_sync()` 现同步流程：`_get_owned_data_source` → 校验授权 → `connector.sync` 取文档列表 → 逐文档建 `KnowledgeDocument` + `_split_document` 分段 + `_index_segment_safely` **全程无配额调用** | [external_data_source_service.py](../../../api/internal/service/external_data_source_service.py) L86-150 |
| 同步产物：DB 文档/分段文本 + pgvector 向量，**不写 COS**（无 UploadFile/帧） | 同上（`create(KnowledgeDocument...)` / `create(KnowledgeSegment...)`） |
| 原子预占范式：`consume_quota(account_id, incoming_bytes, reserve_bytes=...)` 行锁内校验+累加；异常时 `release_usage` 回滚 | [chunked_upload_service.py](../../../api/internal/service/chunked_upload_service.py) L172-199 |
| `StorageQuotaService` 方法：`consume_quota` / `release_usage` / `add_usage` / `check_quota` / `get_usage_summary` | [storage_quota_service.py](../../../api/internal/service/storage_quota_service.py) |
| `ExternalDataSourceService` 构造函数当前不注入 `StorageQuotaService` | `external_data_source_service.py` L36 |
| 失败同步语义：`sync_status=FAILED` + `last_error` 返回（connector 异常已处理） | L94-101 |

**本计划不涉及**：新表/迁移、新建文档逻辑、连接器行为、前端。

---

## 1. 文件结构规划

| 文件 | 职责 |
| --- | --- |
| Modify: `api/internal/service/external_data_source_service.py` | 构造注入 `StorageQuotaService`；`manual_sync()` 配额预占/回滚/入账 |
| Modify: `api/test/internal/service/test_external_data_source_service.py` | 新增配额用例（超限拒绝 / 正常入账 / 失败回滚） |
| Modify: `api/test/internal/service/test_storage_quota_service.py` | 如口径需要补测 |

> 同步还有 Celery 定时路径（每 6 小时自动同步）——核对它是否复用 `manual_sync`/同一写入方法；若独立实现则同样接入。**实现时以调用链实测为准**。

---

## Task C1: 写失败的测试

**Files:**
- Modify: `api/test/internal/service/test_external_data_source_service.py`

- [ ] **Step 1: 追加测试（先读该文件现有夹具：mock connector / fake db 怎么构造，照抄）**

```python
def test_sync_rejects_when_quota_exceeded(monkeypatch):
    """配额不足时同步应被拒绝且数据源标记 FAILED（不写任何文档）。"""
    # 沿用文件既有 `_make_service(...)` 夹具（含 fake connector 返回 2 个文档）
    # 注入 FakeQuota：consume_quota 抛 ForbiddenException
    quota = _FakeQuota(raise_exc=ForbiddenException("存储空间不足，请扩容"))
    service = _make_service(quota=quota)
    data_source = _make_data_source(authorization_status="granted")
    account = _make_account()

    result = service.manual_sync(data_source.id, account)

    assert result["sync_status"] == "failed"
    assert "空间不足" in result["last_error"]
    quota.consume_called is True
    # 未创建任何文档
    assert len(_created_documents(service)) == 0


def test_sync_validates_and_counts_content_bytes(monkeypatch):
    """正常同步：预占字节 = 本次文档内容 utf-8 字节总和，并转入 actual 入账。"""
    quota = _FakeQuota(limit=10_000)
    service = _make_service(quota=quota, documents=[{"name": "a.md", "content": "你好"}])
    data_source = _make_data_source(authorization_status="granted")

    result = service.manual_sync(data_source.id, _make_account())

    assert result["sync_status"] == "success"
    assert quota.consume_bytes >= 6  # "你好" utf-8 = 6 bytes（含其余文档按实际）
    assert quota.released is False  # 成功路径不释放，按实际入账


def test_sync_releases_pre_reserved_quota_on_write_failure(monkeypatch):
    """connector 成功但写库/索引抛异常时应释放预占配额。"""
    quota = _FakeQuota(limit=10_000)
    service = _make_service(quota=quota, documents=[{"name": "boom.md", "content": "x"}],
                            write_error=RuntimeError("db down"))
    data_source = _make_data_source(authorization_status="granted")

    # manual_sync 对写库异常应捕获并返回 failed（沿既有失败语义）
    result = service.manual_sync(data_source.id, _make_account())

    assert result["sync_status"] == "failed"
    assert quota.released is True
```

> 夹具细节（`_FakeQuota` 的 raise_exc/released/consume_bytes 字段、`_make_service` 注入 quota 的方式）以该文件**既有夹具风格**为准，实现时先读测试文件再落地；上面是契约骨架，不是照抄模板。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_external_data_source_service.py -k quota_or_sync -v`
Expected: FAIL — `ForbiddenException` 未抛 或 consume 未调用

---

## Task C2: 实现配额接入

**Files:**
- Modify: `api/internal/service/external_data_source_service.py`

- [ ] **Step 1: 构造注入**

```python
    @inject
    def __init__(
        self,
        db: SQLAlchemy,
        connector=None,
        knowledge_vector_service: KnowledgeVectorService = None,
        storage_quota_service=None,
    ):
        self.db = db
        self.connector = connector
        self.connector_factory = ConnectorFactory()
        self.knowledge_vector_service = knowledge_vector_service
        self.storage_quota_service = storage_quota_service
```

> `storage_quota_service` 注入：module.py 已 bind `StorageQuotaService` 单例（L122），injector 自动注入。测试夹具若不传入则回落 None（走原逻辑，既有用例不回归）。

- [ ] **Step 2: `manual_sync()` 接入配额（核心改写）**

在 `documents = connector.sync(...)` 成功之后、`for document in documents:` 之前插入：

```python
        segment_count = 0
        operation_context = OperationContext.USER.value
        knowledge_base = self._get_knowledge_base(data_source.knowledge_base_id)

        # ── 外部数据源同步纳入存储配额（KB-P5-C）──
        # 同步产物为 DB 文档/分段文本 + 向量，不落 COS；按本次内容 utf-8 字节
        # 原子预占（校验+累加），超限即拒绝并标记 FAILED。口径对齐分片上传的
        # consume_quota / release_usage 范式。
        incoming_bytes = sum(
            len(str(doc.get("content") or "").encode("utf-8")) for doc in documents
        )
        quota_consumed = False
        try:
            if incoming_bytes > 0 and self.storage_quota_service is not None:
                self.storage_quota_service.consume_quota(account.id, incoming_bytes)
                quota_consumed = True
        except Exception as exc:  # ForbiddenException 及存储层异常一并可读化
            data_source.sync_status = ExternalSyncStatus.FAILED.value
            data_source.last_error = f"存储配额不足或扣减失败：{exc}"
            return {
                "sync_status": data_source.sync_status,
                "document_count": 0,
                "last_error": data_source.last_error,
            }
```

在循环写库完成后（`data_source.sync_status = ExternalSyncStatus.SUCCESS.value` 之前），把成功入账字节改为**实际写入**并防止总超账：

```python
        # 成功路径：实际写入字节可能小于预占（connector 多报内容），以实际入账。
        # 预占已含全部字节，不再额外 add_usage；如需精确可在实现时用
        # storage_quota_service.release_usage(account.id, incoming_bytes - actual)
        # 释放高估部分——**以验收口径「成功同步不超总量、失败不残留占位」为准**。
```

`except Exception` 兜底（覆盖写库/索引异常）中，若 `quota_consumed` 为 True 则释放预占（沿用 chunked_upload 范式）：

```python
        except Exception as exc:
            if quota_consumed and self.storage_quota_service is not None:
                try:
                    self.storage_quota_service.release_usage(account.id, incoming_bytes)
                except Exception:
                    logger.warning("释放外部数据源同步预占配额失败", exc_info=True)
            raise
```

> **实现前核对**：
> 1. `manual_sync` 现有 `except` 结构：要把「connector.sync 异常」与「写库异常」分开处理（现有 L92-101 只包 connector 调用；写库异常当前未捕获）。确保写库失败也走 FAILED + 释放预占，而不是裸抛打断定时任务。
> 2. `_index_segment_safely` 是否已有内部 try/except（失败不阻断）；若它吞掉异常，写库异常主要发生在 `create` 上，验收按 create 异常考虑。
> 3. 自动同步（Celery 定时）入口是否复用 `manual_sync`：搜 `manual_sync` 的调用方（route + celery），若有独立自动同步方法也要接同一配额（实现时以实测调用链为准，找不到独立方法则此条 N/A）。

- [ ] **Step 3: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_external_data_source_service.py -v`
Expected: PASS（既有同步用例 + 3 个新配额用例）

---

## Task C3: 回归 + 接线自检 + 文档同步

- [ ] **Step 1: 全量回归** — `cd api && python -m pytest -q`（基线 5200+ passed；2 个既有环境失败不修）
- [ ] **Step 2: 接线自检**

| 新符号 | 入口 |
| --- | --- |
| `manual_sync` 配额预占/释放 | 同步链路唯一入口：`POST /external-data-sources/<id>/sync` route → `manual_sync`（既有）；Celery 定时同步调用方实现时确认 |

- [ ] **Step 3: 文档同步** — `docs/prd/modules/02-knowledge-base.md`（外部数据源小节补「同步产物纳入存储配额」）、`docs/prd/knowledge-base-product-form-design.md` §9.2 KB-P5 行、`docs/prd/execution-roadmap.md`（KB-P5 行补 KB-P5-C）
- [ ] **Step 4: graphify** — `python -m graphify update .`
- [ ] **Step 5: Commit（docs 单独）**

---

## Self-Review 备注

- **验收口径**：配额不足同步被拒且不产生孤儿文档；正常同步用量正确（预占后按实际入账、不超总量）；失败（connector 或写库）释放预占；既有同步用例不回归。
- **数量口径**：以「内容 utf-8 字节」为同步占用单位（DB 文本 + 向量近似），不引入新表。
- **延后项**：按真实存储字节计量需要统计 pgvector 向量占用，本计划按内容字节近似（与产品验收一致）。