# 我的应用真实接口接线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让「我的应用」列表展示当前账号真实应用，替换 9 条本地 mock，并清理死代码与 i18n 违规。

**Architecture:** 后端仅补 1 个 schema 字段（`can_edit`）；前端修正 service 泛型、把 `loadApps` 改为真实调用、移除 mock 与草稿徽标、i18n 化硬编码文案。对话链路（`chatWithMyApp`）完全不动。

**Tech Stack:** Python 3.12 + marshmallow + pytest；Vue 3 + TypeScript + vitest + vue-i18n。

**Spec:** `docs/superpowers/specs/2026-09-12-my-apps-real-data-design.md`

---

## 文件结构

| 文件 | 职责 | 动作 |
| --- | --- | --- |
| `api/internal/schema/my_app_schema.py` | `MyAppResp` 序列化契约 | 修改（补 `can_edit`） |
| `api/test/internal/service/test_my_app_service.py` | service 序列化测试 | 修改（补断言） |
| `api/test/app/http/test_my_apps_routes.py` | `/my/apps` 路由测试 | 新建 |
| `ui/src/services/my-apps.ts` | 接口封装 | 修改（泛型） |
| `ui/src/services/__tests__/my-apps.spec.ts` | service 测试 | 修改 |
| `ui/src/views/space/my-apps/ListView.vue` | 页面 | 修改（接线/删 mock/去草稿/补 import） |
| `ui/src/views/space/my-apps/__tests__/ListView.spec.ts` | 页面测试 | 新建 |
| `ui/src/i18n/messages/zh-CN/myApps.ts` | zh 字典 | 修改 |
| `ui/src/i18n/messages/en-US/myApps.ts` | en 字典 | 修改 |

---

### Task 1: 后端 `MyAppResp` 补 `can_edit`

**Files:**
- Modify: `api/internal/schema/my_app_schema.py`
- Test: `api/test/internal/service/test_my_app_service.py`

- [ ] **Step 1: 写失败的测试（schema 契约）**

在 `api/test/internal/service/test_my_app_service.py` 末尾追加：

```python
def test_my_app_resp_schema_should_expose_can_edit():
    """MyAppResp 必须声明 can_edit，否则 marshmallow dump 会丢弃 service 已返回的该字段。"""
    from internal.schema.my_app_schema import MyAppResp

    dumped = MyAppResp().dump(
        {
            "id": "app-1",
            "assignment_id": "asg-1",
            "name": "Contract AI",
            "icon": "",
            "description": "desc",
            "assigned_at": 1893456000,
            "source": "assigned",
            "status": "published",
            "can_edit": False,
        }
    )

    assert "can_edit" in dumped
    assert dumped["can_edit"] is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_my_app_service.py::test_my_app_resp_schema_should_expose_can_edit -q --no-cov`
Expected: FAIL — `assert 'can_edit' in dumped` 失败（键不存在）

- [ ] **Step 3: 补 schema 字段**

修改 `api/internal/schema/my_app_schema.py`，`MyAppResp` 末尾追加一行：

```python
class MyAppResp(Schema):
    id = fields.String()
    assignment_id = fields.String()
    name = fields.String()
    icon = fields.String()
    description = fields.String()
    assigned_at = fields.Integer(allow_none=True)
    source = fields.String(dump_default="assigned")
    status = fields.String(dump_default="")
    can_edit = fields.Boolean(dump_default=False)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_my_app_service.py -q --no-cov`
Expected: PASS（全部用例，含新增 1 个）

- [ ] **Step 5: 提交**

```bash
git add api/internal/schema/my_app_schema.py api/test/internal/service/test_my_app_service.py
git commit -m "feat(my-apps): expose can_edit in MyAppResp schema"
```

---

### Task 2: 后端 `/my/apps` 路由测试（固化契约）

**Files:**
- Test: `api/test/app/http/test_my_apps_routes.py`

- [ ] **Step 1: 写路由测试**

新建 `api/test/app/http/test_my_apps_routes.py`：

```python
"""GET /my/apps 路由测试：验证普通用户可访问且响应含 can_edit。"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.apps_routes import register_routes

register_routes(asgi_app.quart_app)


class _FakeMyAppService:
    def __init__(self):
        self.calls = []

    def list_my_apps(self, account_id):
        self.calls.append(str(account_id))
        return {
            "list": [
                {
                    "id": "app-1",
                    "assignment_id": "asg-1",
                    "name": "Contract AI",
                    "icon": "",
                    "description": "desc",
                    "assigned_at": 1893456000,
                    "source": "assigned",
                    "status": "published",
                    "can_edit": False,
                }
            ]
        }


def test_list_my_apps_returns_can_edit(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    service = _FakeMyAppService()

    async def _fake_resolve_account(account_id_override=None):
        return account, None

    monkeypatch.setattr(support, "_resolve_account", _fake_resolve_account)
    monkeypatch.setattr(support, "_get_service", lambda cls: service)

    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.get("/my/apps")
            return resp, await resp.json

    resp, payload = asyncio.run(_run())
    assert resp.status_code == 200
    assert payload["code"] == "success"
    items = payload["data"]["list"]
    assert len(items) == 1
    assert items[0]["can_edit"] is False
    assert service.calls == [str(account.id)]
```

