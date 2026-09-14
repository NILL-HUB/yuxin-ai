# 文件存储与对象存储架构

> 本文档为主架构文档的子模块，包含文件存储与对象存储的完整架构设计：端口抽象、三种后端实现（本地/COS/OSS）、运行时代理分发、存储配置与配额收口、配置项、调用链与安全要求。
>
> **主文档**: [architecture-design.md](../architecture-design.md)
> **相关模块**: [03-orchestration-infra.md](./03-orchestration-infra.md) | [02-knowledge-base.md](./02-knowledge-base.md) | [记忆系统/02-storage-and-retrieval.md](../memory-system/02-storage-and-retrieval.md)

---

## 17. 文件存储与对象存储架构

### 17.1 设计目标

系统需要统一管理用户上传的文件（知识库文档、应用图标、AI 生成图片、沙箱产物等），支持在不同部署环境下灵活切换存储后端：

- **开发/测试环境**：使用本地文件系统存储，无需配置云服务账号
- **腾讯云生产环境**：使用腾讯云 COS 对象存储
- **阿里云生产环境**：使用阿里云 OSS 对象存储

有两条主线：

1. **运行时代理分发**：DI 统一绑定 `RuntimeStorageProxy`，代理在请求时按 `storage_config` 表中激活的后端动态分发。Admin 端切换后端后，**新上传文件立即进入新后端**，无需重启服务；历史文件按记录自身的 `storage_backend` 路由回原后端访问。
2. **配额收口**：所有上传路径经代理统一校验账号存储配额（`StorageQuotaService.check_quota`），成功后累加用量，超限拒绝。

### 17.2 架构分层

```
┌─────────────────────────────────────────────────────────────┐
│  业务层（Handler / Service）                                 │
│  - 上传路由 /upload-files/*   - KnowledgeBaseService        │
│  - AdminUploadFileHandler    - IconGeneratorService         │
│  - AppService               - DeepThinkingAgent             │
└────────────────────────┬────────────────────────────────────┘
                         │ 注入（ObjectStoragePort / CosService）
┌────────────────────────▼────────────────────────────────────┐
│  运行时代理层（RuntimeStorageProxy）                         │
│  - upload_file / upload_bytes / download_file               │
│  - upload_bytes_without_record / get_file_url               │
│  - 配额守卫：check_quota（前）+ add_usage（后）              │
│  - 后端解析：upload 跟随激活后端 / download·url 按记录后端路由 │
└────────────────────────┬────────────────────────────────────┘
                         │ 运行时按 storage_config 激活后端分发
┌────────────────────────▼────────────────────────────────────┐
│  实现层（三种可插拔后端，纯存储职责）                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ LocalStorage │  │  CosService  │  │  OSSService  │       │
│  │   Service    │  │  (腾讯云COS)  │  │  (阿里云OSS)  │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### 17.3 核心组件

#### 17.3.1 ObjectStoragePort（端口接口）

位置：`api/internal/core/ports/storage_port.py`

定义存储后端的统一协议，所有实现必须遵循：

```python
@runtime_checkable
class ObjectStoragePort(Protocol):
    def upload_file(self, file, only_image=False, account=None) -> UploadFile: ...
    def upload_bytes(self, *, filename, content, account_id, mime_type=None, folder="artifacts") -> UploadFile: ...
    def download_file(self, key, target_file_path) -> None: ...
    @classmethod
    def upload_bytes_without_record(cls, *, filename, content, folder="generated-images") -> str: ...
    def get_file_url(self, key, download_name=None) -> str: ...
```

#### 17.3.2 StorageBackend（后端枚举）

位置：`api/internal/service/storage/backend.py`

```python
class StorageBackend(str, Enum):
    LOCAL = "local"  # 本地文件系统（开发/测试默认）
    COS = "cos"      # 腾讯云 COS
    OSS = "oss"      # 阿里云 OSS
