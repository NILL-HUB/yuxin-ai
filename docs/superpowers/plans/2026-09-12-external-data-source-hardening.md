# 外部数据源前后端加固 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让知识库页的「外部数据源」弹窗使用真实接口，并修复凭证明文落库/回传、授权不落库、级联清理缺失等后端安全与一致性缺口。

**Architecture:** 新增凭证处理模块（敏感 key 加解密 + 脱敏），服务层在落库前加密、调连接器前解密、API 返回前脱敏；连接器增加可选 `config` 形参以接收解密后配置；回收站删除路径按 `source_type + source_id` 级联清理同步产物；新增 Celery 定时任务做自动同步；前端删除不可用的独立页面，把弹窗接线为唯一真实入口。

**Tech Stack:** Python 3.12 + SQLAlchemy 2 + Alembic + Celery + marshmallow + pytest；Vue 3 + TypeScript + vitest。

**Spec:** `docs/superpowers/specs/2026-09-12-external-data-source-design.md`

---

## 文件结构

**新增**

| 文件 | 职责 |
| --- | --- |
| `api/internal/service/external_data_source_credentials.py` | 敏感 key 加密/解密/脱敏集中处理 |
| `api/internal/task/external_data_source_tasks.py` | 定时自动同步任务 |
| `api/internal/migration/versions/m7b8c9d0e1f2_encrypt_external_data_source_credentials.py` | 历史凭证加密回填 + 清理 enterprise_knowledge |
| `api/test/internal/service/test_external_data_source_credentials.py` | 凭证模块单测 |
| `api/test/internal/task/test_external_data_source_tasks.py` | 定时任务单测 |

**修改**

| 文件 | 职责 |
| --- | --- |
| `api/internal/service/external_data_source_service.py` | 落库加密、授权落库、同步解密、`auto_sync_all` |
| `api/internal/service/connectors/base_connector.py` | 抽象签名增加 `config` 形参 |
| `api/internal/service/connectors/{lark,notion,github,local_folder}_connector.py` | 读解密后配置 |
| `api/internal/service/external_data_source_connector_factory.py` | 移除 enterprise_knowledge |
| `api/internal/entity/knowledge_entity.py` | 移除 `ExternalSourceType.ENTERPRISE_KNOWLEDGE` |
| `api/internal/service/recycle_bin_handlers.py` | 级联清理同步产物 |
| `api/app/http/knowledge_mcp_routes.py` | 响应脱敏 |
| `api/app/http/celery_app.py` | 注册任务模块与 beat |
| `api/test/internal/service/test_external_data_source_service.py` | 适配与新增用例 |
| `api/test/internal/service/test_external_data_source_connector.py` | 适配签名 |
| `ui/src/services/external-data-source.ts` | 列表类型修正 |
| `ui/src/views/space/datasets/components/ExternalDataSourceModal.vue` | 接真实接口 |
| `ui/src/i18n/messages/{zh-CN,en-US}/externalDataSource.ts` | 增删键 |

**删除**

- `api/internal/service/external_data_retrieval_tool.py` + 其单测
- `api/internal/schema/knowledge_schema.py`（无引用死代码）
- `ui/src/views/external-data-sources/`（整个目录）+ 路由注册

---

### Task 1: 新增凭证处理模块

**Files:**
- Create: `api/internal/service/external_data_source_credentials.py`
- Test: `api/test/internal/service/test_external_data_source_credentials.py`

- [ ] **Step 1: 写失败的测试**

新建 `api/test/internal/service/test_external_data_source_credentials.py`：

```python
"""外部数据源凭证处理测试：加密/解密/脱敏。"""

from internal.service.external_data_source_credentials import (
    SENSITIVE_KEYS,
    decrypt_config,
    encrypt_config,
    mask_config,
)


def test_encrypt_then_decrypt_roundtrip():
    config = {"app_id": "cli_x", "app_secret": "super-secret", "folder_token": "ftok"}
    encrypted = encrypt_config(config)

    assert encrypted["app_id"] == "cli_x"
    assert encrypted["folder_token"] == "ftok"
    assert encrypted["app_secret"] != "super-secret"
    assert encrypted["app_secret"].startswith("gAAAAA")

    assert decrypt_config(encrypted) == config


def test_encrypt_is_idempotent():
    once = encrypt_config({"app_secret": "s3cr3t"})
    twice = encrypt_config(once)

    assert twice["app_secret"] == once["app_secret"]


def test_non_sensitive_keys_stay_plaintext():
    config = {"folder_path": "/data/docs", "owner": "acme", "repo": "acme/docs"}
    encrypted = encrypt_config(config)

    assert encrypted == config


def test_decrypt_keeps_plaintext_secret_as_is():
    """未加密（历史明文/迁移未覆盖）的敏感值应原样返回，不得被清空。"""
    config = {"app_secret": "still-plain-secret", "app_id": "cli_x"}
    decrypted = decrypt_config(config)

    assert decrypted["app_secret"] == "still-plain-secret"
    assert decrypted["app_id"] == "cli_x"


def test_decrypt_degrades_single_key_on_failure():
    """看起来是密文（gAAAAA 前缀）但解密失败时，该 key 降级为空串。"""
    config = {"app_secret": "gAAAAA-invalid-token-value", "app_id": "cli_x"}
    decrypted = decrypt_config(config)

    assert decrypted["app_secret"] == ""
    assert decrypted["app_id"] == "cli_x"


def test_mask_config_hides_secrets_and_masks_decrypted():
    masked = mask_config(encrypt_config({"app_secret": "super-secret", "app_id": "cli_x"}))

    assert masked["app_id"] == "cli_x"
    assert masked["app_secret"] != "super-secret"
    assert "super-secret" not in masked["app_secret"]
    assert "*" in masked["app_secret"]


def test_sensitive_keys_cover_all_connector_secret_fields():
    # lark / notion / github 使用的凭证字段都必须在敏感集合内
    assert {"app_secret", "integration_token", "personal_access_token", "token", "api_key"} <= SENSITIVE_KEYS
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_external_data_source_credentials.py -q --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'internal.service.external_data_source_credentials'`

- [ ] **Step 3: 实现凭证模块**

新建 `api/internal/service/external_data_source_credentials.py`：

```python
"""外部数据源凭证处理：对 config 中的敏感 key 做 Fernet 加密/解密/脱敏。

复用 tool_credential_encryptor 的 Fernet 能力（MODEL_KEY_ENCRYPTION_KEY），
仅加密约定敏感 key；非敏感配置（folder_path/owner/repo/database_id 等）
保持明文，保证可读与可查询。
"""
from __future__ import annotations

import logging
from typing import Any

from internal.service.tool_credential_encryptor import (
    _decrypt_value,
    _encrypt_value,
    _mask_value,
    is_encrypted,
)

logger = logging.getLogger(__name__)

# 需要加密存储的 config key（覆盖 lark/notion/github 的全部凭证字段）
SENSITIVE_KEYS = frozenset(
    {
        "app_secret",
        "integration_token",
        "personal_access_token",
        "api_key",
        "token",
        "client_secret",
    }
)


def encrypt_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """加密敏感 key 的值；已加密（gAAAAA 前缀）跳过，保证幂等。"""
    if not config:
        return {}
    result: dict[str, Any] = {}
    for key, value in config.items():
        if key in SENSITIVE_KEYS and isinstance(value, str) and value and not is_encrypted(value):
            result[key] = _encrypt_value(value)
        else:
            result[key] = value
    return result


def decrypt_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """解密敏感 key，供连接器调用外部 API；单 key 解密失败降级为空串并告警。

    仅对「已加密」的值解密；未加密（历史明文或迁移未覆盖）的值原样返回，
    避免把仍在使用的明文凭证误清空。
    """
    if not config:
        return {}
    result: dict[str, Any] = {}
    for key, value in config.items():
        if key in SENSITIVE_KEYS and isinstance(value, str) and value and is_encrypted(value):
            try:
                result[key] = _decrypt_value(value)
            except ValueError:
                logger.warning("外部数据源凭证解密失败 key=%s，已降级为空串", key)
                result[key] = ""
        else:
            result[key] = value
    return result


def mask_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """脱敏输出：敏感 key 一律返回掩码（不区分明文/密文），用于 API 返回。"""
    if not config:
        return {}
    result: dict[str, Any] = {}
    for key, value in config.items():
        if key in SENSITIVE_KEYS and isinstance(value, str) and value:
            real = value
            if is_encrypted(value):
                try:
                    real = _decrypt_value(value)
                except ValueError:
                    real = ""
            result[key] = _mask_value(real)
        else:
            result[key] = value
    return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_external_data_source_credentials.py -q --no-cov`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/external_data_source_credentials.py api/test/internal/service/test_external_data_source_credentials.py
