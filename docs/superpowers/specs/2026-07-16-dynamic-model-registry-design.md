# 动态模型注册表架构设计

**日期**: 2026-07-16
**状态**: 设计待审阅
**作者**: brainstorming 流程产出

## 1. 背景与动机

### 1.1 当前架构的硬约束

当前模型池采用**静态 yaml 注册表**架构：
- `providers.yaml` 定义 10 个内置供应商
- 每个供应商目录下 `positions.yaml` + `{model}.yaml` 定义模型属性
- `LanguageModelManager` 启动时全量加载 yaml 到内存字典
- `_load_model_components` 通过 `get_provider().get_model_entity()` 精确匹配内存字典，匹配失败抛 `NotFoundException`

### 1.2 暴露的问题

1. **无法接入第三方 OpenAI 兼容接口**：用户需配置硅基流动（siliconflow）等第三方供应商，但注册表中无对应 provider，只能错误地复用 `deepseek` provider，导致混淆"模型匹配接口"与"供应商官方接口"
2. **前端下拉数据源缺失**：全新系统的 provider 下拉只能从已加载列表去重，初始为空或仅 3 个硬编码值
3. **无法 CRUD 管理**：废弃供应商无法删除、废弃模型无法弃用，列表越堆越长
4. **yaml 维护成本高**：新增模型需修改代码仓库中的 yaml 文件并重新部署

### 1.3 目标

- **废弃所有静态 yaml 文件**，模型配置全部存入数据库
- 用数据库方式**动态管理所有模型和 key**
- 新增供应商自动注册到数据库，后续下拉直接选择
- 支持**对存入数据的 CRUD 管理**
- **保留 provider 维度 Key 共享机制**（一个 Key 管理同供应商多个模型）
- 支持多种模型类型（chat/multimodal/embedding/image_generation/video_generation/ocr/tts/asr/rerank）
- 支持多种兼容协议（openai/claude）

## 2. 数据库表结构

### 2.1 新增表 `ModelProviderConfig`（供应商）

```sql
id                    UUID PK
name                  String(128) UNIQUE NOT NULL  -- 如 'siliconflow', 'deepseek'
label                 String(255)                  -- 显示名 '硅基流动'
description           Text
icon                  String(512)
background            String(32) DEFAULT '#FFFFFF'
default_base_url      String(512) NOT NULL         -- 供应商统一 base_url
supported_model_types JSONB DEFAULT '["chat"]'     -- 声明该供应商支持哪些模型类型
status                String(32) DEFAULT 'active'  -- active/disabled
created_at            DateTime
updated_at            DateTime
```

**索引**: `ix_model_provider_config_name` (unique), `ix_model_provider_config_status`

### 2.2 改造表 `ModelPoolConfig`（模型）

```diff
- base_url       String(512)  -- 删除，移至 Provider 表
+ model_type     String(32) NOT NULL       -- 模型垂类类型
+ compatible_api String(32) NOT NULL       -- 兼容协议映射
保留: id, provider(→Provider.name 软关联), model_name, display_name,
      tier, capabilities(JSONB), price_per_1k_tokens, max_tokens,
      status, fallback_model_id, priority, created_at, updated_at
```

**新增索引**: `ix_model_pool_config_provider_model` (provider, model_name), `ix_model_pool_config_model_type`

### 2.3 表 `ModelKeyConfig`（Key）不改动

保留现有结构，`provider` 字段按 `Provider.name` 软关联，`model_id` 可选关联具体模型。**provider 维度 Key 共享机制不变**。

### 2.4 边界清晰性

| 数据类别 | 归属表 | 说明 |
|---|---|---|
| base_url | Provider 表 | 同供应商所有模型共享一个 base_url |
| provider 元数据（label/description/icon） | Provider 表 | Model/Key 表不冗余 |
| model_type/model_name/capabilities/pricing | Model 表 | 业务垂类与模型实例属性 |
| key_value/quota/有效期 | Key 表 | 凭证与配额信息 |

### 2.5 model_type 取值范围

| model_type | 说明 | 用途场景 |
|---|---|---|
| `chat` | 文本对话模型 | LLM 核心对话/推理 |
| `multimodal` | 多模态模型 | 图文输入理解 |
| `embedding` | 向量嵌入模型 | 知识库向量化、相似度检索 |
| `image_generation` | 图片生成模型 | 文生图 |
| `video_generation` | 视频生成模型 | 文生视频 |
| `ocr` | OCR 文字识别 | 文档解析、图片文字提取（垂类小模型，成本低） |
| `tts` | 语音合成 | 文字转语音（垂类小模型） |
| `asr` | 语音识别 | 语音转文字（垂类小模型） |
| `rerank` | 重排序模型 | 知识库检索结果重排序（垂类小模型） |

### 2.6 compatible_api 取值范围

| compatible_api | 说明 | 对应内置映射 |
|---|---|---|
| `openai` | OpenAI 兼容协议 | ChatOpenAI / OpenAIEmbeddings / 等 OpenAI 系列类 |
| `claude` | Anthropic Claude 兼容协议 | ChatAnthropic / Claude 系列类 |

**设计要点**：
- `model_type` 与 `compatible_api` 解耦：前者描述"能做什么"，后者描述"用什么协议调用"
- 同一 model_type 可对应不同 compatible_api（如 chat 模型可走 openai 或 claude 协议）
- 后续可扩展新的 compatible_api（如 `gemini`），只需在映射表中添加条目