```

#### 17.3.3 RuntimeStorageProxy（运行时存储分发代理）

位置：`api/internal/service/storage/runtime_storage_service.py`

运行时存储分发代理。**取代原先启动时按 `STORAGE_BACKEND` 环境变量固定绑定后端的方案**，改为在请求时根据 `storage_config` 表中激活的后端动态分发，使 Admin 端切换存储后端后新上传文件立即进入新后端。

DI 绑定（`api/app/http/module.py`）：

```python
from internal.service.storage.runtime_storage_service import RuntimeStorageProxy
binder.bind(ObjectStoragePort, to=RuntimeStorageProxy)
binder.bind(CosService, to=RuntimeStorageProxy)   # 兼容现有注入 CosService 的代码
binder.bind(RuntimeStorageProxy, to=RuntimeStorageProxy, scope=singleton)
binder.bind(StorageQuotaService, to=StorageQuotaService, scope=singleton)
```

关键行为：

| 方法 | 后端解析规则 | 配额守卫 |
| --- | --- | --- |
| `upload_file` | 当前激活后端 | 写入前 `check_quota`，成功后 `add_usage`（`account` 为空则跳过） |
| `upload_bytes` | 当前激活后端 | 写入前 `check_quota`，成功后 `add_usage`（`account_id` 为空则跳过） |
| `upload_bytes_without_record` | 当前激活后端 | 不创建记录、不计配额 |
| `download_file` / `get_file_url` | 优先按 `upload_file.storage_backend` 路由，未命中回退激活后端 | — |

说明：

- `_get_service()` 按后端名在运行时惰性构造对应的 `LocalStorageService` / `CosService` / `AliyunOSSService` 实例，三个后端本身不感知配额（纯存储职责）。
- `UploadFile.storage_backend` 记录写入时的后端；历史文件（该字段为空）归属 legacy 后端（`STORAGE_BACKEND` 环境变量），保证切换激活后端后旧文件仍可访问。

> **历史说明**：早期版本通过 `api/internal/service/storage/factory.py::get_storage_service_class()` 在 DI 配置阶段按环境变量选定后端实现类。该工厂函数在当前代码中已无任何调用点，实际绑定改为上述 `RuntimeStorageProxy`；`StorageBackend` 枚举（`backend.py`）仍在 `StorageConfigService` 的后端取值校验中被引用。

#### 17.3.4 StorageConfigService（存储配置服务）

位置：`api/internal/service/storage/storage_config_service.py`

管理 `storage_config` 表中的后端配置与激活状态：

- `get_active_backend()`：优先读表中激活记录，未配置时降级到 `STORAGE_BACKEND` 环境变量（默认 `local`）
- `set_active_backend(backend)`：同一时间仅一个后端激活，只影响新上传文件
- `upsert_config(backend, configs)`：仅持久化各后端白名单键（密钥类字段不入库，只保留桶名/区域/域名等可展示信息）
- `ensure_default_config()`：启动时幂等补齐全后端记录与默认激活项，保证 Admin 界面与运行时一致
- `get_storage_stats()`：按 `upload_file.storage_backend` 聚合各后端文件数与体积（全局维度）

### 17.4 存储配额与用量计量（P1 新增）

存储配额在**代理层统一收口**，所有上传路径（用户页面上传、Agent 生成产物、小钰帮传、外部数据源同步）都经 `RuntimeStorageProxy` 校验，禁止各入口自行判断。

规则：

```text
total_quota = max(基线 5GB, 生效套餐 storage_quota_gb) + sum(已购扩展包 GB)
used_bytes  = account_storage_usage.used_bytes   （上传 add_usage / 物理销毁 release_usage）
```

**增减时机（关键语义）**：
- **累加**：上传成功（`RuntimeStorageProxy.upload_file` / `upload_bytes`）时 `add_usage(account_id, upload_file.size)`。
- **释放**：**仅在回收站留存期结束、底层存储对象被物理销毁时** `release_usage(account_id, size)`，落点在 `internal/service/recycle_bin_handlers.py` 的 `purge_knowledge_document` / `purge_knowledge_base`（删除底层对象之后调用 `_release_storage_quota`）。
- **删除进回收站不释放**：删除 = 记录快照 + 物理删原表记录，但底层文件在留存期（默认 7~30 天）内仍占用存储，故此时**不**释放配额；删除后立刻恢复语义才成立（恢复不重复累加，因为配额从未被释放）。
- **容错**：配额释放失败只记 warning，不向上抛异常——`purge` 抛异常的语义是"底层对象删除失败需重试"，配额释放失败若抛出会导致重复销毁。快照缺 `account_id` / `size`（老快照）时跳过释放。

| 组件 | 位置 | 职责 |
| --- | --- | --- |
| `StorageQuotaService` | `api/internal/service/storage_quota_service.py` | `resolve_total_quota_bytes`（配额解析）/ `get_used_bytes` / `get_usage_summary` / `check_quota`（上传前校验）/ `add_usage` / `release_usage` |
| `AccountStorageUsage` | `api/internal/model/account_storage_usage.py`（`account_storage_usage` 表） | 缓存每账号已用字节（`account_id` 唯一，`used_bytes` 为 `BigInteger`），避免每次上传全表 `sum(upload_file.size)` |
| `PlanEntitlement.feature_key='storage_quota_gb'` | `plan_entitlement` 表 | 承载生效会员套餐的存储容量权益，管理员在套餐板块配置即生效 |
| `Plan.plan_type='storage_addon'` | `plan` 表 | 存储扩展包套餐类型，容量叠加在套餐配额之上，复用 `PurchaseOrder` 扣款链路 |

配额常量（`DEFAULT_STORAGE_QUOTA_GB=5`、`BYTES_PER_GB`、`STORAGE_QUOTA_FEATURE_KEY`、`StorageAddonPlanType`）定义在 `api/internal/entity/storage_quota_entity.py`。

校验失败时抛 `ForbiddenException`（`reason_code='storage_quota_exceeded'`，携带 `total_bytes` / `used_bytes` / `incoming_bytes`），引导用户购买存储扩展包。

> **已知限制**：`check_quota` 与实际写入之间未加事务锁，高并发下存在轻微超额窗口；完整原子化留待后续迭代。

### 17.5 后端实现

#### 17.5.1 LocalStorageService（本地文件存储）

位置：`api/internal/service/storage/local_storage_service.py`

- **存储路径**：`{LOCAL_STORAGE_ROOT}/{year}/{month:02d}/{day:02d}/[folder/]{uuid}.{ext}`
- **默认根目录**：`storage/uploads`（容器内 `/app/api/storage/uploads`）
- **HTTP 访问**：Flask 路由 `/storage/local/<path:key>` 提供文件下载
- **URL 格式**：`{LOCAL_STORAGE_BASE_URL}/storage/local/{key}`（默认相对路径）
- **依赖**：无外部 SDK，仅使用标准库 `os`/`shutil`
- **适用场景**：开发/测试环境、单机部署、CI/CD 流水线

安全考虑：
- 路径穿越防护：拒绝包含 `..` 的 key
- 文件存在性校验：不存在返回 404
- 生产环境建议通过 Nginx 直接代理 `/storage/local/` 到本地目录，避免走 Flask

#### 17.5.2 CosService（腾讯云 COS）

位置：`api/internal/service/cos_service.py`

- **SDK**：`cos_python_sdk_v5==1.9.36`
- **存储路径**：`{year}/{month:02d}/{day:02d}/[folder/]{uuid}.{ext}`
- **URL 格式**：`{COS_DOMAIN}/{key}`（默认匿名可访问）
- **特性**：内置重试机制（`COS_UPLOAD_MAX_ATTEMPTS`）、幂等上传、预签名 URL
- **classmethod 分发**：`get_file_url` 和 `upload_bytes_without_record` 根据 `STORAGE_BACKEND` 分发到对应后端，兼容现有直接调用 classmethod 的代码

#### 17.5.3 AliyunOSSService（阿里云 OSS）

位置：`api/internal/service/storage/aliyun_oss_service.py`

- **SDK**：`oss2==2.19.1`
- **存储路径**：与 COS 一致
- **URL 格式**：`{OSS_DOMAIN}/{key}`（留空则自动拼接 `https://{bucket}.{endpoint}`）
- **特性**：支持预签名 URL（`OSS_PRESIGNED_DOWNLOAD_URL_EXPIRE_SECONDS`）
- **延迟导入**：`oss2` 在首次调用时导入，未安装时不影响其他后端