git commit -m "feat(external-data-source): add credential encrypt/decrypt/mask helpers"
```

---

### Task 2: 连接器接收解密后配置

**Files:**
- Modify: `api/internal/service/connectors/base_connector.py`
- Modify: `api/internal/service/connectors/lark_connector.py`
- Modify: `api/internal/service/connectors/notion_connector.py`
- Modify: `api/internal/service/connectors/github_connector.py`
- Modify: `api/internal/service/connectors/local_folder_connector.py`
- Test: `api/test/internal/service/test_external_data_source_connector.py`

> 理由：加密后 `data_source.config` 内敏感 key 为密文；连接器 `authorize` 与 `sync` 都回退读 `data_source.config`，因此两者都必须能接收解密后的配置。

- [ ] **Step 1: 写失败的测试**

在 `api/test/internal/service/test_external_data_source_connector.py` 末尾追加：

```python
def test_connectors_prefer_explicit_config_over_data_source_config():
    """传入显式 config 时，应优先使用它（而非 data_source.config）。"""
    from internal.service.connectors.local_folder_connector import LocalFolderConnector
    import tempfile

    folder = tempfile.mkdtemp()
    data_source = SimpleNamespace(config={"folder_path": "/nonexistent-should-be-ignored"})

    # 显式传入有效目录，sync 应使用它而非 data_source.config
    connector = LocalFolderConnector()
    documents = connector.sync(data_source, config={"folder_path": folder})

    assert isinstance(documents, list)
```

（若文件顶部未导入 `SimpleNamespace`，补 `from types import SimpleNamespace`。）

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_external_data_source_connector.py -q --no-cov`
Expected: FAIL — `TypeError: sync() got an unexpected keyword argument 'config'`

- [ ] **Step 3: 改抽象基类**

修改 `api/internal/service/connectors/base_connector.py`，两个抽象方法签名改为：

```python
class BaseConnector(ABC):
    @abstractmethod
    def authorize(
        self,
        data_source: ExternalDataSource,
        auth_config: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> str:
        ...

    @abstractmethod
    def sync(
        self,
        data_source: ExternalDataSource,
        config: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        """config 为空时回退读取 data_source.config（保持既有调用兼容）。"""
        ...
```

- [ ] **Step 4: 改 4 个连接器**

**`local_folder_connector.py`** — `authorize`（原 L38-48）与 `sync`（原 L50-53）改为：

```python
    def authorize(
        self,
        data_source: ExternalDataSource,
        auth_config: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> str:
        resolved = config if config is not None else (data_source.config or {})
        folder_path = self._resolve_folder(
            auth_config.get("folder_path") or resolved.get("folder_path", "")
        )
        if not folder_path or not os.path.isdir(folder_path):
            raise ValueError("文件夹路径无效或不存在")
        return ExternalAuthorizationStatus.GRANTED.value

    def sync(
        self,
        data_source: ExternalDataSource,
        config: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        resolved = config if config is not None else (data_source.config or {})
        folder_path = self._resolve_folder(resolved.get("folder_path", ""))
        if not folder_path or not os.path.isdir(folder_path):
            raise ValueError("文件夹路径无效或不存在")
        # 后续函数体保持原有逻辑不变
```

**`lark_connector.py`** — `authorize`（原 L32-41）与 `sync`（原 L43-51）改为：

```python
    def authorize(
        self,
        data_source: ExternalDataSource,
        auth_config: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> str:
        resolved = config if config is not None else (data_source.config or {})
        app_id = auth_config.get("app_id") or resolved.get("app_id", "")
        app_secret = auth_config.get("app_secret") or resolved.get("app_secret", "")
        if not app_id or not app_secret:
            raise ValueError("飞书连接需要 app_id 和 app_secret")
        return ExternalAuthorizationStatus.GRANTED.value

    def sync(
        self,
        data_source: ExternalDataSource,
        config: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        resolved = config if config is not None else (data_source.config or {})
        app_id = resolved.get("app_id", "")
        app_secret = resolved.get("app_secret", "")
        # 后续函数体保持原有逻辑不变（原 config = data_source.config 一行删除）
```

**`notion_connector.py`** — `authorize`（原 L48-52 附近）与 `sync`（原 L58-60 附近）改为：

```python
    def authorize(
        self,
        data_source: ExternalDataSource,
        auth_config: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> str:
        resolved = config if config is not None else (data_source.config or {})
        integration_token = (
            auth_config.get("integration_token")
            or resolved.get("integration_token", "")
        )
        if not integration_token:
            raise ValueError("Notion 连接需要 integration_token")
        return ExternalAuthorizationStatus.GRANTED.value

    def sync(
        self,
        data_source: ExternalDataSource,
        config: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        config = config if config is not None else (data_source.config or {})
        integration_token = config.get("integration_token", "")
        # 后续函数体保持原有逻辑不变
```

**`github_connector.py`** — `authorize`（原 L35-46）与 `sync`（原 L48-50）改为：

```python
    def authorize(
        self,
        data_source: ExternalDataSource,
        auth_config: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> str:
        resolved = config if config is not None else (data_source.config or {})
        # 兼容 token / personal_access_token 两种字段名（与 sync 保持一致）
        token = (
            auth_config.get("token")
            or auth_config.get("personal_access_token")
            or resolved.get("token", "")
            or resolved.get("personal_access_token", "")
        )
        repo = auth_config.get("repo") or resolved.get("repo", "")
        if not token or not repo:
            raise ValueError("GitHub 连接需要 token 和 repo（owner/repo 格式）")
        if "/" not in repo:
            raise ValueError("repo 需为 owner/repo 格式")
        return ExternalAuthorizationStatus.GRANTED.value

    def sync(
        self,
        data_source: ExternalDataSource,
        config: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        config = config if config is not None else (data_source.config or {})
        # 后续函数体保持原有逻辑不变
```

> 该改动修正了一个既有集成缺陷：`sync` 已兼容 `personal_access_token`，但 `authorize` 只认 `token`，导致前端提交 `personal_access_token` 时授权必然失败。前端字段对齐见 Task 13。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_external_data_source_connector.py -q --no-cov`
Expected: PASS（含新增用例）

- [ ] **Step 6: 提交**

```bash
git add api/internal/service/connectors/ api/test/internal/service/test_external_data_source_connector.py
git commit -m "refactor(connectors): accept decrypted config via optional param"
```

---

### Task 3: 服务层加密落库 + 授权落库 + 同步解密

**Files:**
- Modify: `api/internal/service/external_data_source_service.py`
- Test: `api/test/internal/service/test_external_data_source_service.py`

- [ ] **Step 1: 扩展测试桩（`add`/`commit`）**

`authorize_data_source` 新增了显式落库，测试用的 `_SessionStub` 目前没有 `add`/`commit`，需先补齐（对既有用例无副作用）。

修改 `api/test/internal/service/test_external_data_source_service.py` 的 `_SessionStub`：

```python
class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])
        self.added = []
        self.commits = 0

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1
```

- [ ] **Step 2: 写失败的测试**

在 `api/test/internal/service/test_external_data_source_service.py` 末尾追加：

```python
def test_create_connection_should_encrypt_sensitive_config(monkeypatch):
    account_id = uuid4()
    service = ExternalDataSourceService(db=_fake_db(_SessionStub()))
    created = []
    monkeypatch.setattr(
        service,
        "create",
        lambda model, **kwargs: created.append((model, kwargs)) or SimpleNamespace(**kwargs),
    )

    service.create_connection(
        account=SimpleNamespace(id=account_id),
        knowledge_base=SimpleNamespace(id=uuid4(), owner_account_id=account_id, knowledge_scope="user_content"),
        source_type="lark",
        source_name="Lark",
        config={"app_id": "cli_x", "app_secret": "plain-secret"},
    )

    config = created[0][1]["config"]
    assert config["app_id"] == "cli_x"
    assert config["app_secret"] != "plain-secret"
    assert config["app_secret"].startswith("gAAAAA")