## 3. 实例化链路改造

### 3.1 当前链路（硬门槛）

```python
_instantiate_language_model(model_config)
  → _load_model_components(model_config)
    → LanguageModelManager.get_provider(provider_name)    # 内存字典查找
    → provider.get_model_entity(model_name)               # 内存字典查找
    → provider.get_model_class(model_entity.model_type)   # 硬编码映射
    ↓ 失败抛 NotFoundException
  → model_class(**attributes, **parameters)
```

### 3.2 改造后链路（懒加载 + 失效缓存）

```python
_instantiate_language_model(model_config)
  → _load_model_components(model_config)
    → LanguageModelManager.get_or_load_provider(provider_name)  # 懒加载
    → provider.get_or_load_model_entity(model_name)             # 懒加载
    → ModelClassRegistry.resolve(compatible_api, model_type)    # 二元组映射
    ↓
  → model_class(**attributes, **parameters)
```

### 3.3 LanguageModelManager 改造

从静态注册表管理器 → 动态懒加载缓存管理器：

```python
class LanguageModelManager:
    _CACHE_TTL_SECONDS = 60

    def __init__(self, db: SQLAlchemy):
        self._db = db
        self._provider_cache: dict[str, tuple[ProviderEntity, float]] = {}  # name → (entity, loaded_at)
        self._model_cache: dict[str, dict[str, tuple[ModelEntity, float]]] = {}  # provider_name → {model_name → (entity, loaded_at)}
        self._lock = threading.RLock()

    def get_or_load_provider(self, provider_name: str) -> ProviderEntity:
        """懒加载供应商，命中缓存直接返回"""
        with self._lock:
            cached = self._provider_cache.get(provider_name)
            if cached and (time.time() - cached[1]) < self._CACHE_TTL_SECONDS:
                return cached[0]
            provider_config = self._db.session.query(ModelProviderConfig).filter_by(
                name=provider_name, status='active'
            ).first()
            if not provider_config:
                raise NotFoundException(f"供应商 {provider_name} 不存在或已禁用")
            entity = self._build_provider_entity(provider_config)
            self._provider_cache[provider_name] = (entity, time.time())
            self._model_cache.setdefault(provider_name, {})
            return entity

    def get_or_load_model_entity(self, provider_name: str, model_name: str) -> ModelEntity:
        """懒加载模型实体"""
        self.get_or_load_provider(provider_name)  # 确保 provider 已加载
        with self._lock:
            cache = self._model_cache.get(provider_name, {})
            cached = cache.get(model_name)
            if cached and (time.time() - cached[1]) < self._CACHE_TTL_SECONDS:
                return cached[0]
            model_config = self._db.session.query(ModelPoolConfig).filter_by(
                provider=provider_name, model_name=model_name, status='active'
            ).first()
            if not model_config:
                raise NotFoundException(f"模型 {model_name} 不存在或已禁用")
            entity = self._build_model_entity(model_config)
            self._model_cache.setdefault(provider_name, {})[model_name] = (entity, time.time())
            return entity

    def invalidate_provider(self, provider_name: str):
        """供应商 CRUD 时调用，失效整个供应商缓存"""
        with self._lock:
            self._provider_cache.pop(provider_name, None)
            self._model_cache.pop(provider_name, None)

    def invalidate_model(self, provider_name: str, model_name: str):
        """模型 CRUD 时调用，失效单个模型缓存"""
        with self._lock:
            if provider_name in self._model_cache:
                self._model_cache[provider_name].pop(model_name, None)

    def invalidate_all(self):
        """全量失效，启动/调试用"""
        with self._lock:
            self._provider_cache.clear()
            self._model_cache.clear()
```

### 3.4 ModelClassRegistry 新增

替代 provider 硬编码 model_class 映射：

```python
class ModelClassRegistry:
    """(compatible_api, model_type) → model_class 映射表"""

    _REGISTRY: dict[tuple[str, str], type] = {
        # OpenAI 兼容协议
        ("openai", "chat"):              ChatOpenAI,
        ("openai", "multimodal"):        ChatOpenAI,
        ("openai", "embedding"):         OpenAIEmbeddings,
        ("openai", "image_generation"):  OpenAIImageGenerator,
        ("openai", "video_generation"):  OpenAIVideoGenerator,
        ("openai", "ocr"):               OpenAICompatibleOCR,
        ("openai", "tts"):               OpenAICompatibleTTS,
        ("openai", "asr"):               OpenAICompatibleASR,
        ("openai", "rerank"):            OpenAICompatibleRerank,
        # Claude 兼容协议
        ("claude", "chat"):              ChatAnthropic,
        ("claude", "multimodal"):        ChatAnthropic,
    }

    @classmethod
    def resolve(cls, compatible_api: str, model_type: str) -> type:
        key = (compatible_api, model_type)
        model_class = cls._REGISTRY.get(key)
        if model_class is None:
            raise NotFoundException(f"不支持的模型类型组合: {compatible_api}/{model_type}")
        return model_class
```

### 3.5 _build_model_entity 从 DB 记录构建