- [ ] **Step 2: 运行测试**

Run: `cd api && python -m pytest test/app/http/test_my_apps_routes.py -q --no-cov`
Expected: PASS

> 若报 `register_routes` 重复注册导致路由冲突，确认 `apps_routes.py` 的 `register_routes` 有幂等保护（与 `desktop_routes.py` 同款 `_registered` 标志）；若无，在测试中改用 `importlib.reload` 或复用 `asgi_app` 已注册的 app（不重复调用 `register_routes`）。

- [ ] **Step 3: 提交**

```bash
git add api/test/app/http/test_my_apps_routes.py
git commit -m "test(my-apps): cover GET /my/apps can_edit contract"
```

---

### Task 3: 前端修正 `listMyApps` 泛型

**Files:**
- Modify: `ui/src/services/my-apps.ts`
- Test: `ui/src/services/__tests__/my-apps.spec.ts`

- [ ] **Step 1: 读现有测试**

Run: `cat ui/src/services/__tests__/my-apps.spec.ts`
记录现有断言方式（它 mock 了 `@/utils/request`）。

- [ ] **Step 2: 写失败的测试**

在 `ui/src/services/__tests__/my-apps.spec.ts` 追加：

```ts
it('listMyApps returns the full response envelope', async () => {
  const { listMyApps } = await import('@/services/my-apps')
  const result = await listMyApps()
  // get<T> 运行时返回完整信封 { code, message, data }，而非 data 本身
  expect(result).toHaveProperty('data')
  expect(result.data).toHaveProperty('list')
})
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd ui && npx vitest run src/services/__tests__/my-apps.spec.ts`
Expected: FAIL（类型层面：`result.data` 在旧泛型下不存在，TS 报错或断言失败）

- [ ] **Step 4: 修正泛型**

修改 `ui/src/services/my-apps.ts` 第 4-6 行：

```ts
import { get, ssePost } from '@/utils/request'
import { type MyAppChatRequest, type MyAppListResponse } from '@/models/app-assignment'

export const listMyApps = () => {
  return get<MyAppListResponse>('/my/apps')
}
```

（`chatWithMyApp` 保持不变。）

- [ ] **Step 5: 运行测试确认通过**

Run: `cd ui && npx vitest run src/services/__tests__/my-apps.spec.ts`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add ui/src/services/my-apps.ts ui/src/services/__tests__/my-apps.spec.ts
git commit -m "fix(my-apps): align listMyApps generic with response envelope"
```

---

### Task 4: i18n 字典增删（zh-CN + en-US 同步）

**Files:**
- Modify: `ui/src/i18n/messages/zh-CN/myApps.ts`
- Modify: `ui/src/i18n/messages/en-US/myApps.ts`

- [ ] **Step 1: 确认 parity 测试当前通过（基线）**

Run: `cd ui && npx vitest run src/i18n/__tests__/parity.spec.ts`
Expected: PASS（3 passed）

- [ ] **Step 2: 同步修改两侧字典**

`ui/src/i18n/messages/zh-CN/myApps.ts` 改为：

```ts
export default  {
    title: '我的应用',
    description: '管理员分配给你的应用，以及你从应用商店添加的应用。',
    empty: '暂无应用，请从应用商店添加或联系管理员分配',
    loadFailed: '加载我的应用失败',
    sendFailed: '发送消息失败',
    sourceAssigned: '管理员分配',
    sourceForked: '商店添加',
    noDescription: '暂无描述',
    chatEmpty: '发送一条消息开始对话',
    inputPlaceholder: '输入消息，Enter 发送',
    send: '发送',
    sectionTitle: '全部应用',
    countSuffix: '共 {count} 个',
    enterChatHint: '点击进入对话',
    open: '打开',
    published: '已发布',
    footer: '© 2026 钰见我 · 用心对话，随心创作',
  }