def test_authorize_should_persist_auth_config_encrypted(monkeypatch):
    account_id = uuid4()
    data_source = SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        source_type="lark",
        authorization_status="pending",
        config={},
    )
    service = ExternalDataSourceService(db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=data_source)])))

    class _Connector:
        def authorize(self, ds, auth_config, config=None):
            assert config is not None, "连接器必须收到解密后的配置"
            return "granted"

    monkeypatch.setattr(service.connector_factory, "get_connector", lambda _t: _Connector())

    service.authorize_data_source(data_source.id, SimpleNamespace(id=account_id), {"app_secret": "new-secret"})

    assert data_source.authorization_status == "granted"
    assert data_source.config["app_secret"] != "new-secret"
    assert data_source.config["app_secret"].startswith("gAAAAA")


def test_manual_sync_should_pass_decrypted_config_to_connector(monkeypatch):
    account_id = uuid4()
    from internal.service.external_data_source_credentials import encrypt_config

    data_source = SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        knowledge_base_id=uuid4(),
        source_type="mock",
        source_name="Mock",
        sync_status="idle",
        authorization_status="granted",
        sync_cursor="",
        last_error="",
        config=encrypt_config({"app_secret": "plain-secret"}),
    )
    seen = {}

    class _Connector:
        def sync(self, ds, config=None):
            seen["secret"] = (config or {}).get("app_secret")
            return []

    service = ExternalDataSourceService(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=data_source)])),
        connector=_Connector(),
    )
    monkeypatch.setattr(service, "_get_knowledge_base", lambda _id: None)

    service.manual_sync(data_source.id, SimpleNamespace(id=account_id))

    assert seen["secret"] == "plain-secret"
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_external_data_source_service.py -q --no-cov`
Expected: FAIL —加密断言失败（当前 config 明文落库）/ 连接器未收到 config

- [ ] **Step 4: 实现服务层改动**

修改 `api/internal/service/external_data_source_service.py`：

顶部导入区加入：

```python
from internal.service.external_data_source_credentials import (
    decrypt_config,
    encrypt_config,
)
```

`create_connection` 的返回处（原 `config={**config, "operation_context": ...}`）改为：

```python
            config=encrypt_config({**config, "operation_context": OperationContext.USER.value}),
```

`authorize_data_source` 整体替换为：

```python
    def authorize_data_source(
        self,
        data_source_id,
        account: Account,
        auth_config: dict,
    ) -> ExternalDataSource:
        data_source = self._get_owned_data_source(data_source_id, account)
        # 把本次提交的凭证合并进 config 并加密落库，避免「先创建后授权」时凭证丢失
        merged = {**(data_source.config or {}), **(auth_config or {})}
        data_source.config = encrypt_config(merged)
        connector = self.connector_factory.get_connector(data_source.source_type)
        data_source.authorization_status = connector.authorize(
            data_source,
            auth_config or {},
            config=decrypt_config(data_source.config),
        )
        self.db.session.add(data_source)
        self.db.session.commit()
        return data_source
```

`manual_sync` 中连接器调用处改为：

```python
        connector = self.connector or self.connector_factory.get_connector(data_source.source_type)
        data_source.sync_status = ExternalSyncStatus.SYNCING.value
        try:
            documents = connector.sync(data_source, config=decrypt_config(data_source.config))
```

- [ ] **Step 5: 适配 `MockExternalConnector`**

`create_connection` / `manual_sync` 改动后，既有用例依赖的 `MockExternalConnector.sync(self, data_source)` 不接收 `config`，需补签名（对既有调用无影响）。修改同文件中的 `MockExternalConnector`：

```python
class MockExternalConnector:
    def __init__(self, documents: list[dict[str, str]] | None = None):
        self.documents = documents or []

    def sync(self, data_source: ExternalDataSource, config: dict | None = None) -> list[dict[str, str]]:
        return self.documents
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_external_data_source_service.py -q --no-cov`
Expected: PASS（全部，含新增 3 个用例）

> 若仍有失败，检查 `_FailingExternalConnector.sync` 是否也需补 `config=None` 形参（同类签名变更）。

- [ ] **Step 7: 提交**

```bash
git add api/internal/service/external_data_source_service.py api/test/internal/service/test_external_data_source_service.py
git commit -m "fix(external-data-source): encrypt config at rest and persist auth credentials"
```

---

### Task 4: 新增 `auto_sync_all` 服务方法

**Files:**
- Modify: `api/internal/service/external_data_source_service.py`
- Test: `api/test/internal/service/test_external_data_source_service.py`

- [ ] **Step 1: 写失败的测试**

追加（注意：候选筛选发生在 `_list_auto_sync_candidates` 的 DB 过滤里，故本用例 monkeypatch 该方法只返回 1 条候选；`Account` 查询需提供 owner 否则会被跳过）：

```python
def test_auto_sync_all_isolates_failures(monkeypatch):
    owner_id = uuid4()
    granted = SimpleNamespace(id=uuid4(), owner_account_id=owner_id, authorization_status="granted", sync_status="idle")

    # Account 查询返回 owner，避免被 auto_sync_all 跳过
    session = _SessionStub([_QueryStub(one_or_none_result=SimpleNamespace(id=owner_id))])
    service = ExternalDataSourceService(db=_fake_db(session))
    monkeypatch.setattr(service, "_list_auto_sync_candidates", lambda: [granted])
    monkeypatch.setattr(
        service,
        "manual_sync",
        lambda ds_id, account, **kw: {"sync_status": "success", "document_count": 1, "segment_count": 2},
    )

    result = service.auto_sync_all()

    assert result == {"scanned": 1, "synced": 1, "failed": 0}


def test_auto_sync_all_counts_failures_without_raising(monkeypatch):
    owner_id = uuid4()
    broken = SimpleNamespace(id=uuid4(), owner_account_id=owner_id, authorization_status="granted", sync_status="idle")

    session = _SessionStub([_QueryStub(one_or_none_result=SimpleNamespace(id=owner_id))])
    service = ExternalDataSourceService(db=_fake_db(session))
    monkeypatch.setattr(service, "_list_auto_sync_candidates", lambda: [broken])

    def _boom(ds_id, account, **kw):
        raise RuntimeError("connector down")

    monkeypatch.setattr(service, "manual_sync", _boom)

    result = service.auto_sync_all()

    assert result == {"scanned": 1, "synced": 0, "failed": 1}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_external_data_source_service.py -q --no-cov`
Expected: FAIL — `AttributeError: 'ExternalDataSourceService' object has no attribute 'auto_sync_all'`

- [ ] **Step 3: 实现 `auto_sync_all` 与候选查询**

在 `external_data_source_service.py` 的 `delete_data_source` 之后插入：

```python
    def _list_auto_sync_candidates(self) -> list[ExternalDataSource]:
        """自动同步候选：已授权且当前不在同步中的全部数据源（跨账号）。"""
        return (
            self.db.session.query(ExternalDataSource)
            .filter(
                ExternalDataSource.authorization_status == ExternalAuthorizationStatus.GRANTED.value,
                ExternalDataSource.sync_status != ExternalSyncStatus.SYNCING.value,
            )
            .all()
        )

    def auto_sync_all(self) -> dict[str, int]:
        """定时任务入口：逐个同步候选数据源，单条失败不影响其他。

        Returns:
            ``{"scanned": int, "synced": int, "failed": int}``
        """
        candidates = self._list_auto_sync_candidates()
        synced = 0
        failed = 0
        for data_source in candidates:
            owner = (
                self.db.session.query(Account)
                .filter(Account.id == data_source.owner_account_id)
                .one_or_none()
            )
            if owner is None:
                continue
            try:
                result = self.manual_sync(data_source.id, owner)
                if result.get("sync_status") == ExternalSyncStatus.SUCCESS.value:
                    synced += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
                logger.warning(
                    "外部数据源自动同步失败 data_source_id=%s", data_source.id, exc_info=True
                )
        return {"scanned": len(candidates), "synced": synced, "failed": failed}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_external_data_source_service.py -q --no-cov`
Expected: PASS（含新增 2 个用例）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/external_data_source_service.py api/test/internal/service/test_external_data_source_service.py
git commit -m "feat(external-data-source): add auto_sync_all for scheduled sync"
```

