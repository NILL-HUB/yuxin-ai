# 配置治理：admin 统一化审计清单

> 状态：审计快照（非权威，代表 2026-09-22 排查时点；2026-09-23 按「全局控制配置」收编更新；2026-09-25 按「工具凭证收敛入口」收编更新）。依据 AGENTS.md「系统配置统一走 admin 管理（强制规则）」执行。
> 分级：A=已修复 / B=死代码待清理 / C=合理保留 env / D=待评估是否迁 admin。

## 背景与结论

系统已有完整 admin 后台（存储 `/admin/storage`、公共 AI 配置 `/admin/public-ai-features`、
系统提示词 `/admin/system-knowledge` 等），但历史代码存在「绕过 admin 直接写 env」的漂移：
存储 cos 的 bucket/region/domain 全读 env，`storage_config` 表保存的配置运行时不被读取——
与 `fetch_media` 开关散落 env 属同一类问题。本次审计对全仓 `os.getenv` 读取点（199 处 / 72 文件，
排除 test）做了分级。

## A. 已修复（本次）

| 项 | 问题 | 修复 |
|---|---|---|
| CosService 配置 | `_get_client`/`_get_bucket`/`get_file_url`/`copy_object` 全读 env，admin `storage_config["cos"]` 不生效 | 新增 `_load_cos_configs()` 惰性读表（configs 优先、env 兜底），密钥仍走 env；`upload_bytes_without_record`/`get_file_url` 后端分发改走 `_load_active_backend()` |
| AliyunOSSService 配置 | `_get_bucket`/`_get_domain`/`copy_object` 全读 env，admin `storage_config["oss"]`（bucket/endpoint/domain 白名单已存在）不生效 | 新增 `_load_oss_configs()`，endpoint/bucket/domain 改 configs 优先、env 兜底，密钥仍走 env |
| LocalStorageService 配置 | `_get_local_storage_root`/`_get_local_storage_base_url` 全读 env，admin `storage_config["local"]`（root/base_url 白名单已存在）不生效 | 新增 `_load_local_configs()`，root/base_url 改 configs 优先、env 兜底；分片暂存根 `CHUNK_UPLOAD_ROOT` 属内部细节，不进 admin 白名单 |
| media_fetch_service 后端归一化 | 上传 backend 存在「空值折叠为 local」的错误归一化 | 改走 `RuntimeStorageProxy.active_backend()`（含 classmethod 兜底 `_load_active_backend()`） |
| image_persistence / atlascloud_shared | 图片持久化 fallback 直接 `CosService` classmethod（绕过激活后端分发） | 改走 `injector.get(RuntimeStorageProxy).upload_bytes_without_record(...)` |
| admin_routes_7 `_build_file_items` | resolved_backend 兜底读 `STORAGE_BACKEND` env | 改走 `runtime_storage_service.active_backend()` |
| `AGENT_CHECKPOINT_BY_CONVERSATION` | `assistant_agent_service.py:1606` 直接读 env 判断是否按会话维度启用 checkpoint | 注册 `agent_checkpoint_by_conversation` feature（category=conversation，`default_enabled=False` 保持默认关闭）；运行时改走 `_is_checkpoint_by_conversation_enabled()` 读 `public_ai_feature_config.enabled`（2026-09-23 已随全局控制配置收编迁入 `global_control_config` section `agent_checkpoint`，见 D 节） |
| `MEDIA_FETCH_MAX_BYTES_FALLBACK` | `media_fetch_service.py:48` 解析不到素材体积时直接读 env 估算兜底 512MB | 并入现有 `media_fetch` feature 的 `extra_config.max_bytes_fallback`，新增 `_load_media_fetch_extra_config()` 读取，缺失时仍 env 兜底（2026-09-23 已随全局控制配置收编迁入 `global_control_config` section `media_fetch`，见 D 节） |

## B. 死代码待清理（未接线，勿继续引用）

| 文件 | 符号 | 说明 |
|---|---|---|
| `api/internal/service/storage/backend.py` | `StorageBackend.from_env()` | 零生产调用方，`STORAGE_BACKEND` env 分发已被 `RuntimeStorageProxy` / `StorageConfigService` 取代 |
| `api/internal/service/storage/factory.py` | `get_storage_service_class()` | 零生产调用方，DI（module.py）已改绑 `RuntimeStorageProxy` |