```

（删除 `draft` 键。）

`ui/src/i18n/messages/en-US/myApps.ts` 改为：

```ts
export default  {
    title: 'My Apps',
    description: 'Apps assigned by admins and apps you added from the App Store.',
    empty: 'No apps yet. Add one from the App Store or ask an admin to assign one.',
    loadFailed: 'Failed to load my apps',
    sendFailed: 'Failed to send message',
    sourceAssigned: 'Assigned',
    sourceForked: 'From Store',
    noDescription: 'No description',
    chatEmpty: 'Send a message to start the conversation',
    inputPlaceholder: 'Type a message, Enter to send',
    send: 'Send',
    sectionTitle: 'All apps',
    countSuffix: '{count} total',
    enterChatHint: 'Click to open chat',
    open: 'Open',
    published: 'Published',
    footer: '© 2026 钰见我 · Talk with heart, create at will',
  }
```

（删除 `draft` 键。）

- [ ] **Step 3: 运行 parity 测试**

Run: `cd ui && npx vitest run src/i18n/__tests__/parity.spec.ts`
Expected: PASS（两侧键集合一致）

- [ ] **Step 4: 提交**

```bash
git add ui/src/i18n/messages/zh-CN/myApps.ts ui/src/i18n/messages/en-US/myApps.ts
git commit -m "feat(my-apps): add list-view i18n keys and drop unused draft key"
```

---

### Task 5: `ListView.vue` 接线真实接口 + 清理死代码

**Files:**
- Modify: `ui/src/views/space/my-apps/ListView.vue`

- [ ] **Step 1: 改造 script 部分**

修改 `ui/src/views/space/my-apps/ListView.vue` 的文件头注释与 script：

文件头注释改为：

```vue
<script setup lang="ts">
/**
 * 我的应用 — 视觉对齐画布原型 my-apps.html。
 *
 * 数据来源：真实接口 listMyApps（管理员分配 + 商店添加）。
 * - 列表视图：粉调大圆角应用卡片网格 + 搜索过滤，点击「打开」进入内嵌对话
 * - 对话视图：真实流式聊天（chatWithMyApp），外观对齐原型胶囊气泡
 * - 来源徽标：分叉（商店添加）/ 分配（管理员分配）
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { listMyApps, chatWithMyApp } from '@/services/my-apps'
import type { MyApp } from '@/models/app-assignment'
import { getErrorMessage } from '@/utils/error'
import {
  applyChatStreamEvent,
  type RenderableStreamMessage,
  type StreamState,
} from '@/views/shared/chat-stream'
import { withChatRenderId } from '@/views/shared/chat-stream'

const { t } = useI18n()
```

- [ ] **Step 2: 删除 mock 与 `MockApp`，改 `loadApps` 与图标降级**

删除 `mockApps`（原 L41-54）、`MockApp` 类型、`accentOf`（原 L57）与 `firstChar` 保留；替换为：

```ts
/** 无图标时用应用名首字 + 主题色渐变渲染 */
const accentOf = () => 'linear-gradient(135deg, var(--aicss-accent), var(--aicss-accent-text))'

/** 无图标时取应用名首字展示 */
const firstChar = (name: string) => (name || '?').trim().charAt(0).toUpperCase()

const loadApps = async () => {
  loading.value = true
  try {
    const res = await listMyApps()
    apps.value = res.data?.list || []
  } catch (error: unknown) {
    apps.value = []
    Message.error(getErrorMessage(error, t('myApps.loadFailed')))
  } finally {
    loading.value = false
  }
}
```

- [ ] **Step 3: 删除草稿徽标逻辑**

删除 `isDraft`（原 L88-89）定义。模板中状态徽标区块（原 L263-279）替换为仅「已发布」：

```vue
            <!-- 状态徽标 -->
            <div class="mt-4">
              <span
                class="my-badge-published inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium"
              >
                <span class="h-1.5 w-1.5 rounded-full bg-current"></span>
                {{ t('myApps.published') }}
              </span>
            </div>
```

同时删除样式块中的 `.my-badge-draft`（原 L462-465）。

- [ ] **Step 4: 模板硬编码文案 i18n 化**

替换以下位置（保持结构不变，仅换文案）：

- 第 189 行 `<h2 ...>全部应用</h2>` → `{{ t('myApps.sectionTitle') }}`
- 第 190 行 `共 {{ filteredApps.length }} 个` → `{{ t('myApps.countSuffix', { count: filteredApps.length }) }}`
- 第 286 行 `点击进入对话` → `{{ t('myApps.enterChatHint') }}`
- 第 290 行 `打开<icon-right .../>` → `{{ t('myApps.open') }}<icon-right .../>`
- 第 299 行 `© 2026 钰见我 · 用心对话，随心创作` → `{{ t('myApps.footer') }}`

`accentOf` 调用点（原 L238、L318、L358）改为 `accentOf()`（无参）。`--aicss-accent-text` 在深色主题下可能对比不足，若视觉验收发现文字不可读，改用 `var(--aicss-accent)` + `color: #fff`（实施时以实际渲染为准）。