### 17.6 配置项清单

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `STORAGE_BACKEND` | `local` | 存储后端类型：`local`/`cos`/`oss` |
| `LOCAL_STORAGE_ROOT` | `storage/uploads` | 本地存储根目录 |
| `LOCAL_STORAGE_BASE_URL` | (空) | 本地存储访问基础 URL |
| `COS_SECRET_ID` | - | 腾讯云 COS SecretId |
| `COS_SECRET_KEY` | - | 腾讯云 COS SecretKey |
| `COS_BUCKET` | - | COS Bucket 名称 |
| `COS_REGION` | - | COS 地域 |
| `COS_DOMAIN` | - | COS 访问域名 |
| `OSS_ACCESS_KEY_ID` | - | 阿里云 AccessKey ID |
| `OSS_ACCESS_KEY_SECRET` | - | 阿里云 AccessKey Secret |
| `OSS_ENDPOINT` | - | OSS 端点 |
| `OSS_BUCKET` | - | OSS Bucket 名称 |
| `OSS_DOMAIN` | - | OSS 自定义域名（可选） |

完整配置见 `api/.env.example` 文件存储后端配置区块。

### 17.7 文件元数据模型

所有后端共享 `UploadFile` 表（`api/internal/model/upload_file.py`）存储文件元数据：