---

### Task 5: 移除 `enterprise_knowledge`

**Files:**
- Modify: `api/internal/entity/knowledge_entity.py`
- Modify: `api/internal/service/external_data_source_connector_factory.py`
- Test: `api/test/internal/service/test_external_data_source_connector.py`

- [ ] **Step 1: 写失败的测试**

追加：

```python
def test_connector_factory_rejects_removed_enterprise_knowledge():
    from internal.service.external_data_source_connector_factory import ConnectorFactory

    with pytest.raises(ValueError):
        ConnectorFactory().get_connector("enterprise_knowledge")


def test_external_source_type_no_longer_has_enterprise_knowledge():
    from internal.entity.knowledge_entity import ExternalSourceType

    assert not hasattr(ExternalSourceType, "ENTERPRISE_KNOWLEDGE")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_external_data_source_connector.py -q --no-cov`
Expected: FAIL — 工厂仍能返回该类型 / 枚举仍存在

- [ ] **Step 3: 移除枚举与工厂注册**

`api/internal/entity/knowledge_entity.py`，从 `ExternalSourceType` 删除：

```python
    ENTERPRISE_KNOWLEDGE = "enterprise_knowledge"
```

`api/internal/service/external_data_source_connector_factory.py`，从 `_registry` 删除：

```python
        ExternalSourceType.ENTERPRISE_KNOWLEDGE.value: LocalFolderConnector,
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_external_data_source_connector.py -q --no-cov`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/entity/knowledge_entity.py api/internal/service/external_data_source_connector_factory.py api/test/internal/service/test_external_data_source_connector.py
git commit -m "feat(external-data-source): remove unimplemented enterprise_knowledge type"
```

---

### Task 6: 级联清理同步产物

**Files:**
- Modify: `api/internal/service/recycle_bin_handlers.py`
- Test: `api/test/internal/service/test_recycle_bin_handlers.py`

- [ ] **Step 1: 补导入并写失败的测试**

该测试文件已导入 `SimpleNamespace` 与 `handlers`，但缺 `uuid4`。先把首行改为：

```python
from types import SimpleNamespace
from uuid import uuid4
```

然后在 `api/test/internal/service/test_recycle_bin_handlers.py` 末尾追加：

```python
def test_delete_documents_by_source_removes_matching_docs_and_segments(monkeypatch):
    """按 source_type + source_id 清理，且必须经 injector 取向量服务。"""
    from internal.service import recycle_bin_handlers as handlers

    doc = SimpleNamespace(id=uuid4(), upload_file_id=None)
    segment = SimpleNamespace(id=uuid4())
    removed = {"vector": [], "deleted_models": []}

    class _Query:
        def __init__(self, result):
            self._result = result

        def filter(self, *_a, **_k):
            return self

        def all(self):
            return self._result if isinstance(self._result, list) else []

        def one_or_none(self):
            return self._result

        def delete(self, **_k):
            removed["deleted_models"].append(self._result)
            return 1

    class _Session:
        def query(self, model, *_a, **_k):
            name = getattr(model, "__name__", str(model))
            if name == "KnowledgeDocument":
                return _Query([doc])
            if name == "KnowledgeSegment":
                return _Query([segment])
            return _Query(None)

        def commit(self):
            pass

    monkeypatch.setattr(handlers, "db", SimpleNamespace(session=_Session()))

    class _Vector:
        def remove_segment(self, seg):
            removed["vector"].append(seg.id)

    monkeypatch.setattr(
        handlers, "_get_knowledge_vector_service", lambda: _Vector(), raising=False
    )

    count = handlers._delete_documents_by_source("lark", "ds-1")

    assert count == 1
    assert removed["vector"] == [segment.id]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_recycle_bin_handlers.py::test_delete_documents_by_source_removes_matching_docs_and_segments -q --no-cov`
Expected: FAIL — `AttributeError: module ... has no attribute '_delete_documents_by_source'`

- [ ] **Step 3: 实现清理函数**

在 `api/internal/service/recycle_bin_handlers.py` 的 `external_data_source` 区块（`snapshot_external_data_source` 之前）插入：

```python
def _get_knowledge_vector_service():
    """经 DI 容器获取向量服务（避免无参构造失败被静默吞掉）。"""
    from app.http.module import injector
    from internal.service.knowledge_vector_service import KnowledgeVectorService

    return injector.get(KnowledgeVectorService)


def _delete_documents_by_source(source_type: str, source_id: str) -> int:
    """按 source_type + source_id 清理同步产物：向量 + 分段 + 文档 + 上传文件。

    复用已有索引 knowledge_document_source_idx；仅清理该数据源自身产物。
    """
    documents = (
        db.session.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.source_type == source_type,
            KnowledgeDocument.source_id == str(source_id),
        )
        .all()
    )
    vector_service = None
    try:
        vector_service = _get_knowledge_vector_service()
    except Exception as exc:
        logger.warning("获取向量服务失败，跳过向量清理: %s", exc)

    for doc in documents:
        segments = (
            db.session.query(KnowledgeSegment)
            .filter(KnowledgeSegment.knowledge_document_id == doc.id)
            .all()
        )
        if vector_service is not None:
            for segment in segments:
                try:
                    vector_service.remove_segment(segment)
                except Exception as exc:
                    logger.warning("清理外部数据源向量失败 segment=%s: %s", segment.id, exc)
        db.session.query(KnowledgeSegment).filter(
            KnowledgeSegment.knowledge_document_id == doc.id,
        ).delete(synchronize_session=False)
        upload_file_id = getattr(doc, "upload_file_id", None)
        db.session.query(KnowledgeDocument).filter(
            KnowledgeDocument.id == doc.id,
        ).delete(synchronize_session=False)
        if upload_file_id is not None:
            db.session.query(UploadFile).filter(
                UploadFile.id == upload_file_id,
            ).delete(synchronize_session=False)
    return len(documents)
```

并在 `physical_delete_external_data_source` 中先调用清理：

```python
def physical_delete_external_data_source(resource_id) -> None:
    data_source = (
        db.session.query(ExternalDataSource)
        .filter(ExternalDataSource.id == resource_id)
        .one_or_none()
    )
    if data_source is not None:
        # 先清同步产物（文档/分段/向量/上传文件），再删主记录，避免孤儿数据
        _delete_documents_by_source(data_source.source_type, str(data_source.id))
    db.session.query(ExternalDataSource).filter(
        ExternalDataSource.id == resource_id,
    ).delete(synchronize_session=False)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_recycle_bin_handlers.py -q --no-cov`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/recycle_bin_handlers.py api/test/internal/service/test_recycle_bin_handlers.py
git commit -m "fix(external-data-source): cascade-delete synced docs on data source removal"
```

---

### Task 7: API 响应脱敏

**Files:**
- Modify: `api/app/http/knowledge_mcp_routes.py`
- Test: `api/test/app/http/test_external_data_source_masking.py`

- [ ] **Step 1: 写失败的测试**

新建 `api/test/app/http/test_external_data_source_masking.py`：

```python
"""外部数据源路由响应脱敏测试：密钥不得以明文回传。"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.knowledge_mcp_routes import register_routes

register_routes(asgi_app.quart_app)


def _flat_keys(payload):
    """收集 JSON 中所有字符串值，用于断言不含明文密钥。"""
    found = []

    def _walk(node):
        if isinstance(node, dict):
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)
        elif isinstance(node, str):
            found.append(node)

    _walk(payload)
    return found


def test_list_masks_sensitive_config(monkeypatch):
    from internal.service.external_data_source_credentials import encrypt_config

    account = SimpleNamespace(id=uuid4())
    row = SimpleNamespace(
        id=uuid4(),
        knowledge_base_id=uuid4(),
        source_type="lark",
        source_name="Lark KB",
        authorization_status="granted",
        sync_status="idle",
        sync_cursor="",
        last_synced_at=None,
        last_error="",
        config=encrypt_config({"app_id": "cli_x", "app_secret": "super-secret"}),
        created_at=None,
        updated_at=None,
    )

    class _Service:
        def list_data_sources(self, account, status=""):
            return [row]

    async def _fake_resolve_account(account_id_override=None):
        return account, None

    monkeypatch.setattr(support, "_resolve_account", _fake_resolve_account)
    monkeypatch.setattr(support, "_get_service", lambda cls: _Service())

    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.get("/external-data-sources")
            return resp, await resp.json

    resp, payload = asyncio.run(_run())
    assert resp.status_code == 200

    values = _flat_keys(payload)
    assert "super-secret" not in values
    items = payload["data"]["items"]
    assert items[0]["config"]["app_id"] == "cli_x"
    assert items[0]["config"]["app_secret"] != "super-secret"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/app/http/test_external_data_source_masking.py -q --no-cov`
