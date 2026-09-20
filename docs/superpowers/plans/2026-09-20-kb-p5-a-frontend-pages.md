# KB-P5-A 前台页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户能在知识库前台完成「浏览板块详情 → 分区树导航 → 网格浏览素材 → 查看素材详情（分段/L2/删除）+ 用量面板扩容」的完整闭环。

**Architecture:** 后端 API 全部已就绪，仅补两处小改：① `GET /space/storage/usage` 路由（调用既有 `StorageQuotaService.get_usage_summary`，注册进 [knowledge_mcp_routes.py](../../../api/app/http/knowledge_mcp_routes.py) 的 `register_routes`）；② 文档列表/详情 schema 补 `media_type` / `content_type` / `parse_profile` 三个直读字段（`KnowledgeDocument` 模型皆有，零 service 改动），供前端网格渲染媒体图标/状态。前端新增 detail 目录（容器 + 分区树 + 素材网格 + 素材详情抽屉 + 用量面板四组件），新路由 `space-datasets-detail`，板块列表卡片跳转改到此页。

**Tech Stack:** Quart / marshmallow / Python 3.12；Vue 3 `<script setup>` + TypeScript + Arco Design（a-tree/a-table/avatar）+ Pinia + Vitest + @vue/test-utils；i18n（zh-CN/en-US 双侧同步，parity spec 把关）

---

## 0. 现状核对摘要（2026-09-20 实测）

| 事实 | 依据 |
| --- | --- |
| 后端板块/分区/文档/分段/外部数据源 API 全量已有 | [knowledge_mcp_routes.py](../../../api/app/http/knowledge_mcp_routes.py) `GET/POST /space/knowledge-bases`、`GET .../<id>`、`GET/POST .../<id>/partitions`、`GET .../documents`、`GET .../documents/<id>`、`POST .../documents/<id>/l2`、`GET .../documents/<id>/segments` |
| `get_usage_summary` 已实现、**未暴露路由** | [storage_quota_service.py](../../../api/internal/service/storage_quota_service.py) L136；`StorageQuotaService` 已 bind 单例（module.py L122） |
| 扩容下单链路现成（`storage_addon`） | [commerce_routes.py](../../../api/app/http/commerce_routes.py) `GET /plans`、`POST /orders` |
| 文档模型含 `media_type` / `content_type` / `parse_profile` | [knowledge.py](../../../api/internal/model/knowledge.py) L79/L86/L88 |
| 文档列表/详情 schema **不含**上述字段 | [knowledge_base_schema.py](../../../api/internal/schema/knowledge_base_schema.py) L176/L205 |
| 前端板块列表（卡片）、文档列表（a-table）、分段卡片、外部数据源弹窗已存在 | `ui/src/views/space/datasets/` 对应文件 |
| 前端 hooks 齐备 | `use-get-knowledge-base.ts`：`useGetKnowledgeDocumentsWithPage` / `useGetKnowledgeDocument` / `useGetKnowledgeSegmentsWithPage` |
| i18n 现有字典为分模块单文件（`space.ts` 等），`space.datasets.*` 键已在使用 | `ui/src/i18n/messages/zh-CN/space.ts` |
| 路由注册在 `ui/src/router/index.ts` | `my-knowledge` / `space-datasets-documents-list` / `space-datasets-documents-segments-list` |

**本计划不涉及**：新数据表/迁移（无 schema 变更）、权限点、小钰帮传（KB-P5-B）、外部数据源配额（KB-P5-C）。

---

## 1. 文件结构规划

### 后端

| 文件 | 职责 |
| --- | --- |
| Modify: `api/app/http/knowledge_mcp_routes.py` | 在 `register_routes` 内新增 `GET /space/storage/usage`（`_resolve_account` + `StorageQuotaService.get_usage_summary`） |
| Modify: `api/internal/schema/knowledge_base_schema.py` | `GetKnowledgeDocumentsWithPageResp` / `GetKnowledgeDocumentResp` 各补 `media_type` / `content_type` / `parse_profile` 直读字段 |
| Modify: `api/test/app/http/test_knowledge_mcp_routes.py` | usage 路由用例 + 文档 schema 字段透出用例（按文件既有写法追加） |

### 前端

| 文件 | 职责 |
| --- | --- |
| Create: `ui/src/services/storage-usage.ts` | `getStorageUsage()` 调 `GET /space/storage/usage`；`resolveUpgradeUrl()` → `/membership`（引入路径经核对） |
| Create: `ui/src/models/storage-usage.ts` | 响应类型（total/used/remaining/percent） |
| Create: `ui/src/views/space/datasets/detail/IndexView.vue` | 板块详情容器：头部（返回/图标/名称/标签 + 用量面板）+ 左分区树 + 右素材网格 + 素材详情抽屉 |
| Create: `ui/src/views/space/datasets/detail/components/PartitionTreeNav.vue` | 分区树（两层级，`a-tree`），选中分区触发过滤；根节点 = 全部素材 |
| Create: `ui/src/views/space/datasets/detail/components/MaterialGrid.vue` | 素材网格卡片（图标按 media_type + 状态角标 + 名称 + 分段/字数 + 时间），`a-table` ⇄ 网格切换；虚拟滚动或简单分页 |
| Create: `ui/src/views/space/datasets/detail/components/MaterialDetailDrawer.vue` | 素材详情抽屉：基本信息 + 分段列表 + L2 触发按钮 + 删除 |
| Create: `ui/src/views/space/datasets/detail/components/UsagePanel.vue` | 用量概览卡（进度条 + 数值 + 扩容按钮→`/membership`） |
| Modify: `ui/src/router/index.ts` | 注册 `space-datasets-detail`（path `my-knowledge/:dataset_id`，requiresAuth） |
| Modify: `ui/src/views/space/datasets/ListView.vue` | 卡片跳转改 `space-datasets-detail` |
| Modify: `ui/src/i18n/messages/zh-CN/space.ts` + `en-US/space.ts` | `space.datasets.detail.*` 字典（双侧） |