```python
def _build_model_entity(self, model_config: ModelPoolConfig) -> ModelEntity:
    """从 DB 记录构建 ModelEntity（替代从 yaml 构建）"""
    provider_entity = self.get_or_load_provider(model_config.provider)
    return ModelEntity(
        model=model_config.model_name,
        label=model_config.display_name or model_config.model_name,
        model_type=model_config.model_type,
        compatible_api=model_config.compatible_api,
        features=model_config.capabilities or [],
        context_window=model_config.max_tokens or 4096,
        max_output_tokens=model_config.max_tokens or 4096,
        attributes={
            "model": model_config.model_name,
            "openai_api_base": provider_entity.default_base_url,
            "openai_api_key": "",  # 由 attribute_overrides 运行时注入
        },
        parameters=[],
        metadata={
            "pricing": {
                "input": model_config.price_per_1k_tokens or 0,
                "output": model_config.price_per_1k_tokens or 0,
                "currency": "RMB",
            }
        },
    )
```

### 3.6 缓存失效触发点

| CRUD 操作 | 失效方法 | 触发位置 |
|---|---|---|
| 新增/编辑/删除/禁用/启用 Provider | `invalidate_provider(name)` | `admin_model_provider_service` |
| 新增/编辑/删除/禁用/启用 Model | `invalidate_model(provider, model_name)` | `admin_model_pool_service` |
| 应用启动 | `invalidate_all()` | `app.py` 启动钩子 |

**关键规则**：先提交 DB 事务，再失效缓存（避免缓存已失效但事务回滚导致缓存穿透）。

## 4. CRUD 管理接口设计

### 4.1 Provider 管理 API（新增）

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | `/admin/model-providers` | 分页列表（支持 search/status 过滤） | `model_provider:read` |
| GET | `/admin/model-providers/<id>` | 详情 | `model_provider:read` |
| POST | `/admin/model-providers` | 新增（name 唯一校验） | `model_provider:create` |
| PATCH | `/admin/model-providers/<id>` | 编辑（name 不可改） | `model_provider:update` |
| DELETE | `/admin/model-providers/<id>` | 删除（前置校验：无关联模型） | `model_provider:delete` |
| POST | `/admin/model-providers/<id>/disable` | 禁用（级联禁用模型，缓存失效） | `model_provider:update` |
| POST | `/admin/model-providers/<id>/enable` | 启用（不级联启用模型） | `model_provider:update` |
| GET | `/admin/model-providers/options` | 下拉选项（id+name+label+default_base_url+supported_model_types，status=active） | `model_provider:read` |

### 4.2 Model 管理 API（改造现有 `/admin/model-pool/models`）

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | `/admin/model-pool/models` | 分页列表（支持 provider/model_type/status 过滤） | `model_pool:read` |
| GET | `/admin/model-pool/models/<id>` | 详情 | `model_pool:read` |
| POST | `/admin/model-pool/models` | 新增（校验 provider 存在且 active） | `model_pool:create` |
| PATCH | `/admin/model-pool/models/<id>` | 编辑 | `model_pool:update` |
| DELETE | `/admin/model-pool/models/<id>` | 删除（前置校验：无 model_id 精确关联的 Key） | `model_pool:delete` |
| POST | `/admin/model-pool/models/<id>/disable` | 禁用（缓存失效） | `model_pool:update` |
| POST | `/admin/model-pool/models/<id>/enable` | 启用 | `model_pool:update` |
| GET | `/admin/model-pool/models/options` | 下拉选项（id+provider+model_name，按 provider 分组） | `model_pool:read` |

### 4.3 Key 管理 API（保留现有，补充校验）

保留现有 6 个端点不变，仅补充前置校验：
- 新增 Key 时校验 `provider` 存在且 active
- 若填 `model_id`，校验模型存在且 provider 一致

### 4.4 RBAC 权限定义

新增到 `DEFAULT_PERMISSIONS`：

```python
"model_provider:read":    "查看模型供应商",
"model_provider:create":  "创建模型供应商",
"model_provider:update":  "更新模型供应商",
"model_provider:delete":  "删除模型供应商",
"model_pool:read":        "查看模型池",
"model_pool:create":      "创建模型",
"model_pool:update":      "更新模型",
"model_pool:delete":      "删除模型",
```

绑定到 `super_admin` 角色。

### 4.5 前置校验规则

| 操作 | 校验规则 | 失败响应 |
|---|---|---|
| 删除 Provider | `ModelPoolConfig.provider == name` AND `status='active'` 的模型数为 0 | 409 "存在关联模型，请先删除或禁用模型" |
| 删除 Model | `ModelKeyConfig.model_id == str(model.id)` 的 Key 数为 0 | 409 "存在 model_id 精确关联的 Key，请先删除或解绑" |
| 禁用 Provider | 允许，级联禁用其下所有 active 模型 | - |
| 禁用 Model | 允许，缓存失效 | - |
| 删除 Key | 无前置校验（Key 是独立凭证） | - |
| 新增 Model | provider 存在且 active；同 provider 下 model_name 唯一 | 404/409 |
| 新增 Key | provider 存在且 active；若填 model_id，校验模型存在且 provider 一致 | 404/409 |
| 新增 Provider | name 全局唯一 | 409 "供应商已存在" |
| 编辑 Provider | name 不可改（PATCH 请求忽略 name 字段） | - |

**删除 Model 的细化规则**：
- 仅校验 `model_id` 精确匹配的 Key
- provider 维度共享的 Key（`model_id IS NULL`）不阻止删除
- 删除后这些共享 Key 自动服务于同 provider 其他模型