| 字段 | 说明 |
|------|------|
| `id` | UUID 主键 |
| `account_id` | 上传者账号 ID |
| `name` | 原始文件名 |
| `key` | 存储后端的对象 key（本地路径/COS key/OSS key） |
| `size` | 文件大小（字节），**`BigInteger`**（P1 由 `Integer` 升级，支撑 GB 级视频素材） |
| `extension` | 扩展名（小写） |
| `mime_type` | MIME 类型 |
| `hash` | SHA3-256 哈希 |
| `storage_backend` | 写入时的后端标识（local/cos/oss）；下载与 URL 生成按此字段路由，为空视为 legacy 后端 |

`key` 字段是后端无关的相对路径，`storage_backend` 记录文件实际所在后端，切换激活后端时历史记录的 `key` 仍可在原后端解析。

### 17.8 文件上传调用链

```
前端 useUploadImage / useUploadFile
  → POST /upload-files/image 或 /upload-files/file
    → account_auth_routes.py：_get_service(CosService).upload_file(...)
      （CosService 在 DI 中绑定到 RuntimeStorageProxy）
  → RuntimeStorageProxy.upload_file(file, only_image, account)
      → account 非空：StorageQuotaService.check_quota(account_id, file_size)   ← 超限抛 ForbiddenException
      → _get_service()（按 storage_config 激活后端惰性构造）
          → [local] LocalStorageService: 写入 storage/uploads/{key}
          → [cos]   CosService: client.put_object(bucket, content, key)
          → [oss]   AliyunOSSService: bucket.put_object(key, content)
          → upload_file 记录写入 storage_backend=激活后端
      → account 非空：StorageQuotaService.add_usage(account_id, upload_file.size)  ← 成功后累加用量
  → RuntimeStorageProxy.get_file_url(key)
      → 按 upload_file.storage_backend 路由（未命中回退激活后端）
          → [local] /storage/local/{key}
          → [cos]   {COS_DOMAIN}/{key}
          → [oss]   {OSS_DOMAIN}/{key}
  → 返回 {"image_url": url} 或 UploadFileResp
```

`upload_bytes`（Agent 生成产物等）走同一代理与同一配额守卫；`upload_bytes_without_record` 不创建记录、不计配额。

### 17.9 切换后端操作指南