### 测试

| 文件 | 用例 |
| --- | --- |
| `api/test/app/http/test_knowledge_mcp_routes.py` | usage 返回 4 字段；文档列表带 media_type |
| `ui/src/views/space/datasets/detail/components/__tests__/*.spec.ts` | UsagePanel / PartitionTreeNav / MaterialGrid / MaterialDetailDrawer 各 1-2 例 |
| `ui/src/views/space/datasets/detail/__tests__/IndexView.spec.ts` | 组装 + 分区过滤联动 |

> 现有 `space.datasets.documents.*` 与分段页面**保留**（深度链接/既有入口不下线）。网格为新增视图，不删除 a-table。

---

## Task A1: 后端 `GET /space/storage/usage` 路由

**Files:**
- Modify: `api/app/http/knowledge_mcp_routes.py`
- Test: `api/test/app/http/test_knowledge_mcp_routes.py`

- [ ] **Step 1: 写失败的测试**

在 `api/test/app/http/test_knowledge_mcp_routes.py` 末尾追加（沿用文件既有 `_resolve_account`/client mock 机制；若该文件无现成 app 夹具，参照 `test_app_main.py` 的做法）：

```python
def test_storage_usage_returns_quota_summary(monkeypatch):
    """GET /space/storage/usage 返回 total/used/remaining/percent。"""
    import internal.service.storage_quota_service as mod
    calls = {}

    class _FakeQuota:
        def get_usage_summary(self, account_id):
            calls["account_id"] = account_id
            return {
                "total_bytes": 100,
                "used_bytes": 30,
                "remaining_bytes": 70,
                "usage_percent": 30.0,
            }

    monkeypatch.setattr(mod.StorageQuotaService, "get_usage_summary", _FakeQuota().get_usage_summary)
    # ... 用既有测试的 app 客户端 GET /space/storage/usage（携带登录态）
    # resp.status == 200 且 resp.json["data"] == 上述 4 字段
```

> 若该文件测试结构不便注入，可在 `_get_service` 处替换：`monkeypatch.setattr(knowledge_mcp_routes, "_get_service", lambda _: _FakeQuota())`。**以文件既有写法为准**——先读文件的 app 夹具，照抄其 client 用法。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/app/http/test_knowledge_mcp_routes.py -k storage_usage -v`
Expected: FAIL — 404（路由不存在）

- [ ] **Step 3: 实现路由**

在 [knowledge_mcp_routes.py](../../../api/app/http/knowledge_mcp_routes.py) `register_routes` 内、`async_get_knowledge_bases_with_page` 之前插入：

```python
    @quart_app.get("/space/storage/usage")
    async def async_get_storage_usage() -> Response:
        """async 获取用户端存储用量概览（供用量面板）。"""
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import StorageQuotaService

        summary = await _to_thread(
            _get_service(StorageQuotaService).get_usage_summary, account.id
        )
        return _ok(summary)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/app/http/test_knowledge_mcp_routes.py -k storage_usage -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/http/knowledge_mcp_routes.py api/test/app/http/test_knowledge_mcp_routes.py
git commit -m "feat(kb): 暴露用户端存储用量路由 /space/storage/usage（KB-P5-A）"
```

---

## Task A2: 文档列表/详情 schema 补媒体字段

**Files:**
- Modify: `api/internal/schema/knowledge_base_schema.py`
- Test: `api/test/app/http/test_knowledge_mcp_routes.py`（或 schema 单测文件）

- [ ] **Step 1: 写失败的测试**

在 api 测试追加（验证 documents 列表与详情响应含媒体字段）：

```python
def test_document_list_includes_media_fields(monkeypatch):
    """文档列表响应应带 media_type/content_type/parse_profile，网格据此渲染。"""
    # 用既有夹具构造一个 KnowledgeDocument（_FakeService.get_documents_with_page
    # 返回含 media_type="video"、parse_profile={"duration_sec": 12.5} 的假模型），
    # GET /space/knowledge-bases/<id>/documents 后断言 resp["data"]["list"][0] 含三字段。
```

> 实现时需让假模型带 `media_type`/`content_type`/`parse_profile` 属性；schema `pre_dump` 直读即透出。

- [ ] **Step 2: 运行测试确认失败**

Expected: FAIL — `KeyError: 'media_type'`

- [ ] **Step 3: 实现 schema 扩展**

`GetKnowledgeDocumentsWithPageResp`：

```python
    id = fields.UUID(dump_default="")
    name = fields.String(dump_default="")
    media_type = fields.String(dump_default="document")
    content_type = fields.String(dump_default="document")
    parse_profile = fields.Dict(dump_default=dict)
    character_count = fields.Integer(dump_default=0)
    segment_count = fields.Integer(dump_default=0)
    segment_character_count = fields.Integer(dump_default=0)
    status = fields.String(dump_default="")
    error = fields.String(dump_default="")
    updated_at = fields.Integer(dump_default=0)
    created_at = fields.Integer(dump_default=0)

    @pre_dump
    def process_data(self, data: KnowledgeDocument, **kwargs):
        return {
            "id": data.id,
            "name": data.name,
            "media_type": data.media_type,
            "content_type": data.content_type,
            "parse_profile": data.parse_profile or {},
            "character_count": data.character_count,
            "segment_count": getattr(data, "segment_count", 0),
            "segment_character_count": getattr(data, "segment_character_count", data.character_count or 0),
            "status": data.status,
            "error": data.error,
            "updated_at": datetime_to_timestamp(data.updated_at),
            "created_at": datetime_to_timestamp(data.created_at),
        }