### 4.6 (compatible_api, model_type) 合法组合

```python
ALLOWED_COMPATIBLE_COMBINATIONS = {
    ("openai", "chat"):              True,
    ("openai", "multimodal"):        True,
    ("openai", "embedding"):         True,
    ("openai", "image_generation"):  True,
    ("openai", "video_generation"):  True,
    ("openai", "ocr"):               True,
    ("openai", "tts"):               True,
    ("openai", "asr"):               True,
    ("openai", "rerank"):            True,
    ("claude", "chat"):              True,
    ("claude", "multimodal"):        True,
}
```

前后端共享此规则，前端 compatible_api 选择后 model_type 下拉自动禁用不合法选项。

## 5. 前端改造与下拉联动

### 5.1 页面结构

```
模型池管理（一级菜单）
├── 供应商管理（ModelProvidersView.vue，新增）
├── 模型管理（ModelsView.vue，改造）
└── Key 管理（ModelKeysView.vue，改造）
```

### 5.2 供应商管理页 `ModelProvidersView.vue`（新增）

**列表**：卡片网格布局，遵循项目规范 `a-row/a-col` (xs=24 sm=12 md=8 lg=6 xl=6)：
- 每张卡片显示：图标、label、name、description（截断）、status 标签、模型数量
- 操作按钮：编辑、禁用/启用、删除（需 RBAC 权限）
- 顶部：搜索框 + status 过滤 + 新增按钮

**新增/编辑表单字段**：

| 字段 | 控件 | 必填 | 说明 |
|---|---|---|---|
| name | a-input | 是（仅新增） | 唯一标识，编辑模式禁用 |
| label | a-input | 是 | 显示名 |
| description | a-textarea | 否 | |
| icon | a-input | 否 | 图标 URL |
| background | a-color-picker | 否 | 背景色，默认 #FFFFFF |
| default_base_url | a-input | 是 | 供应商统一 base_url |
| supported_model_types | a-select multiple | 否 | 可选项：9 种 model_type |
| status | a-select | 是 | active/disabled |

### 5.3 模型管理页 `ModelsView.vue`（改造）

**改造点**：
- 移除 provider 从已加载列表去重的逻辑（现有第 135-140 行）
- 移除 base_url 表单字段（从 provider 继承）
- 新增 model_type / compatible_api 字段及联动

**改造后表单字段**：

| 字段 | 控件 | 数据源 | 必填 |
|---|---|---|---|
| provider | a-select | `/admin/model-providers/options` | 是 |
| model_name | a-select（可搜索+允许自定义） | `/admin/model-pool/models/options?provider=xxx` | 是 |
| display_name | a-input | 手动 | 否 |
| model_type | a-select | 固定选项（按 provider supported_model_types 过滤） | 是 |
| compatible_api | a-select | openai / claude | 是 |
| tier | a-select | cheap/standard/premium | 是 |
| capabilities | a-select multiple | 根据 model_type 动态 | 否 |
| price_per_1k_tokens | a-input-number | 手动 | 否 |
| max_tokens | a-input-number | 手动 | 否 |
| fallback_model_id | a-select | 同 provider 下其他模型 | 否 |
| priority | a-input-number | 手动 | 否 |
| status | a-select | active/disabled | 是 |

**关键字段联动**：

1. **provider 选择后**：
   - 自动展示 `default_base_url`（只读，提示"来自供应商"）
   - model_name 下拉过滤为该 provider 下已有模型
   - model_type 下拉过滤为该 provider 的 `supported_model_types`
   - fallback_model_id 下拉过滤为该 provider 下其他模型

2. **model_type 选择后**：capabilities 可选项动态调整：
   - chat → [tool_call, agent_thought, stream]
   - multimodal → [vision, tool_call, stream]
   - embedding → [dimension]
   - image_generation → [size, quality]
   - video_generation → [duration, resolution]
   - ocr → []
   - tts → [voice, format]
   - asr → [language]
   - rerank → [top_n]

3. **compatible_api 选择后**：校验与 model_type 的组合是否支持，不合法选项禁用并提示

### 5.4 Key 管理页（改造）

- provider 下拉改为从 `/admin/model-providers/options` 加载
- 若填 model_id，下拉过滤为所选 provider 下的 active 模型
- 其他字段保持不变

### 5.5 前端服务文件

**新增 `ui/src/services/admin-model-providers.ts`**：

```typescript
export interface ModelProvider {
  id: string
  name: string
  label: string
  description: string
  icon: string
  background: string
  default_base_url: string
  supported_model_types: string[]
  status: 'active' | 'disabled'
  model_count?: number
  created_at: number
  updated_at: number
}

export type ProviderOption = {
  id: string
  name: string
  label: string
  default_base_url: string
  supported_model_types: string[]
}

export const listModelProviders = (params) => get('/admin/model-providers', { params })
export const getModelProvider = (id) => get(`/admin/model-providers/${id}`)
export const createModelProvider = (data) => post('/admin/model-providers', { body: data })
export const updateModelProvider = (id, data) => patch(`/admin/model-providers/${id}`, data)
export const deleteModelProvider = (id) => Delete(`/admin/model-providers/${id}`)
export const disableModelProvider = (id) => post(`/admin/model-providers/${id}/disable`)
export const enableModelProvider = (id) => post(`/admin/model-providers/${id}/enable`)
export const listProviderOptions = () => get('/admin/model-providers/options')
```