- [ ] **Step 5: 类型检查**

Run: `cd ui && npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | grep -E "my-apps" | head -20`
Expected: 无 `my-apps` 相关新错误（仓库存在既有的其他文件类型错误，属基线，不在本任务范围）

- [ ] **Step 6: 提交**

```bash
git add ui/src/views/space/my-apps/ListView.vue
git commit -m "feat(my-apps): load real apps from API and remove mock data"
```

---

### Task 6: `ListView.vue` 组件测试

**Files:**
- Test: `ui/src/views/space/my-apps/__tests__/ListView.spec.ts`

- [ ] **Step 1: 写组件测试**

新建 `ui/src/views/space/my-apps/__tests__/ListView.spec.ts`：

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const listMyAppsMock = vi.fn()

vi.mock('@/services/my-apps', () => ({
  listMyApps: (...args: unknown[]) => listMyAppsMock(...args),
  chatWithMyApp: vi.fn(),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string, params?: Record<string, unknown>) =>
    params ? `${key}:${JSON.stringify(params)}` : key }),
}))

import ListView from '@/views/space/my-apps/ListView.vue'

const globalStubs = {
  'icon-search': true,
  'icon-apps': true,
  'icon-branch': true,
  'icon-user': true,
  'icon-right': true,
  'icon-left': true,
  'icon-message': true,
  'icon-send': true,
  'a-textarea': true,
}

describe('my-apps ListView', () => {
  beforeEach(() => {
    listMyAppsMock.mockReset()
  })

  it('renders apps returned by the real API', async () => {
    listMyAppsMock.mockResolvedValue({
      code: 'success',
      message: '',
      data: { list: [
        { id: 'app-1', name: '智能写作助手', description: 'desc', source: 'forked', status: 'published', assignment_id: '', assigned_at: null },
      ] },
    })
    const wrapper = mount(ListView, { global: { stubs: globalStubs } })
    await flushPromises()
    expect(wrapper.text()).toContain('智能写作助手')
  })

  it('shows empty state when API returns no apps', async () => {
    listMyAppsMock.mockResolvedValue({ code: 'success', message: '', data: { list: [] } })
    const wrapper = mount(ListView, { global: { stubs: globalStubs } })
    await flushPromises()
    expect(wrapper.text()).toContain('myApps.empty')
  })
})
```

- [ ] **Step 2: 运行测试**

Run: `cd ui && npx vitest run src/views/space/my-apps/__tests__/ListView.spec.ts`
Expected: PASS（2 passed）

> 若 Arco `Message` 在测试环境报错，补 `vi.mock('@arco-design/web-vue', () => ({ Message: { error: vi.fn(), success: vi.fn() } }))`。

- [ ] **Step 3: 提交**

```bash
git add ui/src/views/space/my-apps/__tests__/ListView.spec.ts
git commit -m "test(my-apps): cover ListView real-data rendering"
```

---

### Task 7: 全量回归 + 文档同步 + graphify

**Files:**
- Modify: `docs/prd/product-vision.md`

- [ ] **Step 1: 前端全量测试**

Run: `cd ui && npx vitest run`
Expected: 全部 PASS（含新增 ListView 测试与 parity）

- [ ] **Step 2: 后端相关测试**

Run: `cd api && python -m pytest test/internal/service/test_my_app_service.py test/app/http/test_my_apps_routes.py -q --no-cov`
Expected: PASS

- [ ] **Step 3: 更新产品文档状态**

修改 `docs/prd/product-vision.md`：
- §三 表格第 12 行「我的应用列表」：`🎭 **壳子**` → `✅ 真可用`，说明改为「ListView 已接真实接口 `GET /my/apps`（分配 + 商店添加双来源）」
- §4.4 中删除 my-apps 那一条（仅保留外部数据源的条目）
- §5.3 优先级列表中 my-apps 项标注完成

- [ ] **Step 4: 更新知识图谱**

Run: `cd d:/DEMO/openagent-main && python -m graphify update .`
Expected: 输出 `Code graph updated.`

- [ ] **Step 5: 提交**

```bash
git add docs/prd/product-vision.md graphify-out/
git commit -m "docs: mark my-apps list as real-data enabled"
```

---

## 完成标准

- [ ] `GET /my/apps` 响应含 `can_edit`
- [ ] 「我的应用」展示真实数据，无 `mockApps` 残留
- [ ] 无 `draft` 徽标与 `myApps.draft` 键
- [ ] 页面无硬编码展示文案；i18n parity 通过
- [ ] 前端 `npx vitest run` 与后端相关测试全绿
- [ ] `product-vision.md` 状态已更新；graphify 已刷新