```

`GetKnowledgeDocumentResp` 同样补 `media_type` / `content_type` / `parse_profile`（`pre_dump` 直读）。

- [ ] **Step 4: 运行测试确认通过**

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/internal/schema/knowledge_base_schema.py api/test/app/http/test_knowledge_mcp_routes.py
git commit -m "feat(kb): 文档列表/详情透出媒体字段 media_type/parse_profile（KB-P5-A）"
```

---

## Task A3: 前端模型 + service（storage-usage）

**Files:**
- Create: `ui/src/models/storage-usage.ts`
- Create: `ui/src/services/storage-usage.ts`
- Test: `ui/src/services/__tests__/storage-usage.spec.ts`

- [ ] **Step 1: 写失败的测试**

```ts
// ui/src/services/__tests__/storage-usage.spec.ts
import { describe, expect, it, vi, beforeEach } from 'vitest'

const mocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/utils/fetch', () => ({ get: mocks.get }))

import { getStorageUsage } from '@/services/storage-usage'

describe('getStorageUsage', () => {
  beforeEach(() => mocks.get.mockReset())

  it('调 GET /space/storage/usage 并返回 4 字段', async () => {
    mocks.get.mockResolvedValue({
      data: { total_bytes: 100, used_bytes: 30, remaining_bytes: 70, usage_percent: 30.0 },
    })
    const resp = await getStorageUsage()
    expect(mocks.get).toHaveBeenCalledWith('/space/storage/usage')
    expect(resp.data.usage_percent).toBe(30.0)
  })
})
```

> 若项目用的是 `@/utils/request` 或 axios 实例，**以现有 service 写法为准**（先读 `ui/src/services/knowledge-base.ts` 的 fetch 封装再写）。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd ui && npx vitest run src/services/__tests__/storage-usage.spec.ts`
Expected: FAIL — 模块不存在

- [ ] **Step 3: 实现**

```ts
// ui/src/models/storage-usage.ts
export type StorageUsage = {
  total_bytes: number
  used_bytes: number
  remaining_bytes: number
  usage_percent: number
}

export type GetStorageUsageResponse = { data: StorageUsage }
```

```ts
// ui/src/services/storage-usage.ts
import { get } from '@/utils/fetch' // 以现有封装为准
import type { GetStorageUsageResponse } from '@/models/storage-usage'

export const getStorageUsage = (): Promise<GetStorageUsageResponse> => get('/space/storage/usage')
```

- [ ] **Step 4: 运行测试确认通过** — Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ui/src/models/storage-usage.ts ui/src/services/storage-usage.ts ui/src/services/__tests__/storage-usage.spec.ts
git commit -m "feat(ui): 存储用量 service 与模型（KB-P5-A）"
```

---

## Task A4: UsagePanel.vue

**Files:**
- Create: `ui/src/views/space/datasets/detail/components/UsagePanel.vue`
- Test: `ui/src/views/space/datasets/detail/components/__tests__/UsagePanel.spec.ts`
- Modify: `ui/src/i18n/messages/zh-CN/space.ts` + `en-US/space.ts`

- [ ] **Step 1: 写失败的测试**

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const mocks = vi.hoisted(() => ({ getStorageUsage: vi.fn() }))
vi.mock('@/services/storage-usage', () => ({ getStorageUsage: mocks.getStorageUsage }))
vi.mock('@arco-design/web-vue', () => ({
  Message: { error: vi.fn() },
  Progress: { template: '<div />' },
}))

// 用最小 i18n（仅 detail 键）避免依赖全局字典
const messages = {
  'zh-CN': {
    space: { datasets: {
      detail: { usage: { loadFailed: '用量加载失败' } },
    } },
  },
  'en-US': {
    space: { datasets: {
      detail: { usage: { loadFailed: 'Failed to load usage' } },
    } },
  },
}
const i18n = createI18n({ legacy: false, locale: 'zh-CN', fallbackLocale: 'en-US', messages })

import UsagePanel from '@/views/space/datasets/detail/components/UsagePanel.vue'