### 5.6 国际化新增

`zh-CN.ts` / `en-US.ts` 新增 `admin.modelProviders` 命名空间，包含 title/name/label/defaultBaseUrl/supportedModelTypes/modelCount 等 CRUD 操作提示键。

`admin.modelPool` 命名空间新增 modelType/compatibleApi/baseUrlFromProvider 等。

### 5.7 路由与菜单

**路由**：
```typescript
{
  path: 'model-providers',
  name: 'AdminModelProviders',
  component: () => import('@/views/admin/ModelProvidersView.vue'),
  meta: { requiresPermission: 'model_provider:read' }
}
```

**菜单**：在现有"模型池管理"父菜单下新增子菜单项"供应商管理"，排序在"模型管理"之前。

## 6. 数据迁移与启动逻辑

### 6.1 迁移脚本顺序

```
migration_001_create_provider_table.py
  └── 创建 ModelProviderConfig 表

migration_002_import_builtin_providers.py
  └── 导入 10 个内置供应商（atlascloud/deepseek/moonshot/tongyi/wenxin/ollama/google/zhipu/grok/openai）

migration_003_auto_create_user_providers.py
  └── 扫描现有 ModelPoolConfig，为未匹配的 provider 自动创建记录（保留 base_url）
  └── 注意：此 SQL 在 base_url 字段删除之前执行

migration_004_alter_model_pool_config.py
  ├── 新增 model_type/compatible_api 字段（nullable）
  ├── 回填数据（默认 chat/openai）
  ├── 设为 NOT NULL
  └── 删除 base_url 字段

migration_005_cleanup_yaml_files.py
  └── 标记 yaml 文件已废弃（实际文件删除在部署时手动执行）
```

### 6.2 内置 10 个供应商初始数据

| name | label | default_base_url | supported_model_types |
|---|---|---|---|
| atlascloud | Atlas Cloud | https://api.atlascloud.com/v1 | [chat] |
| deepseek | DeepSeek | https://api.deepseek.com/v1 | [chat] |
| moonshot | 月之暗面 | https://api.moonshot.cn/v1 | [chat] |
| tongyi | 通义千问 | https://dashscope.aliyuncs.com/compatible-mode/v1 | [chat, embedding] |
| wenxin | 文心一言 | https://qianfan.baidubce.com/v2 | [chat] |
| ollama | Ollama | http://localhost:11434/v1 | [chat] |
| google | Google | https://generativelanguage.googleapis.com/v1beta | [chat] |
| zhipu | 智谱AI | https://open.bigmodel.cn/api/paas/v4 | [chat, embedding] |
| grok | xAI Grok | https://api.x.ai/v1 | [chat] |
| openai | OpenAI | https://api.openai.com/v1 | [chat, completion, embedding] |

### 6.3 向后兼容性处理

**关键风险**：现有 DB 中 `ModelPoolConfig` 表已有用户配置的模型记录（如硅基流动）。

**处理策略**：
1. `migration_002` 先导入 10 个内置 provider
2. `migration_003` 扫描现有 `ModelPoolConfig`，对 `provider NOT IN (已导入的 10 个)` 的记录自动创建 Provider 记录
3. 自动创建时 `default_base_url` 取该 provider 下模型的 `base_url`（此 SQL 在 `base_url` 字段删除之前执行）
4. `migration_004` 才删除 `base_url` 字段

**用户配置的硅基流动模型保留策略**：
- 若用户已配置 `provider='siliconflow'` 的模型，迁移脚本会自动创建 `siliconflow` Provider 记录
- `default_base_url` 取用户填写的 `base_url`
- 迁移后用户可继续使用，无需重新配置

### 6.4 启动逻辑改造

**`api/app/http/app.py` 改造点**：

```python
def init_app(app: Flask, db: SQLAlchemy, ...):
    # 改造点 1: LanguageModelManager 初始化改为 DB 驱动
    language_model_manager = LanguageModelManager(db=db)

    # 改造点 2: 启动时清空缓存（首次访问触发懒加载）
    language_model_manager.invalidate_all()

    # 改造点 3: 移除 yaml 加载逻辑
    # 删除: load_providers_from_yaml()、load_model_entities_from_yaml() 等调用

    # 改造点 4: 注入依赖
    injector.binder.bind(LanguageModelManager, to=language_model_manager)
```

### 6.5 yaml 文件废弃清单

完整删除以下文件/目录：

```
api/internal/core/language_model/providers/
├── providers.yaml
├── atlascloud/ (positions.yaml + *.yaml)
├── deepseek/ (positions.yaml + *.yaml)
├── moonshot/ (同上)
├── tongyi/ (同上)
├── wenxin/ (同上)
├── ollama/ (同上)
├── google/ (同上)
├── zhipu/ (同上)
├── grok/ (同上)
└── openai/ (同上)
```

同时改造 `language_model_manager.py`：
- 删除 `_load_providers_from_yaml()` 方法
- 删除 `_load_model_entities_from_yaml()` 方法
- 删除 `yaml.safe_load()` 相关导入
- 删除 `os.path.dirname(__file__)` 路径拼接逻辑

### 6.6 部署顺序