## C. 合理保留 env（密钥 / 部署基础设施 / 迁移脚本）

- **第三方凭据与密钥**：COS SecretId/SecretKey、OSS AccessKey、OAuth 客户端、外部 API Key（gaode/newsapi/github/stability 等 builtin 工具 provider）——密钥类一律不入库，走 env 是正确位置。
  - **2026-09-25 收编**：builtin 工具 provider 内凭证裸读（17 文件，约 23 处读取点）已统一收敛到
    `internal/service/tool_credential_resolver.py` 的 `get_tool_credential()`；工具层不再直接
    调用 `os.getenv`。**存放位置不变（仍在 env），仅收敛读取方式**；三种缺凭证语义
    （`return None` / 中文提示串 / `raise FailException`）保留在各自调用点。
  - **空白归一（行为收紧）**：统一解析器会对取值 `.strip()`，因此**仅由空白组成的凭证值
    现被视为「缺失」**（此前 `os.getenv` 原样返回空白串会被当作「已配置」）。这是刻意的
    行为收紧，统一了「有值 / 无值」的判据，避免空白 key 被当成有效凭证发起请求。
  - bridge/OS 家族 4 文件内「`resolve_desktop_bridge` 返回 None 后再读 `DESKTOP_BRIDGE_URL`」
    的可证死分支已删除（该静态回退由 `desktop_bridge_resolver` 内部完成）。
- **部署基础设施**：数据库连接、Redis、容器端口、日志级别、Nginx upstream 等（config/config.py、app.py、logging_extension）。
- **一次性迁移脚本**：`internal/migration/**` 中的 env 读取属数据迁移工具，不进运行时 admin 链。
- **业务开关类 env（已迁入全局控制配置，env 仅兜底，2026-09-23）**：`SKILL_CATALOG_SYNC_ENABLED`、`IMAGE_REQUEST_POLICY`、`VISION_FALLBACK_PROVIDER/MODEL` 已迁入 `global_control_config` 表对应 section（`skill_catalog_sync` / `image_request_policy` / `vision_fallback`），运行时优先读表、读表失败时 env 兜底；`.env.example` / `default_config.py` 仍保留默认值作兜底。

## D. 业务开关类（原待评估项，2026-09-23 已全部收编进全局控制配置）

以下 env 是**系统级业务配置**（非密钥、非部署），原散落 env；2026-09-23 已统一收编进 admin「全局控制配置」板块（`global_control_config` 表），env 仅作兜底：

### D.1 评估结论（2026-09-22 初评，2026-09-23 全部收编进全局控制配置）

| env key | 读取点 | 性质 | 归属（收编后） | 状态 |
|---|---|---|---|---|
| `AGENT_CHECKPOINT_BY_CONVERSATION` | `assistant_agent_service.py`（按会话维度启用 checkpoint） | Agent 运行时行为开关（默认关） | `global_control_config` section `agent_checkpoint`（enabled） | ✅ 已迁移（读 `GlobalControlConfigService.get_config("agent_checkpoint")`，env 兜底） |
| `MEDIA_FETCH_MAX_BYTES_FALLBACK` | `media_fetch_service.py`（解析不到素材体积时估算兜底 512MB） | 内部估算兜底，**非业务开关** | `global_control_config` section `media_fetch`（max_bytes_fallback） | ✅ 已迁移（读 `get_config("media_fetch")`，env 兜底） |
| `RUNTIME_FALLBACK_RETRY_ATTEMPTS` | `language_model_service.py`（单模型/Key 运行时重连次数，默认 5） | 模型运行时降级调优参数 | `global_control_config` section `runtime_fallback`（retry_attempts） | ✅ 已迁移（读 `get_config("runtime_fallback")`，env 兜底） |
| `RUNTIME_FALLBACK_ENABLE_POOL_CANDIDATES` | `language_model_service.py`（同档候选轮换，默认开） | 模型运行时降级开关 | `global_control_config` section `runtime_fallback`（enabled，默认 true 语义一致无需反转） | ✅ 已迁移 |
| `SKILL_CATALOG_SYNC_ENABLED` | `app.py`（启动时是否把技能目录同步进知识库，默认关） | 启动行为开关 | `global_control_config` section `skill_catalog_sync`（enabled） | ✅ 已迁移（`_should_sync_skill_catalog_on_startup()` 读 `get_config("skill_catalog_sync")`，env 兜底） |
| `IMAGE_REQUEST_POLICY` | `language_model_service._resolve_image_request_policy()`（图像生成请求在绑定模型不可用时的策略，默认 strict） | 模型运行时行为策略 | `global_control_config` section `image_request_policy`（policy：strict / auto_upgrade） | ✅ 已迁移（读 `get_config("image_request_policy")`，入口级/全局 env 仍优先） |
| `VISION_FALLBACK_PROVIDER/MODEL` | `language_model_service._resolve_fallback_model_config()`（视觉兜底模型） | 模型运行时兜底参数 | `global_control_config` section `vision_fallback`（provider / model） | ✅ 已迁移（读 `get_config("vision_fallback")`，入口级/全局 env 仍优先） |