describe('UsagePanel', () => {
  beforeEach(() => mocks.getStorageUsage.mockReset())

  it('挂载后拉取用量并渲染百分比', async () => {
    mocks.getStorageUsage.mockResolvedValue({
      data: { total_bytes: 100, used_bytes: 30, remaining_bytes: 70, usage_percent: 30.0 },
    })
    const wrapper = mount(UsagePanel, {
      global: {
        plugins: [i18n],
        stubs: { 'a-progress': { template: '<div />' } },
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('30.0')
    expect(wrapper.text()).toContain('70')
  })

  it('拉取失败渲染错误文案且不崩溃', async () => {
    mocks.getStorageUsage.mockRejectedValue(new Error('boom'))
    const wrapper = mount(UsagePanel, {
      global: { plugins: [i18n], stubs: { 'a-progress': { template: '<div />' } } },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('用量加载失败')
  })
})
```

- [ ] **Step 2: 运行测试确认失败** — Expected: FAIL（组件不存在）

- [ ] **Step 3: 实现组件**

```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getStorageUsage } from '@/services/storage-usage'
import type { StorageUsage } from '@/models/storage-usage'

const { t } = useI18n()
const usage = ref<StorageUsage | null>(null)
const failed = ref(false)
const loading = ref(false)

const formatBytes = (bytes: number) => {
  if (bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const idx = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** idx).toFixed(1)} ${units[idx]}`
}

onMounted(async () => {
  loading.value = true
  try {
    const resp = await getStorageUsage()
    usage.value = resp.data
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="flex flex-col gap-2 rounded-xl border border-border-c bg-surface-2 p-4">
    <div class="flex items-center justify-between">
      <span class="text-sm font-semibold text-text">
        {{ t('space.datasets.detail.usage.title') }}
      </span>
      <a-button size="mini" type="text" @click="failed = false; usage ? null : onMounted()">
        {{ t('space.datasets.detail.usage.refresh') }}
      </a-button>
    </div>

    <template v-if="failed">
      <p class="text-xs text-muted">{{ t('space.datasets.detail.usage.loadFailed') }}</p>
    </template>

    <template v-else-if="usage">
      <a-progress
        :percent="usage.usage_percent / 100"
        :show-text="false"
        class="!w-full"
        status="normal"
      />
      <div class="flex justify-between text-xs text-text-2">
        <span>{{ formatBytes(usage.used_bytes) }} / {{ formatBytes(usage.total_bytes) }}</span>
        <span>{{ usage.usage_percent.toFixed(1) }}%</span>
      </div>
      <a-button size="small" type="primary" class="rounded-lg" @click="window.location.href = '/membership'">
        {{ t('space.datasets.detail.usage.upgrade') }}
      </a-button>
    </template>

    <a-skeleton-line v-else :widths="['100%']" />
  </div>
</template>
```

> 扩容跳转：`/membership` 已有路由（membership-index）。若产品要求从 `/plans` 精确选择 storage_addon，可改跳 `{ name: 'membership-index', query: { plan_type: 'storage_addon' } }`——**以 roadmap 验收口径「扩容入口可达」为准**。

- [ ] **Step 4: 字典双侧同步**

`zh-CN/space.ts` 的 `space.datasets` 下追加：

```ts
    detail: {
      usage: {
        title: '存储用量',
        refresh: '刷新',
        loadFailed: '用量加载失败，请稍后重试',
        upgrade: '扩容',
      },
    },
```

`en-US/space.ts` 对应追加：

```ts
    detail: {
      usage: {
        title: 'Storage Usage',
        refresh: 'Refresh',
        loadFailed: 'Failed to load usage',
        upgrade: 'Upgrade',
      },
    },
```

- [ ] **Step 5: 运行测试 + parity**

Run: `cd ui && npx vitest run src/views/space/datasets/detail/components/__tests__/UsagePanel.spec.ts src/i18n/__tests__/parity.spec.ts`
Expected: PASS（组件 2 例 + parity 通过）

- [ ] **Step 6: Commit**

```bash
git add ui/src/views/space/datasets/detail/components/UsagePanel.vue ui/src/views/space/datasets/detail/components/__tests__/UsagePanel.spec.ts ui/src/i18n/messages/zh-CN/space.ts ui/src/i18n/messages/en-US/space.ts
git commit -m "feat(ui): 存储用量面板 UsagePanel（KB-P5-A）"
```

---

## Task A5: PartitionTreeNav.vue

**Files:**
- Create: `ui/src/views/space/datasets/detail/components/PartitionTreeNav.vue`
- Test: `ui/src/views/space/datasets/detail/components/__tests__/PartitionTreeNav.spec.ts`
- Modify: `ui/src/hooks/use-knowledge-base.ts`（若缺分区 hook 则内联调用 service）

- [ ] **Step 1: 写失败的测试**

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const mocks = vi.hoisted(() => ({ getPartitions: vi.fn() }))
vi.mock('@/services/knowledge-base', () => ({ getPartitions: mocks.getPartitions }))
vi.mock('@arco-design/web-vue', () => ({ Message: { error: vi.fn() } }))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': { space: { datasets: { detail: { partitions: { all: '全部素材' } } } } },
    'en-US': { space: { datasets: { detail: { partitions: { all: 'All materials' } } } } },
  },
})

import PartitionTreeNav from '@/views/space/datasets/detail/components/PartitionTreeNav.vue'

describe('PartitionTreeNav', () => {
  beforeEach(() => mocks.getPartitions.mockReset())

  it('挂载后拉取分区树并渲染，含「全部素材」根节点', async () => {
    mocks.getPartitions.mockResolvedValue({
      data: [
        { id: 'p1', name: '2026-09', partition_key: '2026-09', parent_id: '', sort_order: 1 },
        { id: 'p1-1', name: 'Uploads', partition_key: '2026-09/uploads', parent_id: 'p1', sort_order: 1 },
      ],
    })
    const wrapper = mount(PartitionTreeNav, {
      props: { knowledgeBaseId: 'kb-1' },
      global: { plugins: [i18n] },
    })
    await flushPromises()
    expect(mocks.getPartitions).toHaveBeenCalledWith('kb-1')
    expect(wrapper.text()).toContain('全部素材')
    expect(wrapper.text()).toContain('2026-09')
  })

  it('点击节点 emit select 事件与分区 key', async () => {
    mocks.getPartitions.mockResolvedValue({ data: [] })
    const wrapper = mount(PartitionTreeNav, {
      props: { knowledgeBaseId: 'kb-1' },
      global: { plugins: [i18n] },
    })
    await flushPromises()
    // 触发根节点点击
    await wrapper.find('[data-test="nav-all"]').trigger('click')
    const emitted = wrapper.emitted('select')
    expect(emitted).toBeTruthy()
    expect(emitted![0][0]).toBe('')
  })
})
```

- [ ] **Step 2: 运行测试确认失败** — Expected: FAIL

- [ ] **Step 3: 实现组件**

```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getPartitions } from '@/services/knowledge-base'