1. 执行 Alembic 迁移（5 个脚本按顺序）
2. 部署新代码（API/Celery/Celery-beat 容器重建）
3. 验证启动日志无 yaml 加载错误
4. 验证 `/admin/model-providers` 返回 10+ 个供应商
5. 验证现有模型记录能正常实例化（懒加载触发）
6. 手动删除 `api/internal/core/language_model/providers/` 目录下的 yaml 文件
7. 重建 UI 容器，验证前端页面

## 7. 错误处理与边界场景

### 7.1 缓存一致性

| 场景 | 处理策略 |
|---|---|
| 多 Celery worker 并发首次加载同一 provider | RLock 互斥，构建完成后后续 worker 命中缓存 |
| API 实例 CRUD，Celery 实例缓存未失效 | 接受短暂不一致（TTL 60s 兜底） |
| DB 事务回滚后缓存已失效 | 下次访问重新加载，无影响 |
| Provider 被禁用，缓存中仍有该 Provider 的 Model | `invalidate_provider` 清空整个 provider 的 model 缓存 |

### 7.2 运行时降级

| 场景 | 行为 |
|---|---|
| `select_model_with_fallback` 无 active 模型 | 返回 `(None, [])` |
| `select_key_for_model` 无可用 Key | 返回 None，降级到 `_DEFAULT_RUNTIME_FALLBACK_MODEL_CONFIG`（deepseek-chat） |
| 模型实例化失败（DB 无记录） | NotFoundException 被静默捕获，降级到 deepseek-chat |
| Provider 被禁用但运行时仍尝试加载 | `get_or_load_provider` 查询 status='active'，禁用的 Provider 返回 NotFoundException，触发降级 |
| 缓存命中但 DB 中记录已被删除 | TTL 60s 后重新查询返回 NotFoundException，触发降级 |

### 7.3 base_url 改造

`build_llm_config` 改造点（base_url 从 Provider 表获取，复用缓存避免额外 DB 查询）：

```python
def build_llm_config(self, model: ModelPoolConfig, key: ModelKeyConfig) -> dict:
    api_key = _decrypt_key_value(key.key_value_encrypted)
    config = {
        "provider": model.provider,
        "model": model.model_name,
        "api_key": api_key,
    }
    # 通过 LanguageModelManager 缓存获取 Provider
    provider_entity = language_model_manager.get_or_load_provider(model.provider)
    if provider_entity.default_base_url:
        config["base_url"] = provider_entity.default_base_url
    return config
```

### 7.4 禁用 Provider 的级联逻辑

```python
def disable_provider(self, provider_id):
    provider = self._get_provider_or_404(provider_id)
    provider.status = 'disabled'

    # 级联禁用该 provider 下所有 active 模型
    affected_models = self._db.session.query(ModelPoolConfig).filter(
        ModelPoolConfig.provider == provider.name,
        ModelPoolConfig.status == 'active'
    ).all()

    for model in affected_models:
        model.status = 'disabled'
        language_model_manager.invalidate_model(model.provider, model.model_name)

    language_model_manager.invalidate_provider(provider.name)
    self._db.session.commit()
```

**启用 Provider 的反向逻辑**：仅启用 Provider 本身，**不自动启用**其下被禁用的模型（避免误启用用户主动禁用的模型），用户需手动逐个启用模型。

### 7.5 并发安全

- **缓存读写**：RLock 保护（Celery 多线程场景）
- **CRUD 操作**：依赖 DB 事务隔离（现有机制不变）
- **缓存失效**：先提交 DB 事务，再失效缓存

### 7.6 日志与可观测性

```python
logger.info("Provider 缓存失效: name=%s, trigger=%s", name, operation)
logger.info("Model 缓存失效: provider=%s, model=%s, trigger=%s", provider, model, operation)
logger.warning("模型实例化失败，降级到 deepseek-chat: provider=%s, model=%s, error=%s", ...)
```

## 8. 测试策略与验证清单

### 8.1 单元测试

#### `LanguageModelManager`

| 测试用例 | 验证点 |
|---|---|
| `test_get_or_load_provider_cache_hit` | 第二次调用不查询 DB |
| `test_get_or_load_provider_cache_miss` | 首次调用查询 DB 并构建 ProviderEntity |
| `test_get_or_load_provider_not_found` | DB 无记录抛 NotFoundException |
| `test_get_or_load_provider_disabled` | status='disabled' 抛 NotFoundException |
| `test_get_or_load_model_entity_two_level_cache` | provider 命中缓存后，model 首次加载查 DB |
| `test_invalidate_provider_clears_both_levels` | 失效 provider 同时清空其下所有 model 缓存 |
| `test_invalidate_model_only_clears_one` | 失效单个 model 不影响同 provider 其他 model |
| `test_cache_ttl_expiry` | 60s 后缓存过期，重新查 DB |
| `test_concurrent_load_thread_safety` | 多线程并发首次加载，仅查一次 DB |

#### `ModelClassRegistry`

| 测试用例 | 验证点 |
|---|---|
| `test_resolve_openai_chat` | 返回 ChatOpenAI |
| `test_resolve_claude_chat` | 返回 ChatAnthropic |
| `test_resolve_invalid_combination` | `claude/embedding` 抛 NotFoundException |
| `test_resolve_unknown_compatible_api` | 未知 protocol 抛 NotFoundException |

#### `AdminModelProviderService`