Expected: FAIL — 响应中仍含 `super-secret` 明文

- [ ] **Step 3: 在路由层脱敏**

修改 `api/app/http/knowledge_mcp_routes.py`。在 `register_routes` 内、第一个路由之前加入辅助函数：

```python
    def _masked_data_source(row) -> dict:
        """序列化单条数据源并对 config 脱敏，避免密钥回传前端。"""
        from internal.schema.external_data_source_schema import ExternalDataSourceResp
        from internal.service.external_data_source_credentials import mask_config

        payload = ExternalDataSourceResp().dump(row)
        payload["config"] = mask_config(getattr(row, "config", None))
        return payload
```

列表 handler（`async_external_data_source_list`）的返回改为：

```python
        items = [_masked_data_source(row) for row in data_sources]
        return _ok({"items": items, "total": len(items)})
```

创建 handler（`async_external_data_source_create`）的返回改为：

```python
        return _ok(_masked_data_source(data_source))
```

详情 handler（`async_external_data_source_get`）的返回改为：

```python
        return _ok(_masked_data_source(data_source))
```

授权 handler（`async_external_data_source_authorize`）的返回改为：

```python
        return _ok(_masked_data_source(data_source))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/app/http/test_external_data_source_masking.py -q --no-cov`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/app/http/knowledge_mcp_routes.py api/test/app/http/test_external_data_source_masking.py
git commit -m "fix(external-data-source): mask credentials in API responses"
```

---

### Task 8: 定时自动同步任务

**Files:**
- Create: `api/internal/task/external_data_source_tasks.py`
- Modify: `api/app/http/celery_app.py`
- Test: `api/test/internal/task/test_external_data_source_tasks.py`

- [ ] **Step 1: 写失败的测试**

新建 `api/test/internal/task/test_external_data_source_tasks.py`：

```python
"""外部数据源自动同步定时任务测试。"""

from internal.task import external_data_source_tasks as tasks


def test_task_is_registered_with_expected_name():
    assert (
        tasks.run_external_data_source_auto_sync.name
        == "internal.task.external_data_source_tasks.run_external_data_source_auto_sync"
    )


def test_task_delegates_to_service(monkeypatch):
    captured = {}

    class _Service:
        def auto_sync_all(self):
            captured["called"] = True
            return {"scanned": 2, "synced": 1, "failed": 1}

    monkeypatch.setattr(tasks, "_get_service", lambda: _Service())

    result = tasks.run_external_data_source_auto_sync()

    assert captured["called"] is True
    assert result == {"scanned": 2, "synced": 1, "failed": 1}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/task/test_external_data_source_tasks.py -q --no-cov`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现任务模块**

新建 `api/internal/task/external_data_source_tasks.py`：

```python
"""外部数据源自动同步 Celery 定时任务。

提供周期同步任务：
    - ``run_external_data_source_auto_sync``: 扫描已授权数据源并逐个同步
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


def _get_service():
    """经 DI 容器获取服务（延迟导入，避免 Celery 启动期循环依赖）。"""
    from app.http.module import injector
    from internal.service.external_data_source_service import ExternalDataSourceService

    return injector.get(ExternalDataSourceService)


@shared_task(
    name="internal.task.external_data_source_tasks.run_external_data_source_auto_sync",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_external_data_source_auto_sync(self):
    """扫描已授权数据源并自动同步。

    Returns:
        ``{"scanned": int, "synced": int, "failed": int}`` 执行摘要
    """
    try:
        result = _get_service().auto_sync_all()
        logger.info("外部数据源自动同步完成: %s", result)
        return result
    except Exception:
        logger.exception("外部数据源自动同步任务失败")
        raise self.retry()
```

> 注意：同步函数须为「模块级函数」且通过 `_get_service` 间接取服务，以便测试 monkeypatch。

- [ ] **Step 4: 注册到 Celery**

修改 `api/app/http/celery_app.py`：

`TASK_MODULES` 追加一项（放在 `auto_renewal_tasks` 之后）：

```python
    "internal.task.external_data_source_tasks",
```

显式导入区追加（在 `_task_auto_renewal` 之后）：

```python
import internal.task.external_data_source_tasks as _task_external_ds  # noqa: F401,E402
```

`beat_schedule.update({...})` 中追加：

```python
        "external-data-source-auto-sync": {
            "task": "internal.task.external_data_source_tasks.run_external_data_source_auto_sync",
            "schedule": crontab(hour="*/6", minute=15),  # 每 6 小时 15 分同步一次
            "args": [],
        },
```

`task_routes` 中追加：

```python
        "internal.task.external_data_source_tasks.*": {"queue": "consolidation"},
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/task/test_external_data_source_tasks.py -q --no-cov`
Expected: PASS

- [ ] **Step 6: 验证 beat 已注册**

Run: `cd api && python -c "from app.http.celery_app import celery_app; print('external-data-source-auto-sync' in celery_app.conf.beat_schedule)"`
Expected: 输出 `True`

- [ ] **Step 7: 提交**

```bash
git add api/internal/task/external_data_source_tasks.py api/app/http/celery_app.py api/test/internal/task/test_external_data_source_tasks.py
git commit -m "feat(external-data-source): add scheduled auto-sync task"
```

---

### Task 9: 删除冗余工具与死代码

**Files:**
- Delete: `api/internal/service/external_data_retrieval_tool.py`
- Delete: `api/test/internal/service/test_external_data_retrieval_tool.py`
- Delete: `api/internal/schema/knowledge_schema.py`

- [ ] **Step 1: 再次确认无引用（删除前置检查）**

Run:
```bash
cd d:/DEMO/openagent-main/api && grep -rn "external_data_retrieval_tool\|create_external_data_retrieval_tool" --include="*.py" . | grep -v "test_external_data_retrieval_tool.py"
```
Expected: 无输出

Run:
```bash
cd d:/DEMO/openagent-main/api && grep -rn "schema.knowledge_schema\|schema import knowledge_schema" --include="*.py" .
```
Expected: 无输出

> 若无 `grep`，用编辑器全局搜索替代。若**发现引用**，停止该步并在计划外单独评估。

- [ ] **Step 2: 删除文件**

```bash
git rm api/internal/service/external_data_retrieval_tool.py \
       api/test/internal/service/test_external_data_retrieval_tool.py \
       api/internal/schema/knowledge_schema.py
```

- [ ] **Step 3: 全量后端测试确认无破坏**

Run: `cd api && python -m pytest -q -p no:cacheprovider --no-cov`
Expected: 全部 PASS，0 failed

- [ ] **Step 4: 提交**

```bash
git commit -m "chore: remove unused external data retrieval tool and dead knowledge schema"
```

---

### Task 10: 历史数据迁移

**Files:**
- Create: `api/internal/migration/versions/m7b8c9d0e1f2_encrypt_external_data_source_credentials.py`

- [ ] **Step 1: 编写迁移脚本**

新建 `api/internal/migration/versions/m7b8c9d0e1f2_encrypt_external_data_source_credentials.py`：

```python
"""encrypt external data source credentials and drop enterprise_knowledge

Revision ID: m7b8c9d0e1f2
Revises: l6a7b8c9d0e1
Create Date: 2026-09-12 00:00:00.000000

1. 把 external_data_source.config 中约定敏感 key 的明文值加密回填（幂等：gAAAAA 前缀跳过）。
2. 清理已下线的 enterprise_knowledge 类型数据源及其同步产物。