const props = defineProps<{ knowledgeBaseId: string }>()
const emit = defineEmits<{ (e: 'select', partitionKey: string): void }>()
const { t } = useI18n()

type PartitionNode = {
  id: string
  name: string
  partition_key: string
  parent_id: string
  sort_order: number
}

const treeData = ref<PartitionNode[]>([])
const selectedKey = ref('')

onMounted(async () => {
  const resp = await getPartitions(props.knowledgeBaseId)
  treeData.value = resp.data || []
})

const selectAll = () => {
  selectedKey.value = ''
  emit('select', '')
}

const selectPartition = (node: PartitionNode) => {
  selectedKey.value = node.partition_key
  emit('select', node.partition_key)
}
</script>

<template>
  <div class="flex flex-col gap-1 p-2">
    <button
      data-test="nav-all"
      type="button"
      class="rounded-lg px-3 py-2 text-left text-sm transition"
      :class="selectedKey === '' ? 'bg-brand-soft text-brand-text' : 'text-text-2 hover:bg-surface-2'"
      @click="selectAll"
    >
      {{ t('space.datasets.detail.partitions.all') }}
    </button>
    <button
      v-for="node in treeData"
      :key="node.id"
      type="button"
      class="rounded-lg px-3 py-2 text-left text-sm transition"
      :class="selectedKey === node.partition_key ? 'bg-brand-soft text-brand-text' : 'text-text-2 hover:bg-surface-2'"
      @click="selectPartition(node)"
    >
      {{ node.name }}
    </button>
  </div>
</template>
```

> 两级分区简化为一层展开列表（`parent_id` 为空即一级；子分区缩进由 `sort_order` 派生的 CSS class 处理——首版直接平铺，见下文 A7 若需树形再升级 `a-tree`）。

- [ ] **Step 4: 字典 + 测试 + parity**（追加 `detail.partitions.all` 双侧键）

- [ ] **Step 5: Commit**

---

## Task A6: MaterialGrid.vue（网格 + 表格切换 + 分区过滤）

**Files:**
- Create: `ui/src/views/space/datasets/detail/components/MaterialGrid.vue`
- Test: `ui/src/views/space/datasets/detail/components/__tests__/MaterialGrid.spec.ts`
- Modify: `ui/src/models/knowledge-base.ts`（文档列表类型补 `media_type/content_type/parse_profile`）
- Modify: `ui/src/services/knowledge-base.ts` + `ui/src/hooks/use-knowledge-base.ts`（列表请求补可选 `partition_key` 过滤参数）

- [ ] **Step 1: 列表请求支持分区过滤（前端接线）**

文档列表接口在后端**不含分区过滤**：`get_documents_with_page` 只收 search_word。为让「分区树导航 → 过滤素材」可达，方案：**前端按 `partition_id` 过滤**——需要后端支持。核对后确定：A2 之外再扩展 `GET .../documents` 支持 `partition_key`/`partition_id` 查询参数（后端子任务，本 Task 同步实现）。

本 Task 拆分两个子步骤：
- A6a: 后端 `get_documents_with_page` + 路由支持 `partition_id` 过滤（TDD）
- A6b: 前端 MaterialGrid 网格渲染 + 切换

- [ ] **A6a-1: 写失败测试（后端分区过滤）**

```python
def test_documents_with_page_filters_by_partition(monkeypatch):
    """GET .../documents?partition_id=... 仅返回该分区素材。"""
    # _FakeService.get_documents_with_page 记录收到的 partition_id 参数
```

- [ ] **A6a-3: 实现**

`knowledge_base_service.get_documents_with_page` 增加可选 `partition_id: UUID | None = None`，查询条件追加 `KnowledgeDocument.partition_id == partition_id`（`!= None` 时）。路由读取 `request.args.get("partition_id")` 并以 `_field` 包裹为 `None` 或 `uuid.UUID`，透传。

- [ ] **A6b-1: 写失败测试（前端网格）**

```ts
// MaterialGrid.spec.ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const mocks = vi.hoisted(() => ({ getKnowledgeDocumentsWithPage: vi.fn() }))
vi.mock('@/services/knowledge-base', () => ({ getKnowledgeDocumentsWithPage: mocks.getKnowledgeDocumentsWithPage }))
vi.mock('@arco-design/web-vue', () => ({ Message: { error: vi.fn() } }))