| 测试用例 | 验证点 |
|---|---|
| `test_create_provider_unique_name` | 重名抛 ConflictException |
| `test_update_provider_name_ignored` | PATCH 请求中 name 字段被忽略 |
| `test_delete_provider_with_models_conflict` | 存在关联模型抛 ConflictException |
| `test_delete_provider_no_models_success` | 无关联模型删除成功 |
| `test_disable_provider_cascades_models` | 禁用 provider 级联禁用所有 active 模型 |
| `test_enable_provider_no_cascade` | 启用 provider 不自动启用模型 |
| `test_invalidate_cache_called_on_crud` | 所有写操作后触发缓存失效 |

#### `AdminModelPoolService`

| 测试用例 | 验证点 |
|---|---|
| `test_create_model_validates_provider_active` | provider 不存在或 disabled 抛 NotFoundException |
| `test_create_model_duplicate_name` | 同 provider 下重名抛 ConflictException |
| `test_delete_model_with_precise_key_conflict` | model_id 精确匹配的 Key 存在抛 ConflictException |
| `test_delete_model_with_shared_key_allowed` | provider 维度共享 Key 不阻止删除 |
| `test_invalidate_cache_called_on_crud` | 写操作后触发 model 缓存失效 |

#### `build_llm_config`

| 测试用例 | 验证点 |
|---|---|
| `test_build_llm_config_base_url_from_provider` | base_url 从 ProviderEntity 获取 |
| `test_build_llm_config_no_extra_db_query` | 复用 manager 缓存，无额外 DB 查询 |

### 8.2 集成测试

| 测试用例 | 验证点 |
|---|---|
| `test_instantiate_chat_model_full_chain` | DB ModelPoolConfig → ModelEntity → ChatOpenAI 实例化成功 |
| `test_instantiate_multimodal_with_vision_capability` | multimodal 类型 capabilities 含 vision |
| `test_instantiate_embedding_model` | embedding 类型走 OpenAIEmbeddings |
| `test_instantiate_fallback_on_not_found` | 模型不存在降级到 deepseek-chat |
| `test_instantiate_fallback_on_provider_disabled` | provider 禁用降级到 deepseek-chat |
| `test_create_provider_then_model_then_key_full_flow` | 完整创建链路 |
| `test_disable_provider_runtime_degradation` | 禁用 provider 后运行时不再选中其模型 |

### 8.3 迁移测试

| 测试用例 | 验证点 |
|---|---|
| `test_migration_imports_10_builtin_providers` | 迁移后 provider 表有 10 条内置记录 |
| `test_migration_preserves_user_custom_providers` | 用户自定义 provider（如 siliconflow）自动创建 |
| `test_migration_preserves_user_base_url` | 用户自定义 base_url 不丢失 |
| `test_migration_backfills_model_type_compatible_api` | 现有模型回填为 chat/openai |
| `test_migration_drops_base_url_column` | ModelPoolConfig.base_url 字段已删除 |
| `test_migration_rollback` | downgrade 可完整回滚 |

### 8.4 部署验证清单（人工执行）

**测试数据**：使用用户已配置的硅基流动模型进行全链路验证。若迁移导致数据无法保留，用户将在新架构中重新添加。

#### 迁移阶段

- [ ] 执行 `alembic upgrade head` 成功
- [ ] DB 查询 `SELECT COUNT(*) FROM model_provider_config` ≥ 10
- [ ] DB 查询 `SELECT name FROM model_provider_config` 包含 10 个内置 name
- [ ] DB 查询硅基流动 provider 记录存在（若用户原已配置）
- [ ] DB 查询 `SELECT COUNT(*) FROM model_pool_config WHERE model_type IS NULL` = 0
- [ ] DB 查询 `SELECT COUNT(*) FROM model_pool_config WHERE compatible_api IS NULL` = 0
- [ ] DB 查询 `SHOW COLUMNS FROM model_pool_config LIKE 'base_url'` 为空

#### 启动阶段

- [ ] API 容器启动无报错
- [ ] Celery 容器启动无报错
- [ ] Celery-beat 容器启动无报错
- [ ] API 日志无 yaml 加载相关错误
- [ ] API 日志无 `LanguageModelManager` 初始化错误

#### 接口验证

- [ ] `GET /admin/model-providers` 返回 200，list 非空
- [ ] `GET /admin/model-providers/options` 返回 200，options 非空
- [ ] `GET /admin/model-pool/models` 返回 200，现有模型可见（含硅基流动）
- [ ] `POST /admin/model-providers` 新增成功
- [ ] `POST /admin/model-pool/models` 关联新 provider 成功
- [ ] `DELETE /admin/model-providers/<id>` 有关联模型时返回 409

#### 运行时验证（使用硅基流动模型）

- [ ] 触发一次 LLM 调用，日志显示懒加载 DB 查询
- [ ] 第二次调用同一模型，日志无 DB 查询（命中缓存）
- [ ] 硅基流动模型全链路调用成功（provider 加载 → model 加载 → Key 匹配 → 实例化 → 调用）
- [ ] 禁用某 provider，运行时降级到 deepseek-chat

#### 前端验证

- [ ] 供应商管理页可见 10 个内置供应商（+硅基流动，若已迁移）
- [ ] 模型管理页 provider 下拉包含所有 active provider
- [ ] 模型管理页表单无 base_url 字段
- [ ] 模型管理页 model_type 下拉包含 9 种类型
- [ ] 模型管理页 compatible_api 下拉包含 openai/claude
- [ ] provider 选择后，model_type 按其 supported_model_types 过滤
- [ ] compatible_api 选择后，model_type 不合法选项禁用