### D.2 结构性结论

- **收编载体**：`global_control_config` 表（`api/internal/model/global_control_config.py`）单行 id=1 + `configs` JSONB，按 section 分块（`runtime_fallback` / `media_fetch` / `agent_checkpoint` / `skill_catalog_sync` / `image_request_policy` / `vision_fallback`），沿用 `desktop_client_config` 成熟模式。admin 入口：系统配置菜单 → `/admin/global-control-config`（`GlobalControlConfigView.vue`），`GET/PUT /admin/global-control-config`（`admin_routes_8.py`，权限 `system_config:manage`）。
- **运行时读取统一走 `GlobalControlConfigService.get_config(section)`**（`api/internal/service/global_control_config_service.py`，字段白名单 + policy 枚举校验 + 惰性 injector 兜底返回空 dict/False），各读取点保留 env 兜底。`_BUILTIN_FEATURES` 已移除 `runtime_fallback` / `media_fetch` / `agent_checkpoint_by_conversation` 三条行为开关类——`public_ai_feature_config` 恢复纯「模型绑定」语义。
- **启动 seed**：`ensure_default_config()` 在 `run_startup_sync_initialization()`（MODE != celery）中补齐默认行；Alembic 迁移 `g1b2c3d4e5f8_add_global_control_config` 负责建表、读旧 `public_ai_feature_config` 值迁移进新表、删除旧三条记录。
- **桌面客户端连接**（`desktop_client_config` 表 / `api_origin`）：数据与服务不动，仅前端入口并入 `GlobalControlConfigView.vue` 卡片。
- 实施路径：①→②（迁入 `public_ai_feature_config` 中间态）→③（2026-09-23 整体收编进 `global_control_config`，D 级 7 项全部迁完）。

### D.3 死代码（B 级）处置

`backend.py`（`StorageBackend.from_env()`，含整个 `StorageBackend` 枚举）与 `factory.py`（`get_storage_service_class()`）零生产调用方（DI 已改绑 `RuntimeStorageProxy`，后端分发统一走 `get_active_backend()`），已于 2026-09-22 全仓核实引用后整体删除。删除后存储相关测试 189 个全通过。

## 接线说明（本次修复的入口）

- admin 写入入口：`POST /admin/storage/configs/{backend}`（`api/app/http/admin_routes_7.py`，/admin/storage 页面 `AdminStorageView.vue`）；公共 AI 配置 `/admin/public-ai-features`（`PublicAIFeatureConfigView.vue`，纯模型绑定）；全局控制配置 `GET/PUT /admin/global-control-config`（`GlobalControlConfigView.vue`，系统配置菜单）
- 运行时读取点：
  - `CosService._load_cos_configs()`、`AliyunOSSService._load_oss_configs()`、`LocalStorageService._load_local_configs()`（均惰性取 `StorageConfigService.get_config(backend)`，异常时返回 `{}` 由调用方 env 兜底）
  - 全局控制配置统一走 `GlobalControlConfigService.get_config(section)`（表优先、env 兜底）：`assistant_agent_service` 读 `agent_checkpoint`、`media_fetch_service` 读 `media_fetch`、`language_model_service._runtime_fallback_config()` 读 `runtime_fallback`、`_resolve_image_request_policy()` 读 `image_request_policy`、`_resolve_fallback_model_config()` 读 `vision_fallback`、`app._should_sync_skill_catalog_on_startup()` 读 `skill_catalog_sync`
- 激活后端：`StorageConfigService.get_active_backend()`（表激活记录优先、env 兜底）
