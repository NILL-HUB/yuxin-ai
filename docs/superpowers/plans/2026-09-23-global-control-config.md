# 全局控制配置板块整合计划

> 状态：待执行（2026-09-23，用户已确认范围 A+B+C）
> 关联：config-governance（admin 统一配置化管理）、config-inventory.md D/C 级收编

## 目标

在 admin「系统配置」菜单下新增 **全局控制配置**（`/admin/global-control-config`），收编 8 项全局行为配置；公共 AI 配置恢复纯「模型绑定」语义；桌面客户端连接并入；3 个散落 env 业务开关收编。

## 收编清单（A+B+C）

| # | 配置 | 当前形态 | 去向 |
|---|---|---|---|
| 1 | 模型运行时降级（重连次数 + 同档候选轮换开关） | `public_ai_feature_config` runtime_fallback（enabled + extra_config.retry_attempts） | 新表 `runtime_fallback` section |
| 2 | 外部素材体积上限 + fetch_media 开关 | runtime_fallback 同表的 media_fetch（enabled + extra_config.max_bytes_fallback） | 新表 `media_fetch` section |
| 3 | 会话级 Checkpoint 开关 | `agent_checkpoint_by_conversation` feature（enabled） | 新表 `agent_checkpoint` section |
| 4 | 桌面客户端连接（api_origin） | 独立菜单 `/admin/desktop-client-config` + `desktop_client_config` 表 | 前端并入新页面（**数据/服务不动**，仅编辑入口合并） |
| 5 | 技能目录同步开关 `SKILL_CATALOG_SYNC_ENABLED` | env（config.py:197，app.py:46 启动消费，默认关） | 新表 `skill_catalog_sync` section |
| 6 | 图像请求策略 `IMAGE_REQUEST_POLICY` | env（language_model_service.py:1144，默认 strict） | 新表 `image_request_policy` section |
| 7 | 视觉兜底模型 `VISION_FALLBACK_PROVIDER/MODEL` | env（language_model_service.py:1162） | 新表 `vision_fallback` section |

公共 AI 配置三条旧 feature（runtime_fallback / media_fetch / agent_checkpoint_by_conversation）在迁移时**值搬入新表后删除记录**，并从 `_BUILTIN_FEATURES` 移除（不再 seed）；`conductor` / `schedule_intent_parser` / `admin_agent` / `vision_analyze` 等模型绑定类保留不动。

## 后端

1. **新表 `global_control_config`**（单行 `id=1`，`configs JSONB`，沿用 `desktop_client_config` 成熟模式）：
   ```
   {
     "runtime_fallback":      { "enabled": true,  "retry_attempts": 5 },
     "media_fetch":           { "enabled": false, "max_bytes_fallback": 536870912 },
     "agent_checkpoint":      { "enabled": false },
     "skill_catalog_sync":    { "enabled": false },
     "image_request_policy":  { "policy": "strict" },
     "vision_fallback":       { "provider": "", "model": "" }
   }
   ```
   - Alembic 迁移：建表 + **一次性迁移**（读三条旧 feature 记录 → 写入对应 section → 删除旧记录）；`down_revision` 指向已被 git 跟踪的既有 head，收敛单 head。

2. **`GlobalControlConfigService`**：
   - `ensure_default_config()` 启动补齐（与 StorageConfigService 同模式）
   - `get_config(section) -> dict` / `update_config(section, patch)`（白名单 key 校验，与 storage config 同模式）
   - 注入到 module.py

3. **admin API**：`GET/PUT /admin/global-control-config`（权限 `system_config:manage`，与 desktop-client 一致）；section 白名单 + 各字段类型校验。

4. **运行时读取点迁移**（逐一替换，**保留 env 兜底**防断链）：
   | 读取点 | 现位置 | 改读 |
   |---|---|---|
   | `_runtime_fallback_config()` | language_model_service.py | 新表 runtime_fallback |
   | `_load_media_fetch_extra_config()` + 工具挂载 `_enabled()` | media_fetch_service.py | 新表 media_fetch |
   | `_is_checkpoint_by_conversation_enabled()` | assistant_agent_service.py | 新表 agent_checkpoint |
   | 技能目录同步启动消费 | app.py:46 | 新表 skill_catalog_sync |
   | 图片请求策略 | language_model_service.py:1144 | 新表 image_request_policy |
   | 视觉兜底 | language_model_service.py:1162 | 新表 vision_fallback |

5. `public_ai_feature_service._BUILTIN_FEATURES`：移除三条行为开关类 feature（保留模型绑定类）。

## 前端

1. **新页面 `GlobalControlConfigView.vue`**（路由 `/admin/global-control-config`，`system_config:manage`）：分组表单
   - 模型运行时降级（重连次数 + 轮换开关）
   - 外部素材获取（功能开关 + 体积上限 MB）
   - 会话 Checkpoint（开关）
   - 技能目录同步（开关）
   - 图像请求策略（select: strict/auto）
   - 视觉兜底（provider + model 输入）
   - 桌面客户端连接（api_origin）
2. **AdminLayout 菜单**：系统配置下加「全局控制配置」；**删除 desktop-client-config 独立菜单项**。
3. **`PublicAIFeatureConfigView.vue` 瘦身**：移除扩展参数表单（`EXTRA_PARAM_FIELDS` / `buildExtraConfig` / `extraParamValues` / 卡片 extra_config 行），恢复纯模型绑定编辑；同步清理 i18n 键（zh/en 各删 extraParam* 相关、保留公共键）。
4. **i18n**：新页面全量 zh/en；parity 测试通过。

## 测试

- 后端：GlobalControlConfigService 单测（ensure_default / get / update 白名单）、迁移测试、3+2 个读取点迁移测试（language_model / media_fetch / assistant_agent / app 启动 / image_policy / vision）、admin API 测试
- 前端：i18n parity + vue-tsc
- 全量回归

## 文档同步（AGENTS.md 强制）

- `AGENTS.md`「既有 admin 板块清单」表加一行：全局控制配置（`/admin/global-control-config`，表 `global_control_config`，seed `GlobalControlConfigService.ensure_default_config()`）
- `docs/research/config-inventory.md`：C 级 3 项（SKILL_CATALOG_SYNC_ENABLED / IMAGE_REQUEST_POLICY / VISION_FALLBACK_*）→ 已迁移；D 级结论更新（runtime_fallback / media_fetch / agent_checkpoint 改入全局控制配置）
- `docs/README.md`：如有新增顶层文档再登记（本计划属 docs/superpowers，已在导航体系内）
- `python -m graphify update .`

## 风险与注意

- **启动顺序**：skill catalog sync 在 app.py 启动消费，收编后读 DB 需确保 DB 可用（MODE != celery 时 app 初始化已完成，DB 可用）
- **默认值保全**：image_request_policy 默认 `strict`、runtime_fallback enabled 默认 true、media_fetch enabled 默认 false、checkpoint 默认 false，新表 seed 必须与现状一致，否则行为漂移
- **env 兜底**：所有运行时读取点改读新表后保留 env 兜底，避免漏配时断链
- **feature 记录清理**：迁移脚本删旧记录时仅在值成功搬入后删除；`ensure_builtin_features` 不再 seed 三条
- **前端 dev 模式**：src 改动 HMR 生效；**API 容器需重启**（FLASK_ENV=production）触发迁移与 seed