const i18n = createI18n({
  legacy: false, locale: 'zh-CN',
  messages: {
    'zh-CN': {
      space: { datasets: { detail: {
        material: { gridView: '网格', tableView: '表格', empty: '暂无素材', searchPlaceholder: '搜索素材' },
      } } },
    },
    'en-US': {
      space: { datasets: { detail: {
        material: { gridView: 'Grid', tableView: 'Table', empty: 'No materials', searchPlaceholder: 'Search materials' },
      } } },
    },
  },
})

import MaterialGrid from '@/views/space/datasets/detail/components/MaterialGrid.vue'

describe('MaterialGrid', () => {
  beforeEach(() => mocks.getKnowledgeDocumentsWithPage.mockReset())

  it('挂载后按当前分区拉取素材并以网格渲染', async () => {
    mocks.getKnowledgeDocumentsWithPage.mockResolvedValue({
      data: {
        list: [{ id: 'd1', name: 'demo.mp4', media_type: 'video', status: 'completed', character_count: 120, created_at: 1700000000 }],
        paginator: { current_page: 1, page_size: 20, total_page: 1, total_record: 1 },
      },
    })
    const wrapper = mount(MaterialGrid, {
      props: { knowledgeBaseId: 'kb-1', partitionId: '' },
      global: { plugins: [i18n] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('demo.mp4')
    // 网格模式默认；切换表格按钮存在
    expect(wrapper.text()).toContain('表格')
  })

  it('分区变化时重新拉取并携带 partition_id', async () => {
    mocks.getKnowledgeDocumentsWithPage.mockResolvedValue({
      data: { list: [], paginator: { current_page: 1, page_size: 20, total_page: 1, total_record: 0 } },
    })
    const wrapper = mount(MaterialGrid, {
      props: { knowledgeBaseId: 'kb-1', partitionId: '' },
      global: { plugins: [i18n] },
    })
    await wrapper.setProps({ partitionId: 'p-key' })
    await flushPromises()
    expect(mocks.getKnowledgeDocumentsWithPage).toHaveBeenLastCalledWith(
      'kb-1', expect.objectContaining({ partition_id: 'p-key' }),
    )
  })
})
```

- [ ] **A6b-3: 实现组件**

```vue
<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useGetKnowledgeDocumentsWithPage } from '@/hooks/use-knowledge-base'

const props = defineProps<{ knowledgeBaseId: string; partitionId: string }>()
const emit = defineEmits<{ (e: 'open', documentId: string): void }>()
const { t } = useI18n()

const viewMode = ref<'grid' | 'table'>('grid')
const searchWord = ref('')
const { loading, documents, paginator, loadDocuments } = useGetKnowledgeDocumentsWithPage()

const mediaIcon = (mediaType: string) => {
  const map: Record<string, string> = {
    document: 'icon-file', image: 'icon-image', video: 'icon-video', audio: 'icon-audio',
  }
  return map[mediaType] || 'icon-file'
}

watch(
  () => [props.knowledgeBaseId, props.partitionId, searchWord.value] as const,
  ([kb]) => {
    if (!kb) return
    void loadDocuments(kb, {
      current_page: 1,
      page_size: 50,
      search_word: searchWord.value.trim(),
      partition_id: props.partitionId || undefined,
    })
  },
  { immediate: true },
)
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <div class="flex items-center justify-between gap-3 pb-3">
      <a-input
        v-model="searchWord"
        :placeholder="t('space.datasets.detail.material.searchPlaceholder')"
        allow-clear
        class="!w-[220px]"
      />
      <a-radio-group v-model="viewMode" type="button" size="mini">
        <a-radio value="grid">{{ t('space.datasets.detail.material.gridView') }}</a-radio>
        <a-radio value="table">{{ t('space.datasets.detail.material.tableView') }}</a-radio>
      </a-radio-group>
    </div>

    <div v-if="viewMode === 'grid'" class="min-h-0 flex-1 overflow-y-auto">
      <a-grid :cols="4" :col-gap="16" :row-gap="16" v-loading="loading">
        <a-grid-item v-for="doc in documents" :key="doc.id">
          <div
            class="cursor-pointer rounded-xl border border-border-c bg-surface p-3 transition hover:border-brand"
            @click="emit('open', String(doc.id))"
          >
            <div class="flex items-center justify-between">
              <a-avatar shape="square" :size="40" class="rounded-lg bg-brand-soft">
                <template #trigger-icon><icon-font :type="mediaIcon(String(doc.media_type))" /></template>
              </a-avatar>
              <a-tag
                class="rounded-full text-xs"
                :class="doc.status === 'completed' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'"
              >
                {{ doc.status }}
              </a-tag>
            </div>
            <p class="mt-2 line-clamp-1 break-all text-sm font-medium text-text">{{ doc.name }}</p>
            <p class="mt-1 text-xs text-muted">
              {{ doc.character_count }} · {{ new Date(Number(doc.created_at) * 1000).toLocaleDateString() }}
            </p>
          </div>
        </a-grid-item>
      </a-grid>
      <a-empty v-if="!loading && documents.length === 0" class="py-16">
        <template #description>{{ t('space.datasets.detail.material.empty') }}</template>
      </a-empty>
    </div>

    <a-table
      v-else
      row-key="id"
      :loading="loading"
      :data="documents"
      :pagination="{
        total: paginator.total_record,
        current: paginator.current_page,
        pageSize: paginator.page_size,
        showTotal: true, showPageSize: true, pageSizeOptions: [20, 50],
      }"
    >
      <template #columns>
        <a-table-column :title="t('space.datasets.documents.columns.document')" data-index="name" />
        <a-table-column :title="t('space.datasets.documents.columns.characterCount')" data-index="character_count" />
        <a-table-column :title="t('space.datasets.documents.columns.processingStatus')" data-index="status" />
        <a-table-column :title="t('space.datasets.documents.columns.uploadedAt')" data-index="created_at" />
      </template>
    </a-table>
  </div>
</template>
```

> 网格卡片用 media_type 图标 + 状态角标 + 名称 + 字符数/日期。首版不做缩略图（需后端帧图 URL 直出，属 A7 增强项），验收以「媒体区分 + 分区过滤 + 网格/表格切换」为准。

- [ ] **A6b-4: 测试 + parity + Commit**

---

## Task A7: MaterialDetailDrawer.vue

**Files:**
- Create: `ui/src/views/space/datasets/detail/components/MaterialDetailDrawer.vue`
- Test: `ui/src/views/space/datasets/detail/components/__tests__/MaterialDetailDrawer.spec.ts`
- Modify: `ui/src/models/knowledge-base.ts`（详情类型补媒体字段）

- [ ] **Step 1: 写失败测试**

```ts
// MaterialDetailDrawer.spec.ts 核心 2 例
// 1) 打开时并行拉文档详情 + 分段列表，渲染基本信息与分段内容
// 2) 点「L2 深度解析」按钮调用 triggerDocumentL2 且成功后该按钮 loading 复位
```

- [ ] **Step 2: 失败** → **Step 3: 实现**

```vue
<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  useGetKnowledgeDocument,
  useGetKnowledgeSegmentsWithPage,
} from '@/hooks/use-knowledge-base'
import { triggerDocumentL2 } from '@/services/knowledge-base'

