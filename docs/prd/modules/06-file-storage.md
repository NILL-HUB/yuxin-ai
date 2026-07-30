# 文件存储与对象存储架构

> 本文档为主架构文档的子模块，包含文件存储与对象存储的完整架构设计：端口抽象、三种后端实现（本地/COS/OSS）、工厂切换、配置项、调用链与安全要求。
>
> **主文档**: [architecture-design.md](../architecture-design.md)
> **相关模块**: [03-orchestration-infra.md](./03-orchestration-infra.md) | [记忆系统/02-storage-and-retrieval.md](../memory-system/02-storage-and-retrieval.md)

---

## 17. 文件存储与对象存储架构

### 17.1 设计目标

系统需要统一管理用户上传的文件（知识库文档、应用图标、AI 生成图片、沙箱产物等），支持在不同部署环境下灵活切换存储后端：

- **开发/测试环境**：使用本地文件系统存储，无需配置云服务账号
- **腾讯云生产环境**：使用腾讯云 COS 对象存储
- **阿里云生产环境**：使用阿里云 OSS 对象存储

通过环境变量 `STORAGE_BACKEND` 一键切换，业务代码无感知。

### 17.2 架构分层

```
┌─────────────────────────────────────────────────────────────┐
│  业务层（Handler / Service）                                 │
│  - UploadFileHandler    - KnowledgeBaseService              │
│  - AdminUploadFileHandler  - IconGeneratorService           │
│  - AppService           - DeepThinkingAgent                 │
└────────────────────────┬────────────────────────────────────┘
                         │ 注入
┌────────────────────────▼────────────────────────────────────┐
│  端口层（ObjectStoragePort Protocol）                        │
│  - upload_file / upload_bytes / download_file               │
│  - upload_bytes_without_record / get_file_url               │
└────────────────────────┬────────────────────────────────────┘
                         │ 绑定（DI 容器根据 STORAGE_BACKEND 选择）
┌────────────────────────▼────────────────────────────────────┐
│  实现层（三种可插拔后端）                                     │
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

#### 17.3.3 StorageFactory（存储工厂）

位置：`api/internal/service/storage/factory.py`

根据 `STORAGE_BACKEND` 环境变量返回对应的后端实现类：

```python
def get_storage_service_class():
    backend = StorageBackend.from_env(default=StorageBackend.LOCAL)
    if backend == StorageBackend.LOCAL:
        return LocalStorageService
    if backend == StorageBackend.COS:
        return CosService
    if backend == StorageBackend.OSS:
        return AliyunOSSService
```

DI 容器在 `app/http/module.py` 中通过工厂动态绑定：

```python
storage_service_class = get_storage_service_class()
binder.bind(ObjectStoragePort, to=storage_service_class)
binder.bind(CosService, to=storage_service_class)  # 兼容现有代码
```

### 17.4 后端实现

#### 17.4.1 LocalStorageService（本地文件存储）

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

#### 17.4.2 CosService（腾讯云 COS）

位置：`api/internal/service/cos_service.py`

- **SDK**：`cos_python_sdk_v5==1.9.36`
- **存储路径**：`{year}/{month:02d}/{day:02d}/[folder/]{uuid}.{ext}`
- **URL 格式**：`{COS_DOMAIN}/{key}`（默认匿名可访问）
- **特性**：内置重试机制（`COS_UPLOAD_MAX_ATTEMPTS`）、幂等上传、预签名 URL
- **classmethod 分发**：`get_file_url` 和 `upload_bytes_without_record` 根据 `STORAGE_BACKEND` 分发到对应后端，兼容现有直接调用 classmethod 的代码

#### 17.4.3 AliyunOSSService（阿里云 OSS）

位置：`api/internal/service/storage/aliyun_oss_service.py`

- **SDK**：`oss2==2.19.1`
- **存储路径**：与 COS 一致
- **URL 格式**：`{OSS_DOMAIN}/{key}`（留空则自动拼接 `https://{bucket}.{endpoint}`）
- **特性**：支持预签名 URL（`OSS_PRESIGNED_DOWNLOAD_URL_EXPIRE_SECONDS`）
- **延迟导入**：`oss2` 在首次调用时导入，未安装时不影响其他后端

### 17.5 配置项清单

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

### 17.6 文件元数据模型

所有后端共享 `UploadFile` 表（`api/internal/model/upload_file.py`）存储文件元数据：