依赖 MODEL_KEY_ENCRYPTION_KEY；未配置则中止（与 d5e6f7a8b9c2 同款）。
downgrade 不可逆（加密与删除均无法还原），需走备份恢复。
"""
import json
import os
from typing import Any

from alembic import op
from cryptography.fernet import Fernet
from sqlalchemy import text

revision = "m7b8c9d0e1f2"
down_revision = "l6a7b8c9d0e1"
branch_labels = None
depends_on = None

_ENCRYPTED_PREFIX = "gAAAAA"
_SENSITIVE_KEYS = (
    "app_secret",
    "integration_token",
    "personal_access_token",
    "api_key",
    "token",
    "client_secret",
)


def _load_fernet() -> Fernet:
    raw_key = os.getenv("MODEL_KEY_ENCRYPTION_KEY", "").strip()
    if not raw_key:
        raise RuntimeError(
            "MODEL_KEY_ENCRYPTION_KEY 未配置，无法执行外部数据源凭证加密迁移；"
            "请配置该变量后重试。"
        )
    try:
        return Fernet(raw_key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "MODEL_KEY_ENCRYPTION_KEY 不是合法的 Fernet 密钥，"
            "请使用 Fernet.generate_key() 生成"
        ) from exc


def _is_encrypted(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value.startswith(_ENCRYPTED_PREFIX)


def _verify_fernet_roundtrip(fernet: Fernet) -> None:
    sample = "migration-sanity-check"
    encrypted = fernet.encrypt(sample.encode("utf-8")).decode("utf-8")
    if fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8") != sample:
        raise RuntimeError("Fernet 加解密自检失败，请检查 MODEL_KEY_ENCRYPTION_KEY")


def _encrypt_config(fernet: Fernet, config: Any) -> tuple[dict, int]:
    """加密敏感 key，返回 (新 config, 加密计数)。"""
    if not isinstance(config, dict):
        return {}, 0
    count = 0
    new_config = dict(config)
    for key in _SENSITIVE_KEYS:
        value = new_config.get(key)
        if isinstance(value, str) and value and not _is_encrypted(value):
            new_config[key] = fernet.encrypt(value.encode("utf-8")).decode("utf-8")
            count += 1
    return new_config, count


def upgrade():
    fernet = _load_fernet()
    _verify_fernet_roundtrip(fernet)
    conn = op.get_bind()

    # 1. 加密历史 config
    rows = conn.execute(
        text("SELECT id, config FROM external_data_source")
    ).fetchall()
    encrypted_rows = 0
    for row in rows:
        new_config, count = _encrypt_config(fernet, row.config)
        if count == 0:
            continue
        conn.execute(
            text(
                "UPDATE external_data_source SET config = CAST(:cfg AS JSONB) WHERE id = :id"
            ),
            {"cfg": json.dumps(new_config, ensure_ascii=False), "id": row.id},
        )
        encrypted_rows += 1

    # 2. 清理 enterprise_knowledge 数据源及其同步产物
    conn.execute(
        text(
            "DELETE FROM knowledge_segment WHERE knowledge_document_id IN ("
            "  SELECT id FROM knowledge_document WHERE source_type = 'enterprise_knowledge'"
            ")"
        )
    )
    conn.execute(
        text("DELETE FROM knowledge_document WHERE source_type = 'enterprise_knowledge'")
    )
    removed = conn.execute(
        text("DELETE FROM external_data_source WHERE source_type = 'enterprise_knowledge'")
    ).rowcount

    print(
        f"[migration] 外部数据源凭证加密完成：{encrypted_rows} 行；"
        f"清理 enterprise_knowledge 数据源：{removed} 行"
    )


def downgrade():
    raise NotImplementedError(
        "该迁移不可逆（凭证加密与 enterprise_knowledge 删除均无法还原），请走备份恢复。"
    )
```

- [ ] **Step 2: 校验迁移链与语法**

Run: `cd api && python -m py_compile internal/migration/versions/m7b8c9d0e1f2_encrypt_external_data_source_credentials.py`
Expected: 无输出（成功）

Run: `cd api && python scripts/verify_migration_upgrade.py`
Expected: 通过（head 唯一）

- [ ] **Step 3: 应用迁移**

Run: `docker exec -e PYTHONPATH=/app/api llmops-api sh -c "cd /app/api && alembic -c internal/migration/alembic.ini upgrade head"`
Expected: 输出 `Running upgrade l6a7b8c9d0e1 -> m7b8c9d0e1f2, encrypt external data source credentials...`

- [ ] **Step 4: 验证结果**

Run:
```bash
docker exec llmops-db psql -U postgres -d llmops -c "SELECT source_type, jsonb_object_keys(config) FROM external_data_source;"
```
Expected: 无 `enterprise_knowledge` 行；有敏感 key 的行其值以 `gAAAAA` 开头（可另用 Python 验证解密）

- [ ] **Step 5: 提交**

```bash
git add api/internal/migration/versions/m7b8c9d0e1f2_encrypt_external_data_source_credentials.py
git commit -m "feat(migration): encrypt external data source credentials and drop enterprise_knowledge"
```

---

### Task 11: 前端 service 类型修正

**Files:**
- Modify: `ui/src/services/external-data-source.ts`

- [ ] **Step 1: 修正列表返回类型**

修改 `ui/src/services/external-data-source.ts`，新增列表响应类型并修改函数：

```ts
export type ExternalDataSourceList = {
  items: Array<ExternalDataSource>
  total: number
}

export const getExternalDataSources = (status?: string) => {
  return get<BaseResponse<ExternalDataSourceList>>(`/external-data-sources`, {
    params: status ? { status } : undefined,
  })
}
```

（其余函数不变。）

- [ ] **Step 2: 类型检查**

Run: `cd ui && npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | grep "external-data-source" | head -20`
Expected: 无输出（该文件无类型错误）

- [ ] **Step 3: 提交**

```bash
git add ui/src/services/external-data-source.ts
git commit -m "fix(external-data-source): correct list response shape to items/total"
```

---

### Task 12: i18n 字典增删

**Files:**
- Modify: `ui/src/i18n/messages/zh-CN/externalDataSource.ts`
- Modify: `ui/src/i18n/messages/en-US/externalDataSource.ts`

- [ ] **Step 1: 同步修改两侧字典**

`ui/src/i18n/messages/zh-CN/externalDataSource.ts` 追加以下键（并删除 `enterpriseKnowledge`）：

```ts
    boundSourcesTitle: '已绑定数据源',
    boundCount: '{count} 个已绑定',
    goAuthorize: '去授权',
    syncedAt: '同步于 {time}',
    needsAuthorize: '需要补充授权后开始同步',
    bindNewTitle: '绑定新数据源',
    bindNote: '数据仅用于知识库检索与同步',
    secureNote: '凭证仅保存在你的账号下，用于定时同步该数据源；可随时解绑。',
    binding: '绑定中…',
    bindSource: '绑定数据源',
    cancel: '取消',
    confirmUnbind: '确认解绑',
    unbindConfirmText: '确认解绑「{name}」？解绑后该数据源将不再同步，且无法恢复。',
    loading: '加载中…',
    close: '关闭',
    namePlaceholder: '例如：{example}',
    namePlaceholderDefault: '产品知识库',
    namePlaceholderDrive: '本地文档目录',
    optional: '选填',
    required: '*',
    fields: {
      docsPath: '文档目录',
    },
```

> `fields` 为已存在的嵌套字典，此处仅**新增** `docsPath` 子键；不要整块替换 `fields`，保留 `appId`/`appSecret`/`repo` 等既有键。

`ui/src/i18n/messages/en-US/externalDataSource.ts` 追加对应键（同样删除 `enterpriseKnowledge`）：

```ts
    boundSourcesTitle: 'Bound sources',
    boundCount: '{count} bound',
    goAuthorize: 'Authorize',
    syncedAt: 'Synced at {time}',
    needsAuthorize: 'Authorization required before syncing',
    bindNewTitle: 'Bind a new source',
    bindNote: 'Data is used only for knowledge base retrieval and sync',
    secureNote: 'Credentials are stored under your account and used for scheduled sync; you can unbind anytime.',
    binding: 'Binding…',
    bindSource: 'Bind source',
    cancel: 'Cancel',
    confirmUnbind: 'Confirm unbind',
    unbindConfirmText: 'Unbind "{name}"? It will stop syncing and cannot be recovered.',
    loading: 'Loading…',
    close: 'Close',
    namePlaceholder: 'e.g. {example}',
    namePlaceholderDefault: 'Product knowledge base',
    namePlaceholderDrive: 'Local documents folder',
    optional: 'Optional',
    required: '*',
    fields: {
      docsPath: 'Docs path',
    },
```

> `fields` 为已存在的嵌套字典，此处仅**新增** `docsPath` 子键（对应 Task 13 GitHub 表单的可选文档目录字段）；不要整块替换 `fields`，保留 `appId`/`appSecret`/`repo` 等既有键。

- [ ] **Step 2: 运行 parity 测试**

Run: `cd ui && npx vitest run src/i18n/__tests__/parity.spec.ts`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add ui/src/i18n/messages/zh-CN/externalDataSource.ts ui/src/i18n/messages/en-US/externalDataSource.ts
git commit -m "feat(external-data-source): add modal i18n keys and drop enterprise knowledge"
```

---

### Task 13: 弹窗接线真实接口

**Files:**
- Modify: `ui/src/views/space/datasets/components/ExternalDataSourceModal.vue`

- [ ] **Step 1: 替换 script 的 mock 与业务逻辑**

修改 `ui/src/views/space/datasets/components/ExternalDataSourceModal.vue` 的 `<script setup>`：

删除 `MockSource` 类型、`MOCK_SOURCES`、`MockSource` 相关引用；顶部改为：

```ts
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useCredentialStore } from '@/stores/credential'
import { isCredentialLoggedIn } from '@/utils/auth'
import { redirectToLogin } from '@/utils/login-redirect'
import { getErrorMessage } from '@/utils/error'
import {
  authorizeExternalDataSource,
  createExternalDataSource,
  deleteExternalDataSource,
  getExternalDataSources,
  syncExternalDataSource,
} from '@/services/external-data-source'
import type { ExternalDataSource } from '@/services/external-data-source'
```

数据源列表与类型选项改为：

```ts
const dataSources = ref<ExternalDataSource[]>([])
const loading = ref(false)
const syncingIds = ref<Record<string, boolean>>({})
const authorizingIds = ref<Record<string, boolean>>({})
const unbindTarget = ref<ExternalDataSource | null>(null)

const creating = ref(false)
const expandCreate = ref(false)
const createForm = ref({
  source_type: 'lark' as string,
  source_name: '',
  config: {} as Record<string, string>,
})

const sourceTypeOptions: Array<{ value: string; label: string }> = [
  { value: 'lark', label: t('externalDataSource.lark') },
  { value: 'notion', label: t('externalDataSource.notion') },
  { value: 'github', label: t('externalDataSource.github') },
  { value: 'drive', label: t('externalDataSource.drive') },
]
```

`credentialFields` 保留 lark/notion/github/drive 四个分支，**删除 `enterprise_knowledge` 分支**。其中 GitHub 分支改为单一 `repo` 全名输入（与后端连接器要求的 `owner/repo` 格式对齐）：

```ts
    case 'github':
      return [
        { key: 'personal_access_token', label: t('externalDataSource.fields.personalAccessToken'), required: true, full: true },
        { key: 'repo', label: t('externalDataSource.fields.repo'), required: true, full: false },
        { key: 'path', label: t('externalDataSource.fields.docsPath'), required: false, full: false },
      ]
```

> 修正既有集成缺陷：原表单分设 `owner` 与 `repo` 两栏，但后端 `github_connector` 要求 `repo` 为 `owner/repo` 全名且会校验其中含 `/`。合并为单栏后前端与后端一致。（`path` 为可选文档目录，对应后端 `config.path`，默认 `docs`。）

`typeMeta` 改为：

```ts
const typeMeta: Record<string, { labelKey: string; cls: string }> = {
  lark: { labelKey: 'lark', cls: 'type-lark' },
  notion: { labelKey: 'notion', cls: 'type-notion' },
  github: { labelKey: 'github', cls: 'type-github' },
  drive: { labelKey: 'drive', cls: 'type-drive' },
}
```

业务函数改为：

```ts
const loadDataSources = async () => {
  loading.value = true
  try {
    const res = await getExternalDataSources()
    dataSources.value = res.data?.items || []
  } catch (error: unknown) {
    dataSources.value = []
    Message.error(getErrorMessage(error, t('externalDataSource.syncFailed')))
  } finally {
    loading.value = false
  }
}

const handleCreate = async () => {
  if (!createForm.value.source_name.trim()) {
    Message.error(t('externalDataSource.createFailed'))
    return
  }
  creating.value = true
  try {
    await createExternalDataSource({
      source_type: createForm.value.source_type,
      source_name: createForm.value.source_name.trim(),
      config: { ...createForm.value.config },
    })
    Message.success(t('externalDataSource.createSuccess'))
    expandCreate.value = false
    resetCreateForm()
    await loadDataSources()
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('externalDataSource.createFailed')))
  } finally {
    creating.value = false
  }
}

const handleAuthorize = async (record: ExternalDataSource) => {
  if (authorizingIds.value[record.id]) return
  authorizingIds.value[record.id] = true
  try {
    await authorizeExternalDataSource(record.id, {})
    Message.success(t('externalDataSource.granted'))
    await loadDataSources()
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('externalDataSource.syncFailed')))
  } finally {
    authorizingIds.value[record.id] = false
  }
}

const handleSync = async (record: ExternalDataSource) => {
  if (syncingIds.value[record.id]) return
  syncingIds.value[record.id] = true
  try {
    const res = await syncExternalDataSource(record.id)
    const result = res.data
    if (result && result.sync_status === 'success') {
      Message.success(
        t('externalDataSource.syncSuccess', {
          document: result.document_count,
          segment: result.segment_count,
        }),
      )
    } else {
      Message.error(
        result?.last_error
          ? `${t('externalDataSource.syncFailed')}: ${result.last_error}`
          : t('externalDataSource.syncFailed'),
      )
    }
    await loadDataSources()
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('externalDataSource.syncFailed')))
  } finally {
    syncingIds.value[record.id] = false
  }
}

const confirmUnbind = async () => {
  if (!unbindTarget.value) return
  const target = unbindTarget.value
  try {
    await deleteExternalDataSource(target.id)
    Message.success(t('externalDataSource.delete'))
    unbindTarget.value = null
    await loadDataSources()
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('externalDataSource.syncFailed')))
  }
}
```

`watch(visible)` 中的加载逻辑保持调用 `loadDataSources()`。

- [ ] **Step 2: 更新模板**

模板改动（保持结构，替换绑定与文案）：

- 「去授权」按钮：`@click="source.authorization_status = 'granted'"` → `@click="handleAuthorize(source)"`，并加 `:disabled="authorizingIds[source.id]"`
- 状态判定：`source.authorization_status === 'pending'` 分支展示「去授权」，`'granted'` 分支展示「同步」（保持现有 `v-else` 结构）
- 文案 i18n 化：
  - `已绑定数据源` → `{{ t('externalDataSource.boundSourcesTitle') }}`
  - `{{ dataSources.length }} 个已绑定` → `{{ t('externalDataSource.boundCount', { count: dataSources.length }) }}`
  - `去授权` → `{{ t('externalDataSource.goAuthorize') }}`
  - `同步于 {{ formatTime(...) }}` → `{{ t('externalDataSource.syncedAt', { time: formatTime(source.last_synced_at) }) }}`
  - `需要补充授权后开始同步` → `{{ t('externalDataSource.needsAuthorize') }}`
  - `绑定新数据源` → `{{ t('externalDataSource.bindNewTitle') }}`
  - `数据仅用于知识库检索与同步` → `{{ t('externalDataSource.bindNote') }}`
  - `凭证仅保存在你的账号下，…` → `{{ t('externalDataSource.secureNote') }}`
  - `绑定中…` / `绑定数据源` → `{{ t('externalDataSource.binding') }}` / `{{ t('externalDataSource.bindSource') }}`
  - `取消` / `确认解绑` → `{{ t('externalDataSource.cancel') }}` / `{{ t('externalDataSource.confirmUnbind') }}`
  - `确认解绑「{{ unbindTarget.source_name }}」？…` → `{{ t('externalDataSource.unbindConfirmText', { name: unbindTarget.source_name }) }}`
  - `加载中…` → `{{ t('externalDataSource.loading') }}`
  - `关闭`（aria-label）→ `:aria-label="t('externalDataSource.close')"`
  - 名称输入框 placeholder → `:placeholder="t('externalDataSource.namePlaceholder', { example: createForm.source_type === 'drive' ? t('externalDataSource.namePlaceholderDrive') : t('externalDataSource.namePlaceholderDefault') })"`
  - `选填` → `{{ t('externalDataSource.optional') }}`；`*` 保留为 `{{ t('externalDataSource.required') }}`
- 移除 `enterprise_knowledge` 相关的图标分支（`v-else` 落到 `icon-folder`/`icon-common`）
- 新增 `last_error` 提示（在 `eds-row-sub` 之后）：

```vue
                <p v-if="source.last_error" class="eds-row-sub eds-row-error">
                  {{ source.last_error }}
                </p>
```

并在样式块追加：

```css
.eds-row-error {
  color: #f53f3f;
}
```

- [ ] **Step 3: 类型检查**

Run: `cd ui && npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | grep "ExternalDataSourceModal" | head -20`
Expected: 无输出

- [ ] **Step 4: 提交**

```bash
git add ui/src/views/space/datasets/components/ExternalDataSourceModal.vue
git commit -m "feat(external-data-source): wire modal to real APIs"
```

---

### Task 14: 删除独立页面与路由

**Files:**
- Delete: `ui/src/views/external-data-sources/` （整个目录）
- Modify: `ui/src/router/index.ts`

- [ ] **Step 1: 确认无其他引用**

Run:
```bash
cd d:/DEMO/openagent-main/ui && grep -rn "external-data-sources/ListView\|user-external-data-sources-list" src/
```
Expected: 仅 `src/router/index.ts` 命中

- [ ] **Step 2: 删除路由注册**

修改 `ui/src/router/index.ts`，删除该路由对象（原约 L89-93）：

```ts
        {
          path: 'external-data-sources',
          name: 'user-external-data-sources-list',
          component: () => import('@/views/external-data-sources/ListView.vue'),
        },
```

- [ ] **Step 3: 删除页面目录**

```bash
git rm -r ui/src/views/external-data-sources
```

- [ ] **Step 4: 类型检查与测试**

Run: `cd ui && npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | grep -i "external-data-sources" | head -10`
Expected: 无输出

Run: `cd ui && npx vitest run`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add ui/src/router/index.ts
git commit -m "chore(external-data-source): remove unusable standalone page and route"
```

---

### Task 15: 前端弹窗测试

**Files:**
- Create: `ui/src/views/space/datasets/components/__tests__/ExternalDataSourceModal.spec.ts`

- [ ] **Step 1: 写测试**

新建 `ui/src/views/space/datasets/components/__tests__/ExternalDataSourceModal.spec.ts`：

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const getSourcesMock = vi.fn()
const createMock = vi.fn()
const syncMock = vi.fn()
const authorizeMock = vi.fn()
const deleteMock = vi.fn()

vi.mock('@/services/external-data-source', () => ({
  getExternalDataSources: (...a: unknown[]) => getSourcesMock(...a),
  createExternalDataSource: (...a: unknown[]) => createMock(...a),
  syncExternalDataSource: (...a: unknown[]) => syncMock(...a),
  authorizeExternalDataSource: (...a: unknown[]) => authorizeMock(...a),
  deleteExternalDataSource: (...a: unknown[]) => deleteMock(...a),
}))

vi.mock('@/stores/credential', () => ({
  useCredentialStore: () => ({ credential: { access_token: 't', expire_at: 9999999999 } }),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

import ExternalDataSourceModal from '@/views/space/datasets/components/ExternalDataSourceModal.vue'

const stubs = {
  'a-modal': { template: '<div><slot /></div>' },
  'icon-cloud': true, 'icon-close': true, 'icon-user': true, 'icon-loading': true,
  'icon-storage': true, 'icon-send': true, 'icon-file': true, 'icon-github': true,
  'icon-folder': true, 'icon-common': true, 'icon-check': true, 'icon-clock-circle': true,
  'icon-safe': true, 'icon-sync': true, 'icon-link': true, 'icon-exclamation-circle': true,
  'icon-lock': true,
}

describe('ExternalDataSourceModal', () => {
  beforeEach(() => {
    getSourcesMock.mockReset()
    createMock.mockReset()
  })

  it('renders real data sources from API', async () => {
    getSourcesMock.mockResolvedValue({
      code: 'success', message: '',
      data: { items: [
        { id: 's1', source_type: 'lark', source_name: '产品研发知识库',
          authorization_status: 'granted', sync_status: 'success',
          last_synced_at: '2026-09-03T09:30:00', last_error: '', config: {} },
      ], total: 1 },
    })
    const wrapper = mount(ExternalDataSourceModal, {
      props: { visible: true },
      global: { stubs },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('产品研发知识库')
  })

  it('creates a data source via real API', async () => {
    getSourcesMock.mockResolvedValue({ code: 'success', message: '', data: { items: [], total: 0 } })
    createMock.mockResolvedValue({ code: 'success', message: '', data: {} })
    const wrapper = mount(ExternalDataSourceModal, {
      props: { visible: true },
      global: { stubs },
    })
    await flushPromises()
    // @ts-expect-error 访问组件内部状态用于测试
    wrapper.vm.createForm.source_name = 'Lark KB'
    // @ts-expect-error 访问组件内部方法用于测试
    await wrapper.vm.handleCreate()
    expect(createMock).toHaveBeenCalledWith(
      expect.objectContaining({ source_type: 'lark', source_name: 'Lark KB' }),
    )
  })
})
```

> 若组件未用 `defineExpose`，`wrapper.vm.xxx` 在 `<script setup>` 下仍可访问（vitest + @vue/test-utils 支持）。若访问受限，改用触发 DOM 事件（填 input + 提交表单）。

- [ ] **Step 2: 运行测试**

Run: `cd ui && npx vitest run src/views/space/datasets/components/__tests__/ExternalDataSourceModal.spec.ts`
Expected: PASS（2 passed）

- [ ] **Step 3: 提交**

```bash
git add ui/src/views/space/datasets/components/__tests__/ExternalDataSourceModal.spec.ts
git commit -m "test(external-data-source): cover modal real-API integration"
```

---

### Task 16: 全量回归 + 文档同步 + graphify

**Files:**
- Modify: `docs/prd/product-vision.md`
- Modify: `docs/prd/modules/02-knowledge-base.md`

- [ ] **Step 1: 后端全量测试**

Run: `cd api && python -m pytest -q -p no:cacheprovider --no-cov`
Expected: 全部 PASS，0 failed

- [ ] **Step 2: 前端全量测试**

Run: `cd ui && npx vitest run`
Expected: 全部 PASS

- [ ] **Step 3: 更新产品文档**

`docs/prd/product-vision.md`：
- §三 表格第 13 行「知识库『外部数据源』弹窗」：`🎭 **壳子**` → `✅ 真可用`，说明改为「弹窗已接真实接口；凭证明文落库/回传、授权不落库、级联清理缺失已修复」
- §4.4 删除该条（若无剩余条目，整节改为「本轮无遗留 mock」或移除该节）
- §5.3 优先级列表第 4 项标注完成

`docs/prd/modules/02-knowledge-base.md`：修正过时表述（原文「现有知识库缺少外部数据源连接和同步能力」）为「外部数据源连接与同步已实现（lark/notion/github 真实 API + 本地文件夹；凭证加密存储；支持手动手动与定时同步）」。

- [ ] **Step 4: 更新知识图谱**

Run: `cd d:/DEMO/openagent-main && python -m graphify update .`
Expected: 输出 `Code graph updated.`

- [ ] **Step 5: 提交**

```bash
git add docs/prd/product-vision.md docs/prd/modules/02-knowledge-base.md graphify-out/
git commit -m "docs: mark external data source as hardened and update knowledge base module"
```

---

## 完成标准

- [ ] 弹窗展示真实数据源；创建/授权/同步/解绑均走真实接口
- [ ] 任何 API 响应都不含明文密钥（有测试断言）
- [ ] `external_data_source.config` 敏感 key 加密落库；历史数据已迁移
- [ ] 授权将 `auth_config` 落库，后续同步可用
- [ ] 删除数据源级联清理文档/分段/向量，无孤儿
- [ ] 定时任务每 6 小时自动同步，单条失败不阻塞
- [ ] `enterprise_knowledge` 从枚举/工厂/前端/i18n 移除
- [ ] `external_data_retrieval_tool` 与 `knowledge_schema.py` 已删除且无引用
- [ ] 独立页面与路由已删除
- [ ] 前后端测试全绿；i18n parity 通过；graphify 已刷新