const props = defineProps<{ knowledgeBaseId: string; documentId: string | null; visible: boolean }>()
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void; (e: 'deleted'): void }>()
const { t } = useI18n()

const { loading: docLoading, document, loadDocument } = useGetKnowledgeDocument()
const { loading: segLoading, segments, loadSegments } = useGetKnowledgeSegmentsWithPage()
const l2Loading = ref(false)

watch(
  () => [props.visible, props.documentId] as const,
  ([visible, docId]) => {
    if (!visible || !docId || !props.knowledgeBaseId) return
    void loadDocument(props.knowledgeBaseId, docId)
    void loadSegments(props.knowledgeBaseId, docId, true)
  },
  { immediate: true },
)

const handleTriggerL2 = async () => {
  if (!props.documentId) return
  l2Loading.value = true
  try {
    await triggerDocumentL2(props.knowledgeBaseId, props.documentId)
  } finally {
    l2Loading.value = false
  }
}
</script>

<template>
  <a-drawer
    :visible="visible"
    :width="480"
    :footer="false"
    @cancel="emit('update:visible', false)"
  >
    <template #title>
      <span class="text-base font-semibold text-text">{{ document.name || '' }}</span>
    </template>

    <div class="flex flex-col gap-4">
      <div v-loading="docLoading" class="space-y-2 rounded-xl border border-border-c bg-surface-2 p-4">
        <p class="text-sm text-text-2">
          {{ t('space.datasets.detail.material.status') }}:
          <a-tag>{{ document.status || 'waiting' }}</a-tag>
        </p>
        <p class="text-sm text-text-2">
          {{ t('space.datasets.detail.material.segmentCount') }}: {{ document.segment_count ?? 0 }}
        </p>
        <p class="text-sm text-text-2">
          {{ t('space.datasets.detail.material.characterCount') }}: {{ document.character_count ?? 0 }}
        </p>
      </div>

      <div class="flex gap-2">
        <a-button type="primary" size="small" :loading="l2Loading" @click="handleTriggerL2">
          {{ t('space.datasets.detail.material.triggerL2') }}
        </a-button>
      </div>

      <div class="space-y-2">
        <a-skeleton v-if="segLoading" :animation="true" />
        <template v-else>
          <div
            v-for="seg in segments"
            :key="seg.id"
            class="rounded-lg border border-border-c bg-surface p-3"
          >
            <p class="line-clamp-3 text-sm text-text-2">{{ seg.content }}</p>
            <p class="mt-1 text-xs text-muted">#{{ seg.position }}</p>
          </div>
          <a-empty v-if="segments.length === 0">
            <template #description>{{ t('space.datasets.detail.material.noSegments') }}</template>
          </a-empty>
        </template>
      </div>
    </div>
  </a-drawer>
</template>
```

- [ ] **Step 4: 字典 + 测试 + parity + Commit**

---

## Task A8: IndexView.vue 组装 + 路由 + 列表页跳转改造

**Files:**
- Create: `ui/src/views/space/datasets/detail/IndexView.vue`
- Test: `ui/src/views/space/datasets/detail/__tests__/IndexView.spec.ts`
- Modify: `ui/src/router/index.ts`
- Modify: `ui/src/views/space/datasets/ListView.vue`（卡片跳转）
- Modify: `ui/src/i18n/messages/zh-CN/space.ts` + `en-US/space.ts`

- [ ] **Step 1: 写失败测试（组装联动）**

```ts
// IndexView.spec.ts 核心例：渲染后呈现板块名 + 用量面板 + 分区树 + 素材网格；
// 点击分区树某节点 → MaterialGrid props.partitionId 更新。
```

- [ ] **Step 3: 实现 IndexView**

```vue
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useGetKnowledgeBase } from '@/hooks/use-knowledge-base'
import UsagePanel from './components/UsagePanel.vue'
import PartitionTreeNav from './components/PartitionTreeNav.vue'
import MaterialGrid from './components/MaterialGrid.vue'
import MaterialDetailDrawer from './components/MaterialDetailDrawer.vue'