| 字段 | 说明 |
|------|------|
| `id` | UUID 主键 |
| `account_id` | 上传者账号 ID |
| `name` | 原始文件名 |
| `key` | 存储后端的对象 key（本地路径/COS key/OSS key） |
| `size` | 文件大小（字节） |
| `extension` | 扩展名（小写） |
| `mime_type` | MIME 类型 |
| `hash` | SHA3-256 哈希 |

`key` 字段是后端无关的相对路径，切换后端时历史记录的 `key` 仍可解析（前提是新后端能访问到对应文件）。

### 17.7 文件上传调用链

```
前端 useUploadImage / useUploadFile
  → POST /upload-files/image 或 /upload-files/file
  → UploadFileHandler / AdminUploadFileHandler
  → ObjectStoragePort.upload_file(file, only_image, account)
      → [local] LocalStorageService: 写入 storage/uploads/{key}
      → [cos]   CosService: client.put_object(bucket, content, key)
      → [oss]   AliyunOSSService: bucket.put_object(key, content)
  → UploadFileService.create_upload_file(...)  写 DB 记录
  → ObjectStoragePort.get_file_url(key)
      → [local] /storage/local/{key}
      → [cos]   {COS_DOMAIN}/{key}
      → [oss]   {OSS_DOMAIN}/{key}
  → 返回 {"image_url": url} 或 UploadFileResp
```

### 17.8 切换后端操作指南

#### 切换到本地存储（开发环境）

```bash
# .env 文件
STORAGE_BACKEND=local
LOCAL_STORAGE_ROOT=storage/uploads
```

无需其他配置，重启 API 容器即可。文件通过 `/storage/local/{key}` 访问。

#### 切换到腾讯云 COS（生产环境）

```bash
# .env 文件
STORAGE_BACKEND=cos
COS_SECRET_ID=your-secret-id
COS_SECRET_KEY=your-secret-key
COS_BUCKET=your-bucket
COS_REGION=ap-beijing
COS_DOMAIN=https://your-bucket.cos.ap-beijing.myqcloud.com
```

#### 切换到阿里云 OSS（生产环境）

```bash
# .env 文件
STORAGE_BACKEND=oss
OSS_ACCESS_KEY_ID=your-access-key-id
OSS_ACCESS_KEY_SECRET=your-access-key-secret
OSS_ENDPOINT=oss-cn-beijing.aliyuncs.com
OSS_BUCKET=your-bucket
OSS_DOMAIN=https://your-bucket.oss-cn-beijing.aliyuncs.com
```

### 17.9 与记忆系统冷存储的关系

记忆系统的冷存储（`cold_storage_manager.py`）目前直接调用 `CosService._get_client()` 和 `_get_bucket()` 访问 COS，**不走 ObjectStoragePort 抽象**。这是历史遗留设计，因为冷存储需要直接操作 COS 客户端进行大文件分片上传。

后续演进计划：将冷存储也纳入 ObjectStoragePort 抽象，统一通过 `STORAGE_BACKEND` 切换。详见 `docs/prd/memory-system/02-storage-and-retrieval.md` §5.3。

### 17.10 安全要求

1. **上传校验**：扩展名白名单（`ALLOWED_IMAGE_EXTENSION` + `ALLOWED_DOCUMENT_EXTENSION`），文件大小 ≤ 15MB
2. **路径穿越防护**：本地存储路由拒绝包含 `..` 的 key
3. **匿名访问**：COS/OSS 默认返回匿名可访问 URL，要求 Bucket 为公共读；私有桶需显式开启预签名
4. **文件哈希**：所有上传文件计算 SHA3-256 哈希，存入 `UploadFile.hash` 字段，可用于去重和完整性校验
5. **未来增强**：magic number 校验（`filetype` 库已安装但未启用）、病毒扫描、内容审核

### 17.11 后续演进路线

1. **短期**：✅ 已完成 local/cos/oss 三后端切换
2. **中期**：将 `icon_generator_service` 的图标生成也走 `ObjectStoragePort`（当前绕过直接调用 COS 客户端）
3. **中期**：将 `cold_storage_manager` 纳入 `ObjectStoragePort` 抽象
4. **长期**：支持 AWS S3、MinIO、Azure Blob 等更多后端
5. **长期**：前端直传（STS 临时凭证）、分片上传、断点续传