**推荐方式：Admin 端运行时切换**。管理员在存储配置板块把目标后端置为激活（`StorageConfigService.set_active_backend`），**无需重启服务**，新上传文件立即进入新后端；历史文件仍按各自 `storage_backend` 访问。各后端的桶/区域/域名等配置项通过 `upsert_config` 写入 `storage_config` 表（密钥类字段不入库）。

**降级方式：环境变量**。`storage_config` 表无激活记录时，运行时代理会降级到 `STORAGE_BACKEND` 环境变量（默认 `local`）。启动时 `ensure_default_config()` 会幂等补齐记录，把环境变量指定的后端标记为激活，保证 Admin 界面与运行时一致。

```bash
# .env 文件（仅作无 DB 配置时的降级方案）
STORAGE_BACKEND=cos
COS_SECRET_ID=your-secret-id
COS_SECRET_KEY=your-secret-key
COS_BUCKET=your-bucket
COS_REGION=ap-beijing
COS_DOMAIN=https://your-bucket.cos.ap-beijing.myqcloud.com
```

> **注意**：环境变量中的密钥/桶配置用于后端 SDK 的客户端初始化与 URL 拼接；`storage_config` 表只保存非敏感的展示配置。

### 17.10 与记忆系统冷存储的关系

记忆系统的冷存储（`cold_storage_manager.py`）目前直接调用 `CosService._get_client()` 和 `_get_bucket()` 访问 COS，**不走 ObjectStoragePort 抽象**。这是历史遗留设计，因为冷存储需要直接操作 COS 客户端进行大文件分片上传。

后续演进计划：将冷存储也纳入 ObjectStoragePort 抽象，统一通过 `STORAGE_BACKEND` 切换。详见 `docs/prd/memory-system/02-storage-and-retrieval.md` §5.3。

### 17.11 安全要求

1. **上传校验**：扩展名白名单（`ALLOWED_IMAGE_EXTENSION` / `ALLOWED_DOCUMENT_EXTENSION` / `ALLOWED_VIDEO_EXTENSION` / `ALLOWED_AUDIO_EXTENSION`，P1 已扩展音视频），单文件大小 ≤ 15MB（分片上传解除上限属后续 P2）
2. **扩展名白名单分层**：存储层（`LocalStorageService` / `CosService` / `AliyunOSSService`）统一用 `allowed_extensions_for_base_type("mixed")` 取**全类型并集**（图片 + 文档 + 视频 + 音频），仅校验"是否为系统允许上传的媒体类型"，**放行 video/audio**，不感知知识库板块语义；板块级细粒度约束由 `KnowledgeBaseService._assert_media_type_allowed` 按 `knowledge_base.base_type` 负责，且**校验前移到落盘之前**，被拒文件不占用配额。详见 [02-knowledge-base.md §11.8.6](./02-knowledge-base.md#1186-存储层白名单的分层设计)
3. **配额校验**：所有上传路径经 `RuntimeStorageProxy` 走 `StorageQuotaService.check_quota`，超限拒绝
4. **路径穿越防护**：本地存储路由拒绝包含 `..` 的 key
5. **匿名访问**：COS/OSS 默认返回匿名可访问 URL，要求 Bucket 为公共读；私有桶需显式开启预签名
6. **文件哈希**：所有上传文件计算 SHA3-256 哈希，存入 `UploadFile.hash` 字段，可用于去重和完整性校验
7. **未来增强**：magic number 校验（`filetype` 库已安装但未启用）、病毒扫描、内容审核

### 17.12 后续演进路线

1. **短期**：✅ 已完成 local/cos/oss 三后端切换（运行时代理分发）
2. **短期**：✅ 已完成存储配额与按 account 计量（`StorageQuotaService` + `account_storage_usage`）
3. **中期**：将 `icon_generator_service` 的图标生成也走 `ObjectStoragePort`（当前绕过直接调用 COS 客户端）
4. **中期**：将 `cold_storage_manager` 纳入 `ObjectStoragePort` 抽象
5. **中期**：分片上传 + 秒传 + 断点续传，解除单文件 15MB 上限（P2）
6. **长期**：支持 AWS S3、MinIO、Azure Blob 等更多后端
7. **长期**：前端直传（STS 临时凭证）