#### yaml 清理

- [ ] 手动删除 `api/internal/core/language_model/providers/*.yaml`
- [ ] 重启 API 容器，启动无报错
- [ ] 所有功能正常

### 8.5 性能验证

| 指标 | 预期 | 验证方法 |
|---|---|---|
| 首次模型实例化延迟 | < 50ms（单次 DB 查询） | 日志时间戳 |
| 缓存命中实例化延迟 | < 1ms | 日志时间戳 |
| CRUD 后缓存失效延迟 | < 1ms（内存操作） | 日志时间戳 |
| 跨进程失效延迟 | ≤ 60s（TTL 兜底） | 手动禁用后观察 Celery 行为 |

### 8.6 回滚预案

**回滚条件**：迁移后系统无法正常实例化模型，且无法快速修复。

**回滚步骤**：
1. `alembic downgrade -1`（逐个回滚迁移脚本）
2. 恢复 yaml 文件目录（从 git 历史检出）
3. 恢复 `LanguageModelManager` 旧代码（从 git 历史检出）
4. 重建 API/Celery/Celery-beat 容器
5. 验证系统恢复

## 9. 文件改动清单

### 9.1 后端新增

```
api/internal/model/
└── model_provider_entity.py                          # ModelProviderConfig ORM

api/internal/service/
└── admin_model_provider_service.py                   # Provider CRUD service

api/internal/handler/
└── admin_model_provider_handler.py                   # Provider HTTP handler

api/internal/schema/
└── admin_model_provider_schema.py                    # Provider 请求/响应 schema

api/internal/core/language_model/
├── model_class_registry.py                           # (compatible_api, model_type) → class
└── entities/
    └── provider_entity.py                            # ProviderEntity 改造（移除 yaml 相关）

api/migrations/versions/
├── migration_001_create_provider_table.py
├── migration_002_import_builtin_providers.py
├── migration_003_auto_create_user_providers.py
├── migration_004_alter_model_pool_config.py
└── migration_005_cleanup_yaml_files.py
```

### 9.2 后端改造

```
api/internal/model/model_pool_entity.py               # ModelPoolConfig 增加 model_type/compatible_api，删除 base_url
api/internal/core/language_model/language_model_manager.py  # 改造为懒加载缓存
api/internal/service/language_model_service.py        # _load_model_components 改造
api/internal/service/runtime_model_pool_service.py    # build_llm_config 改造（base_url 从 provider 获取）
api/internal/service/admin_model_pool_service.py      # 增加 provider 校验、缓存失效触发
api/internal/schema/admin_model_pool_schema.py        # 补充 model_type/compatible_api 字段
api/internal/router/router.py                         # 注册 Provider 路由
api/internal/extension/extension.py                   # DEFAULT_PERMISSIONS 新增权限
api/app/http/app.py                                   # 启动逻辑改造
```

### 9.3 后端删除

```
api/internal/core/language_model/providers/           # 整个目录（所有 yaml 文件）
```

### 9.4 前端新增

```
ui/src/services/admin-model-providers.ts              # Provider API service
ui/src/views/admin/ModelProvidersView.vue             # Provider 管理页
```

### 9.5 前端改造

```
ui/src/views/admin/ModelsView.vue                     # 表单改造（model_type/compatible_api 联动，移除 base_url）
ui/src/views/admin/ModelKeysView.vue                  # provider 下拉数据源改造
ui/src/router/index.ts                                # 新增 provider 路由
ui/src/i18n/messages/zh-CN.ts                         # 新增 modelProviders 命名空间
ui/src/i18n/messages/en-US.ts                         # 同上
ui/src/menu/                                          # 新增供应商管理菜单项
```

## 10. 实施顺序建议

1. **后端数据层**：ModelProviderConfig 实体 + 迁移脚本 1-4
2. **后端核心改造**：LanguageModelManager + ModelClassRegistry + _build_model_entity
3. **后端 Service/Handler**：AdminModelProviderService + AdminModelPoolService 改造
4. **后端路由与权限**：router.py + DEFAULT_PERMISSIONS
5. **后端启动验证**：app.py 改造 + 容器重建 + 接口验证
6. **前端服务与页面**：admin-model-providers.ts + ModelProvidersView.vue
7. **前端模型页改造**：ModelsView.vue 表单联动
8. **前端 Key 页改造**：ModelKeysView.vue
9. **yaml 清理**：迁移脚本 5 + 手动删除 yaml 文件 + 最终验证
10. **全链路测试**：使用硅基流动模型端到端验证

## 11. 用户配置保留策略

**用户已配置的硅基流动模型**：
- 迁移脚本 003 会自动扫描 `ModelPoolConfig`，为 `provider='siliconflow'`（或用户填写的其他 provider 名）自动创建 Provider 记录
- `default_base_url` 取用户填写的 `base_url`，不丢失
- 迁移后模型记录继续可用，无需重新配置

**若迁移导致数据无法保留**：
- 用户将在新架构中重新添加硅基流动 provider 和模型
- 新增流程：供应商管理页新增 provider → 模型管理页新增模型 → Key 管理页新增 Key
- 全程数据库 CRUD，无需修改代码