const route = useRoute()
const knowledgeBaseId = computed(() => String(route.params.dataset_id ?? ''))

const { knowledgeBase: dataset, loadKnowledgeBase } = useGetKnowledgeBase()
if (knowledgeBaseId.value) void loadKnowledgeBase(knowledgeBaseId.value)

const currentPartition = ref('')
const drawerDocId = ref<string | null>(null)
const drawerVisible = ref(false)

const openDocument = (documentId: string) => {
  drawerDocId.value = documentId
  drawerVisible.value = true
}
</script>

<template>
  <div class="scrollbar-w-none h-full min-h-0 overflow-y-auto bg-surface-2 px-6 py-6 pb-10">
    <div class="flex min-h-full flex-col gap-4">
      <router-link :to="{ name: 'my-knowledge' }">
        <a-button size="mini" type="text" class="!text-text-2">
          <template #icon><icon-left /></template>
          {{ dataset.name || '' }}
        </a-button>
      </router-link>

      <UsagePanel />

      <div class="grid min-h-0 flex-1 grid-cols-[220px_minmax(0,1fr)] gap-4 overflow-hidden rounded-2xl border border-border-c bg-surface shadow-sm">
        <aside class="min-h-0 overflow-y-auto border-r border-border-c pt-2">
          <PartitionTreeNav :knowledge-base-id="knowledgeBaseId" @select="currentPartition = $event" />
        </aside>
        <section class="min-h-0 p-4">
          <MaterialGrid
            :knowledge-base-id="knowledgeBaseId"
            :partition-id="currentPartition"
            @open="openDocument"
          />
        </section>
      </div>
    </div>

    <MaterialDetailDrawer
      v-model:visible="drawerVisible"
      :knowledge-base-id="knowledgeBaseId"
      :document-id="drawerDocId"
      @deleted="currentPartition && (drawerVisible = false)"
    />
  </div>
</template>
```

- [ ] **Step 4: 注册路由**

`ui/src/router/index.ts` 在 `my-knowledge` 之前（或其后）追加：

```ts
        {
          path: 'my-knowledge/:dataset_id',
          name: 'space-datasets-detail',
          component: () => import('@/views/space/datasets/detail/IndexView.vue'),
          meta: { requiresAuth: true },
        },
```

> `space-datasets-documents-list` 与 segments 路由保留（不冲突：`:dataset_id` 单段、`documents` 显式多段）。

- [ ] **Step 5: ListView 卡片跳转改造**

`ui/src/views/space/datasets/ListView.vue` 中卡片点击（现跳 `space-datasets-documents-list` 的 `router.push`，L280-285 附近）改为：

```ts
router.push({ name: 'space-datasets-detail', params: { dataset_id: id } })
```

- [ ] **Step 6: 字典补齐 + parity + 全量前端测试**

Run: `cd ui && npx vitest run src/i18n/__tests__/parity.spec.ts && npx vitest run src/views/space/datasets`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

---

## Task A9: 全量回归 + 接线自检 + 文档同步

- [ ] **Step 1: 后端全量回归** — `cd api && python -m pytest -q`（预期与基线一致：5200+ passed，2 个既有环境失败不计）
- [ ] **Step 2: 前端全量** — `cd ui && npx vitest run`
- [ ] **Step 3: 接线自检（AGENTS.md 强制）**

| 新符号 | 入口 |
| --- | --- |
| `GET /space/storage/usage` | 前端 `storage-usage.ts`（唯一）→ UsagePanel → IndexView（唯一挂载） |
| 文档 schema `media_type/parse_profile` | 前端 `MaterialGrid` 图标/状态渲染（唯一消费方） |
| `documents?partition_id=` | PartitionTreeNav 选中 → `currentPartition` → MaterialGrid 拉取参数 |
| 前端 detail 组件 | 路由 `space-datasets-detail` + 板块列表卡片跳转（唯一入口） |

- [ ] **Step 4: 文档同步**

`docs/prd/modules/02-knowledge-base.md`：知识库前台用户端页面小节补一句「板块详情/分区树导航/素材网格与详情/用量面板已落地（KB-P5-A）」，并登记 `/space/storage/usage`；`docs/prd/execution-roadmap.md`：KB-P5 行状态改「KB-P5-A 完成（前台页面：详情/分区/网格/用量）」，KB-P5 行整体仍 ⬜（B/C 未做）；`docs/prd/knowledge-base-product-form-design.md` §9.2 KB-P5 行「落地」列补 KB-P5-A 已落地项。

- [ ] **Step 5: graphify** — `python -m graphify update .`
- [ ] **Step 6: Commit（docs 单独一条）**

---

## Self-Review 备注

- **验收链路**：板块列表 → 卡片 → detail 页 → 分区树选中过滤 → 网格/表格切换 → 点素材出抽屉（分段/L2/删除）→ 用量面板真实数据 + 扩容按钮可达 `/membership`。
- **既有页面不删除**：documents a-table 列表与分段页保留，深度链接不回退。
- **延时项（不在首版）**：网格缩略图（frame_url 直出）、`a-tree` 树形分区折叠、素材详情内素材改名/禁用——如需可在 KB-P5-A 收尾后追加增补任务。