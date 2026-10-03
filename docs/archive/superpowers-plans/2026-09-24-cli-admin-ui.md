# CLI 工具来源 admin 管理页 — 实现计划

> **已归档（2026-10-03）**：Task 1~6 已落地（i18n 双语镜像 + `admin-cli.ts` service + `CreateOrUpdateCliModal.vue` + `AdminCliView.vue` + 路由/菜单接线 + 文档同步），`AdminCliView.spec.ts` / `CreateOrUpdateCliModal.spec.ts` 共 12 例与 i18n parity 全绿、类型检查无命中。当前说明见 [01-agent-tool-pool.md](../../prd/modules/01-agent-tool-pool.md) 与 [CLI 管理页设计规格](../superpowers-specs/2026-09-24-cli-admin-ui-design.md)；本文档仅保留实施过程，**不代表当前实现**。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理员经「资源编排 → CLI 管理」界面完成 CLI 注册/编辑/启停/删除，能力说明书表格化编辑，env 安全不回显。

**Architecture:** 纯前端增量——service（薄 HTTP 封装）+ 列表页 + 创建/编辑弹窗 + i18n 双语镜像 + 路由/菜单接线；后端 `/admin/cli` 五端点已就绪（`CliService`，`cli:*` RBAC + 审计），本计划零后端改动。

**Tech Stack:** Vue 3 / TypeScript / Arco Design / vue-i18n / vitest + @vue/test-utils。

**规格:** `docs/superpowers/specs/2026-09-24-cli-admin-ui-design.md`（已获批；Task 6 含一处按实际代码的措辞修正）

**执行约定（覆盖本计划的 Commit 步骤）:** 本仓库当前**未获提交授权**——所有标注 Commit 的步骤统一**跳过**（改动留在工作树），待用户明确指示后统一提交。

**测试注意:** 仓库 HEAD 存在既有 vue-tsc 类型错误——类型检查用「输出过滤本计划文件名」判定，不要求全仓零错误。

---

### Task 1: i18n 字典（zh/en 镜像）+ 目录注册 + 菜单键

**Files:**
- Create: `ui/src/i18n/messages/zh-CN/admin/adminCli.ts`
- Create: `ui/src/i18n/messages/en-US/admin/adminCli.ts`
- Modify: `ui/src/i18n/messages/{zh-CN,en-US}/admin/index.ts`
- Modify: `ui/src/i18n/messages/{zh-CN,en-US}/admin/adminLayout.ts`

- [ ] **Step 1: 创建 zh 字典 `ui/src/i18n/messages/zh-CN/admin/adminCli.ts`**

```ts
export default {
  title: 'CLI 管理',
  description:
    '注册本地 CLI 作为工具来源（source_type=cli）：能力说明书展开为工具池候选，Agent 经语义与关键词命中选用。',
  register: '注册 CLI',
  searchPlaceholder: '搜索名称或命令',
  categoryAll: '全部分类',
  loadFailed: '加载 CLI 列表失败',
  total: '共 {count} 个 CLI',
  empty: '暂无 CLI，点击「注册 CLI」添加第一个',
  edit: '编辑',
  remove: '删除',
  deleteConfirmTitle: '删除 CLI',
  deleteConfirmContent: '删除「{name}」后其工具将从工具池移除，确定删除？',
  deleted: '已删除',
  deleteFailed: '删除失败',
  statusFailed: '状态更新失败',
  columns: {
    tools: '工具数',
  },
  modal: {
    createTitle: '注册 CLI',
    editTitle: '编辑 CLI：{name}',
    basicSection: '基础信息',
    commandSection: '命令',
    schemaSection: '能力说明书',
    keywordSection: '任务关键词',
    envSection: '环境变量',
    name: 'CLI 名称',
    namePlaceholder: '唯一标识，如 ffmpeg',
    label: '显示名称',
    labelPlaceholder: '如 视频处理 CLI',
    descriptionLabel: '描述',
    descriptionPlaceholder: '该 CLI 能帮 Agent 做什么',
    category: '分类',
    categoryPlaceholder: '如 media（自由文本，默认 other）',
    command: '执行命令',
    commandPlaceholder: '如 python / ffmpeg',
    args: '固定参数',
    argsHint: '每行一个参数，追加在执行命令之后（如 -m my_tool）',
    addArg: '添加参数',
    timeout: '超时（秒）',
    enabled: '启用',
    toolId: '工具 ID',
    toolIdPlaceholder: '如 caption_video',
    toolDesc: '工具描述',
    toolDescPlaceholder: 'Agent 据此判断何时选用（语义命中依据）',
    toolParams: '参数 JSON',
    toolParamsPlaceholder: '{}',
    addTool: '添加工具',
    keyword: '关键词',
    keywordPlaceholder: '如 字幕 / subtitle',
    addKeyword: '添加关键词',
    envKey: '变量名',
    envValue: '值',
    addEnv: '添加变量',
    clearEnv: '提交时清空全部环境变量',
    envHint: '值加密存储、不回显；重新输入即整体覆盖，未编辑则保持原值。',
    jsonMode: '编辑为 JSON',
    jsonBackToTable: '返回表格编辑',
    save: '保存',
    cancel: '取消',
    createSuccess: '注册成功',
    updateSuccess: '保存成功',
    saveFailed: '保存失败',
    nameRequired: 'CLI 名称不能为空',
    commandRequired: 'CLI 命令不能为空',
    schemaRequired: '请至少声明一个工具及其描述',
    toolIdRequired: '工具 ID 不能为空',
    toolDescRequired: '工具描述不能为空',
    toolIdDuplicate: '工具 ID 重复：{id}',
    paramsInvalid: '参数 JSON 格式不合法',
    jsonInvalid: '能力说明书 JSON 不合法（需为非空对象）',
  },
}
```

- [ ] **Step 2: 创建 en 镜像 `ui/src/i18n/messages/en-US/admin/adminCli.ts`（键结构完全一致）**

```ts
export default {
  title: 'CLI Management',
  description:
    'Register local CLIs as tool sources (source_type=cli): capability specs expand into tool-pool candidates that agents select via semantic and keyword matching.',
  register: 'Register CLI',
  searchPlaceholder: 'Search by name or command',
  categoryAll: 'All categories',
  loadFailed: 'Failed to load CLI list',
  total: '{count} CLIs',
  empty: 'No CLIs yet. Click "Register CLI" to add the first one',
  edit: 'Edit',
  remove: 'Delete',
  deleteConfirmTitle: 'Delete CLI',
  deleteConfirmContent: 'Deleting "{name}" will remove its tools from the tool pool. Continue?',
  deleted: 'Deleted',
  deleteFailed: 'Delete failed',
  statusFailed: 'Failed to update status',
  columns: {
    tools: 'Tools',
  },
  modal: {
    createTitle: 'Register CLI',
    editTitle: 'Edit CLI: {name}',
    basicSection: 'Basic Info',
    commandSection: 'Command',
    schemaSection: 'Capability Spec',
    keywordSection: 'Task Keywords',
    envSection: 'Environment Variables',
    name: 'CLI Name',
    namePlaceholder: 'Unique identifier, e.g. ffmpeg',
    label: 'Display Name',
    labelPlaceholder: 'e.g. Video Processing CLI',
    descriptionLabel: 'Description',
    descriptionPlaceholder: 'What this CLI can do for agents',
    category: 'Category',
    categoryPlaceholder: 'e.g. media (free text, defaults to other)',
    command: 'Exec Command',
    commandPlaceholder: 'e.g. python / ffmpeg',
    args: 'Fixed Args',
    argsHint: 'One arg per line, appended after the command (e.g. -m my_tool)',
    addArg: 'Add Arg',
    timeout: 'Timeout (seconds)',
    enabled: 'Enabled',
    toolId: 'Tool ID',
    toolIdPlaceholder: 'e.g. caption_video',
    toolDesc: 'Tool Description',
    toolDescPlaceholder: 'How agents decide when to use it (semantic matching basis)',
    toolParams: 'Params JSON',
    toolParamsPlaceholder: '{}',
    addTool: 'Add Tool',
    keyword: 'Keyword',
    keywordPlaceholder: 'e.g. subtitle',
    addKeyword: 'Add Keyword',
    envKey: 'Name',
    envValue: 'Value',
    addEnv: 'Add Variable',
    clearEnv: 'Clear all env vars on submit',
    envHint: 'Values are encrypted and never echoed back; re-entering overwrites the whole set, untouched values stay unchanged.',
    jsonMode: 'Edit as JSON',
    jsonBackToTable: 'Back to table',
    save: 'Save',
    cancel: 'Cancel',
    createSuccess: 'Registered',
    updateSuccess: 'Saved',
    saveFailed: 'Save failed',
    nameRequired: 'CLI name is required',
    commandRequired: 'CLI command is required',
    schemaRequired: 'Declare at least one tool with its description',
    toolIdRequired: 'Tool ID is required',
    toolDescRequired: 'Tool description is required',
    toolIdDuplicate: 'Duplicate tool ID: {id}',
    paramsInvalid: 'Params JSON is invalid',
    jsonInvalid: 'Capability spec JSON is invalid (must be a non-empty object)',
  },
}
```

- [ ] **Step 3: 两侧 `admin/index.ts` 注册（import 区 + export 区各加一行，放在 `mcpAdmin` 相邻处）**

zh 与 en 两个文件同改：

```ts
import adminCli from './adminCli'
```

```ts
  adminCli,
```

- [ ] **Step 4: 两侧 `adminLayout.ts` 加菜单键（`mcp:` 行之后）**

zh：

```ts
        cli: 'CLI管理',
```

en：

```ts
        cli: 'CLI Management',
```

- [ ] **Step 5: 跑 parity 测试**

Run（cwd=`ui`）: `npx vitest run src/i18n/__tests__/parity.spec.ts`
Expected: PASS（此时无新 t() 引用，仅校验 zh/en 键集镜像）

- [ ] **Step 6: Commit（跳过，待用户授权）**

---

### Task 2: service — `admin-cli.ts`

**Files:**
- Create: `ui/src/services/admin-cli.ts`

- [ ] **Step 1: 创建文件（类型即 §2 契约的忠实映射；写法对照 `admin-global-control-config.ts`）**

```ts
import { get, post, put, del } from '@/utils/request'
import type { BaseResponse } from '@/models/base'

/** 能力说明书单条：{ 工具ID: { description, parameters } } */
export interface CliToolSpec {
  description?: string
  parameters?: Record<string, unknown>
}

export interface CliProvider {
  id: string
  name: string
  label: string
  description: string
  category: string
  command: string
  args: string[]
  tool_schema: Record<string, CliToolSpec>
  task_keywords: string[]
  timeout_seconds: number
  enabled: boolean
  is_public: boolean
  tool_count: number
}

/** POST/PUT 请求体；PUT 仅处理传入字段（env 未传即保持原值） */
export interface CliProviderPayload {
  name?: string
  label?: string
  description?: string
  category?: string
  command?: string
  args?: string[]
  env?: Record<string, string>
  tool_schema?: Record<string, CliToolSpec>
  task_keywords?: string[]
  timeout_seconds?: number
  enabled?: boolean
}

export const listCliProviders = async (): Promise<CliProvider[]> => {
  const response = await get<BaseResponse<{ items: CliProvider[] }>>('/admin/cli')
  return response.data.items
}

export const createCliProvider = async (payload: CliProviderPayload): Promise<string> => {
  const response = await post<BaseResponse<{ id: string }>>('/admin/cli', { body: payload })
  return response.data.id
}

export const updateCliProvider = async (id: string, payload: CliProviderPayload): Promise<void> => {
  await put<BaseResponse<unknown>>(`/admin/cli/${id}`, { body: payload })
}

export const deleteCliProvider = async (id: string): Promise<void> => {
  await del<BaseResponse<unknown>>(`/admin/cli/${id}`)
}
```

- [ ] **Step 2: 类型检查（过滤本计划文件，忽略仓库既有错误）**

Run（cwd=`ui`）: `npx vue-tsc --noEmit 2>&1 | Select-String -Pattern "admin-cli|AdminCliView|CreateOrUpdateCliModal"`
Expected: 无命中（有命中即修）

- [ ] **Step 3: Commit（跳过，待用户授权）**

---

### Task 3: 创建/编辑弹窗 — 先写失败测试再实现

**Files:**
- Test: `ui/src/views/admin/__tests__/CreateOrUpdateCliModal.spec.ts`（新建）
- Create: `ui/src/views/admin/cli/CreateOrUpdateCliModal.vue`

- [ ] **Step 1: 写失败测试**

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CreateOrUpdateCliModal from '@/views/admin/cli/CreateOrUpdateCliModal.vue'
import type { CliProvider } from '@/services/admin-cli'

const mocks = vi.hoisted(() => ({
  createCliProvider: vi.fn(),
  updateCliProvider: vi.fn(),
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
}))

vi.mock('@/services/admin-cli', () => ({
  createCliProvider: mocks.createCliProvider,
  updateCliProvider: mocks.updateCliProvider,
}))

vi.mock('@arco-design/web-vue', async () => {
  const actual = await vi.importActual<typeof import('@arco-design/web-vue')>('@arco-design/web-vue')
  return {
    ...actual,
    Message: { error: mocks.messageError, success: mocks.messageSuccess, warning: vi.fn() },
  }
})

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

const inputStub = {
  props: ['modelValue', 'placeholder', 'disabled'],
  emits: ['update:modelValue'],
  template:
    '<input :value="modelValue" :placeholder="placeholder" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}
const textareaStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template:
    '<textarea :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}
const formItemStub = {
  props: ['label'],
  template: '<div class="form-item"><slot /></div>',
}
const modalStub = {
  props: ['visible', 'title', 'width', 'footer'],
  emits: ['cancel'],
  template: '<div class="modal-stub"><div class="modal-title">{{ title }}</div><slot /></div>',
}

const mountModal = (props: { visible: boolean; provider: CliProvider | null }) =>
  mount(CreateOrUpdateCliModal, {
    props,
    global: {
      stubs: {
        'a-modal': modalStub,
        'a-form': { template: '<form><slot /></form>' },
        'a-form-item': formItemStub,
        'a-input': inputStub,
        'a-textarea': textareaStub,
        'a-input-number': inputStub,
        'a-switch': {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template: '<button class="switch" @click="$emit(\'update:modelValue\', !modelValue)"></button>',
        },
        'a-checkbox': {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template:
            '<label class="checkbox"><input type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" /><slot /></label>',
        },
      },
    },
  })

const provider: CliProvider = {
  id: 'p-1',
  name: 'ffmpeg',
  label: '视频处理',
  description: '转码与字幕',
  category: 'media',
  command: 'ffmpeg',
  args: ['-version'],
  tool_schema: { probe: { description: '探测媒体信息', parameters: { path: { type: 'string' } } } },
  task_keywords: ['转码'],
  timeout_seconds: 60,
  enabled: true,
  is_public: false,
  tool_count: 1,
}

describe('CreateOrUpdateCliModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('create mode: empty form blocks save with nameRequired', async () => {
    const wrapper = mountModal({ visible: true, provider: null })
    await wrapper.get('.save-btn').trigger('click')

    expect(mocks.createCliProvider).not.toHaveBeenCalled()
    expect(mocks.messageError).toHaveBeenCalledWith('admin.adminCli.modal.nameRequired')
  })

  it('create mode: missing command blocks save with commandRequired', async () => {
    const wrapper = mountModal({ visible: true, provider: null })
    await wrapper.get('[data-test="name"]').setValue('ffmpeg')
    await wrapper.get('.save-btn').trigger('click')

    expect(mocks.createCliProvider).not.toHaveBeenCalled()
    expect(mocks.messageError).toHaveBeenCalledWith('admin.adminCli.modal.commandRequired')
  })

  it('create mode: name+command+tool row submits expanded tool_schema', async () => {
    const wrapper = mountModal({ visible: true, provider: null })
    await wrapper.get('[data-test="name"]').setValue('ffmpeg')
    await wrapper.get('[data-test="command"]').setValue('ffmpeg')
    await wrapper.get('.add-tool').trigger('click')
    await wrapper.get('[data-test="tool-id-0"]').setValue('probe')
    await wrapper.get('[data-test="tool-desc-0"]').setValue('探测媒体信息')
    await wrapper.get('.save-btn').trigger('click')
    await flushPromises()

    expect(mocks.createCliProvider).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'ffmpeg',
        command: 'ffmpeg',
        tool_schema: { probe: { description: '探测媒体信息', parameters: {} } },
      }),
    )
    expect(mocks.messageError).not.toHaveBeenCalled()
  })

  it('create mode: empty capability spec is rejected', async () => {
    const wrapper = mountModal({ visible: true, provider: null })
    await wrapper.get('[data-test="name"]').setValue('ffmpeg')
    await wrapper.get('[data-test="command"]').setValue('ffmpeg')
    await wrapper.get('.save-btn').trigger('click')

    expect(mocks.createCliProvider).not.toHaveBeenCalled()
    expect(mocks.messageError).toHaveBeenCalledWith('admin.adminCli.modal.schemaRequired')
  })

  it('edit mode: prefills provider and submits without name', async () => {
    const wrapper = mountModal({ visible: true, provider })
    await flushPromises()
    expect((wrapper.get('[data-test="command"]').element as HTMLInputElement).value).toBe('ffmpeg')

    mocks.updateCliProvider.mockResolvedValue(undefined)
    await wrapper.get('.save-btn').trigger('click')
    await flushPromises()

    expect(mocks.updateCliProvider).toHaveBeenCalledWith(
      'p-1',
      expect.objectContaining({ command: 'ffmpeg' }),
    )
    const payload = mocks.updateCliProvider.mock.calls[0][1]
    expect('name' in payload).toBe(false)
    expect(payload.tool_schema).toEqual(provider.tool_schema)
  })

  it('env untouched omits env key; clearEnv submits empty env', async () => {
    const wrapper = mountModal({ visible: true, provider })
    mocks.updateCliProvider.mockResolvedValue(undefined)
    await wrapper.get('.save-btn').trigger('click')
    await flushPromises()
    expect('env' in mocks.updateCliProvider.mock.calls[0][1]).toBe(false)

    await wrapper.get('[data-test="clear-env"]').setValue(true)
    await wrapper.get('.save-btn').trigger('click')
    await flushPromises()
    expect(mocks.updateCliProvider.mock.calls[1][1].env).toEqual({})
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run（cwd=`ui`）: `npx vitest run src/views/admin/__tests__/CreateOrUpdateCliModal.spec.ts`
Expected: FAIL（模块不存在 / 导入错误）

- [ ] **Step 3: 实现 `ui/src/views/admin/cli/CreateOrUpdateCliModal.vue`**

```vue
<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import {
  createCliProvider,
  updateCliProvider,
  type CliProvider,
  type CliProviderPayload,
  type CliToolSpec,
} from '@/services/admin-cli'

const props = defineProps<{
  visible: boolean
  provider: CliProvider | null
}>()
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'saved'): void
}>()

const { t } = useI18n()

const form = reactive({
  name: '',
  label: '',
  description: '',
  category: '',
  command: '',
  timeout_seconds: 30,
  enabled: true,
})
const argRows = ref<string[]>([])
const keywordRows = ref<string[]>([])
const toolRows = ref<Array<{ id: string; description: string; parametersText: string }>>([])
const envRows = ref<Array<{ key: string; value: string }>>([])
const clearEnv = ref(false)
const envTouched = ref(false)
const jsonMode = ref(false)
const jsonText = ref('')
const saving = ref(false)

const isEdit = computed(() => Boolean(props.provider))

const fillFromProvider = (provider: CliProvider | null) => {
  form.name = provider?.name ?? ''
  form.label = provider?.label ?? ''
  form.description = provider?.description ?? ''
  form.category = provider?.category ?? ''
  form.command = provider?.command ?? ''
  form.timeout_seconds = provider?.timeout_seconds ?? 30
  form.enabled = provider?.enabled ?? true
  argRows.value = [...(provider?.args ?? [])]
  keywordRows.value = [...(provider?.task_keywords ?? [])]
  toolRows.value = Object.entries(provider?.tool_schema ?? {}).map(([id, spec]) => ({
    id,
    description: spec?.description ?? '',
    parametersText: spec?.parameters ? JSON.stringify(spec.parameters, null, 2) : '',
  }))
  // GET 不回显 env（加密安全约束）：编辑态 env 保持「未编辑不提交」
  envRows.value = []
  clearEnv.value = false
  envTouched.value = false
  jsonMode.value = false
  jsonText.value = ''
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) fillFromProvider(props.provider)
  },
  { immediate: true },
)

const addArg = () => argRows.value.push('')
const removeArg = (index: number) => argRows.value.splice(index, 1)
const addKeyword = () => keywordRows.value.push('')
const removeKeyword = (index: number) => keywordRows.value.splice(index, 1)
const addTool = () => toolRows.value.push({ id: '', description: '', parametersText: '' })
const removeTool = (index: number) => toolRows.value.splice(index, 1)
const addEnv = () => {
  envRows.value.push({ key: '', value: '' })
  envTouched.value = true
}
const removeEnv = (index: number) => {
  envRows.value.splice(index, 1)
  envTouched.value = true
}

const buildToolSchema = (): Record<string, CliToolSpec> | null => {
  if (!toolRows.value.length) {
    Message.error(t('admin.adminCli.modal.schemaRequired'))
    return null
  }
  const schema: Record<string, CliToolSpec> = {}
  for (const row of toolRows.value) {
    const id = row.id.trim()
    if (!id) {
      Message.error(t('admin.adminCli.modal.toolIdRequired'))
      return null
    }
    if (schema[id]) {
      Message.error(t('admin.adminCli.modal.toolIdDuplicate', { id }))
      return null
    }
    const description = row.description.trim()
    if (!description) {
      Message.error(t('admin.adminCli.modal.toolDescRequired'))
      return null
    }
    let parameters: Record<string, unknown> = {}
    const text = row.parametersText.trim()
    if (text) {
      try {
        const parsed = JSON.parse(text)
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
          throw new Error('not an object')
        }
        parameters = parsed as Record<string, unknown>
      } catch {
        Message.error(t('admin.adminCli.modal.paramsInvalid'))
        return null
      }
    }
    schema[id] = { description, parameters }
  }
  return schema
}

const toggleJsonMode = () => {
  if (!jsonMode.value) {
    const schema = buildToolSchema()
    if (!schema) return
    jsonText.value = JSON.stringify(schema, null, 2)
    jsonMode.value = true
    return
  }
  try {
    const parsed = JSON.parse(jsonText.value || '')
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed) || !Object.keys(parsed).length) {
      Message.error(t('admin.adminCli.modal.jsonInvalid'))
      return
    }
    toolRows.value = Object.entries(parsed as Record<string, CliToolSpec>).map(([id, spec]) => ({
      id,
      description: spec?.description ?? '',
      parametersText: spec?.parameters ? JSON.stringify(spec.parameters, null, 2) : '',
    }))
    jsonMode.value = false
  } catch {
    Message.error(t('admin.adminCli.modal.jsonInvalid'))
  }
}

const handleSave = async () => {
  if (!isEdit.value && !form.name.trim()) {
    Message.error(t('admin.adminCli.modal.nameRequired'))
    return
  }
  if (!form.command.trim()) {
    Message.error(t('admin.adminCli.modal.commandRequired'))
    return
  }

  let toolSchema: Record<string, CliToolSpec> | null = null
  if (jsonMode.value) {
    try {
      const parsed = JSON.parse(jsonText.value || '')
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed) || !Object.keys(parsed).length) {
        Message.error(t('admin.adminCli.modal.jsonInvalid'))
        return
      }
      toolSchema = parsed as Record<string, CliToolSpec>
    } catch {
      Message.error(t('admin.adminCli.modal.jsonInvalid'))
      return
    }
  } else {
    toolSchema = buildToolSchema()
    if (!toolSchema) return
  }

  const payload: CliProviderPayload = {
    label: form.label.trim(),
    description: form.description.trim(),
    category: form.category.trim() || 'other',
    command: form.command.trim(),
    args: argRows.value.map((item) => item.trim()).filter(Boolean),
    tool_schema: toolSchema,
    task_keywords: keywordRows.value.map((item) => item.trim()).filter(Boolean),
    timeout_seconds: Number(form.timeout_seconds) || 30,
    enabled: form.enabled,
  }
  if (!isEdit.value) payload.name = form.name.trim()

  // env：GET 不回显——仅在主动编辑（或勾选清空）时提交，未编辑不带 env 键（服务端保持原值）
  if (clearEnv.value) {
    payload.env = {}
  } else if (envTouched.value && envRows.value.length) {
    payload.env = Object.fromEntries(
      envRows.value
        .filter((row) => row.key.trim())
        .map((row) => [row.key.trim(), row.value]),
    )
  }

  saving.value = true
  try {
    if (props.provider) {
      await updateCliProvider(props.provider.id, payload)
      Message.success(t('admin.adminCli.modal.updateSuccess'))
    } else {
      await createCliProvider(payload)
      Message.success(t('admin.adminCli.modal.createSuccess'))
    }
    emit('update:visible', false)
    emit('saved')
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.adminCli.modal.saveFailed')))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <a-modal
    :visible="visible"
    :title="isEdit ? t('admin.adminCli.modal.editTitle', { name: provider?.name }) : t('admin.adminCli.modal.createTitle')"
    :width="720"
    :footer="false"
    @cancel="emit('update:visible', false)"
  >
    <a-form layout="vertical">
      <h4 class="section-title">{{ t('admin.adminCli.modal.basicSection') }}</h4>
      <div class="grid grid-cols-2 gap-3">
        <a-form-item :label="t('admin.adminCli.modal.name')">
          <a-input
            v-if="!isEdit"
            v-model="form.name"
            data-test="name"
            :placeholder="t('admin.adminCli.modal.namePlaceholder')"
            allow-clear
          />
          <a-input v-else :model-value="provider?.name" disabled />
        </a-form-item>
        <a-form-item :label="t('admin.adminCli.modal.label')">
          <a-input v-model="form.label" :placeholder="t('admin.adminCli.modal.labelPlaceholder')" allow-clear />
        </a-form-item>
        <a-form-item :label="t('admin.adminCli.modal.descriptionLabel')">
          <a-input v-model="form.description" :placeholder="t('admin.adminCli.modal.descriptionPlaceholder')" allow-clear />
        </a-form-item>
        <a-form-item :label="t('admin.adminCli.modal.category')">
          <a-input v-model="form.category" :placeholder="t('admin.adminCli.modal.categoryPlaceholder')" allow-clear />
        </a-form-item>
        <a-form-item :label="t('admin.adminCli.modal.timeout')">
          <a-input-number v-model="form.timeout_seconds" :min="1" :step="1" :precision="0" />
        </a-form-item>
        <a-form-item :label="t('admin.adminCli.modal.enabled')">
          <a-switch v-model="form.enabled" />
        </a-form-item>
      </div>

      <h4 class="section-title">{{ t('admin.adminCli.modal.commandSection') }}</h4>
      <a-form-item :label="t('admin.adminCli.modal.command')">
        <a-input v-model="form.command" data-test="command" :placeholder="t('admin.adminCli.modal.commandPlaceholder')" allow-clear />
      </a-form-item>
      <a-form-item :label="t('admin.adminCli.modal.args')">
        <div v-for="(_arg, index) in argRows" :key="index" class="row-line">
          <a-input v-model="argRows[index]" :placeholder="t('admin.adminCli.modal.toolParamsPlaceholder')" />
          <button type="button" class="danger-link" @click="removeArg(index)">−</button>
        </div>
        <button type="button" class="add-link" @click="addArg">+ {{ t('admin.adminCli.modal.addArg') }}</button>
        <p class="hint-text">{{ t('admin.adminCli.modal.argsHint') }}</p>
      </a-form-item>

      <h4 class="section-title">
        {{ t('admin.adminCli.modal.schemaSection') }}
        <button type="button" class="add-link" @click="toggleJsonMode">
          {{ jsonMode ? t('admin.adminCli.modal.jsonBackToTable') : t('admin.adminCli.modal.jsonMode') }}
        </button>
      </h4>
      <a-textarea
        v-if="jsonMode"
        v-model="jsonText"
        data-test="schema-json"
        :rows="10"
        :placeholder="t('admin.adminCli.modal.toolParamsPlaceholder')"
      />
      <template v-else>
        <div v-for="(row, index) in toolRows" :key="index" class="tool-row">
          <a-input
            v-model="row.id"
            :data-test="`tool-id-${index}`"
            :placeholder="t('admin.adminCli.modal.toolIdPlaceholder')"
          />
          <a-input
            v-model="row.description"
            :data-test="`tool-desc-${index}`"
            :placeholder="t('admin.adminCli.modal.toolDescPlaceholder')"
          />
          <a-textarea
            v-model="row.parametersText"
            :rows="2"
            :placeholder="t('admin.adminCli.modal.toolParamsPlaceholder')"
          />
          <button type="button" class="danger-link" @click="removeTool(index)">−</button>
        </div>
        <button type="button" class="add-link add-tool" @click="addTool">
          + {{ t('admin.adminCli.modal.addTool') }}
        </button>
      </template>

      <h4 class="section-title">{{ t('admin.adminCli.modal.keywordSection') }}</h4>
      <div v-for="(_keyword, index) in keywordRows" :key="index" class="row-line">
        <a-input v-model="keywordRows[index]" :placeholder="t('admin.adminCli.modal.keywordPlaceholder')" />
        <button type="button" class="danger-link" @click="removeKeyword(index)">−</button>
      </div>
      <button type="button" class="add-link" @click="addKeyword">
        + {{ t('admin.adminCli.modal.addKeyword') }}
      </button>

      <h4 class="section-title">{{ t('admin.adminCli.modal.envSection') }}</h4>
      <div v-for="(row, index) in envRows" :key="index" class="row-line">
        <a-input v-model="row.key" :placeholder="t('admin.adminCli.modal.envKey')" />
        <a-input v-model="row.value" :placeholder="t('admin.adminCli.modal.envValue')" />
        <button type="button" class="danger-link" @click="removeEnv(index)">−</button>
      </div>
      <button type="button" class="add-link" @click="addEnv">
        + {{ t('admin.adminCli.modal.addEnv') }}
      </button>
      <label class="checkbox-line">
        <input v-model="clearEnv" data-test="clear-env" type="checkbox" />
        {{ t('admin.adminCli.modal.clearEnv') }}
      </label>
      <p class="hint-text">{{ t('admin.adminCli.modal.envHint') }}</p>
    </a-form>

    <div class="footer-bar">
      <button type="button" class="cancel-btn" @click="emit('update:visible', false)">
        {{ t('admin.adminCli.modal.cancel') }}
      </button>
      <button type="button" class="save-btn" :disabled="saving" @click="handleSave">
        {{ t('admin.adminCli.modal.save') }}
      </button>
    </div>
  </a-modal>
</template>

<style scoped>
.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 14px;
  font-weight: 600;
  margin: 16px 0 8px;
}
.row-line,
.tool-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  margin-bottom: 6px;
}
.tool-row > :first-child {
  width: 180px;
  flex: none;
}
.add-link {
  color: #165dff;
  font-size: 13px;
}
.danger-link {
  color: #f53f3f;
  padding: 0 6px;
}
.hint-text {
  font-size: 12px;
  color: #86909c;
  margin-top: 4px;
}
.checkbox-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  margin-top: 8px;
}
.footer-bar {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
.save-btn {
  background: #165dff;
  color: #fff;
  padding: 6px 16px;
  border-radius: 4px;
}
.cancel-btn {
  padding: 6px 16px;
  border: 1px solid #e5e6eb;
  border-radius: 4px;
}
</style>
```

- [ ] **Step 4: 运行确认通过**

Run: `npx vitest run src/views/admin/__tests__/CreateOrUpdateCliModal.spec.ts`
Expected: 6 例全 PASS

- [ ] **Step 5: Commit（跳过，待用户授权）**

---

### Task 4: 列表页 `AdminCliView` — 先写失败测试再实现

**Files:**
- Test: `ui/src/views/admin/__tests__/AdminCliView.spec.ts`（新建）
- Create: `ui/src/views/admin/AdminCliView.vue`

- [ ] **Step 1: 写失败测试**

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminCliView from '@/views/admin/AdminCliView.vue'
import type { CliProvider } from '@/services/admin-cli'

const mocks = vi.hoisted(() => ({
  listCliProviders: vi.fn(),
  updateCliProvider: vi.fn(),
  deleteCliProvider: vi.fn(),
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
  modalConfirm: vi.fn(),
}))

vi.mock('@/services/admin-cli', () => ({
  listCliProviders: mocks.listCliProviders,
  updateCliProvider: mocks.updateCliProvider,
  deleteCliProvider: mocks.deleteCliProvider,
  createCliProvider: vi.fn(),
}))

vi.mock('@arco-design/web-vue', async () => {
  const actual = await vi.importActual<typeof import('@arco-design/web-vue')>('@arco-design/web-vue')
  return {
    ...actual,
    Message: { error: mocks.messageError, success: mocks.messageSuccess, warning: vi.fn() },
    Modal: { confirm: mocks.modalConfirm },
  }
})

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string, params?: { count?: number; name?: string }) =>
    params?.count !== undefined ? `${key}:${params.count}` : params?.name ? `${key}:${params.name}` : key }),
}))

vi.mock('@/stores/admin', () => ({
  useAdminStore: () => ({ hasPermission: () => true }),
}))

vi.mock('@/views/admin/cli/CreateOrUpdateCliModal.vue', () => ({
  default: {
    name: 'CreateOrUpdateCliModal',
    props: ['visible', 'provider'],
    emits: ['update:visible', 'saved'],
    template: '<div class="cli-modal-stub" />',
  },
}))

const switchStub = {
  props: ['modelValue'],
  emits: ['change'],
  template: '<button class="switch" @click="$emit(\'change\', !modelValue)"></button>',
}

const inputStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template:
    '<input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const provider = (overrides: Partial<CliProvider> = {}): CliProvider => ({
  id: 'p-1',
  name: 'ffmpeg',
  label: '视频处理',
  description: '转码字幕',
  category: 'media',
  command: 'ffmpeg',
  args: ['-version'],
  tool_schema: { probe: { description: '探测' } },
  task_keywords: ['转码'],
  timeout_seconds: 30,
  enabled: true,
  is_public: false,
  tool_count: 1,
  ...overrides,
})

const mountView = () =>
  mount(AdminCliView, {
    global: {
      stubs: {
        'a-input': inputStub,
        'a-switch': switchStub,
        'a-select': {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template:
            '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>',
        },
        'a-option': {
          props: ['value'],
          template: '<option :value="value"><slot /></option>',
        },
      },
    },
  })

describe('AdminCliView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads providers on mount and renders rows', async () => {
    mocks.listCliProviders.mockResolvedValue([provider()])
    const wrapper = mountView()
    await flushPromises()

    expect(mocks.listCliProviders).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('ffmpeg')
    expect(wrapper.text()).toContain('admin.adminCli.columns.tools')
    expect(wrapper.text()).toContain(': 1')
  })

  it('filters rows by search keyword', async () => {
    mocks.listCliProviders.mockResolvedValue([
      provider(),
      provider({ id: 'p-2', name: 'git', command: 'git', label: '版本控制' }),
    ])
    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('[data-test="search"]').setValue('git')
    expect(wrapper.text()).not.toContain('ffmpeg')
    expect(wrapper.text()).toContain('git')
  })

  it('toggles enabled via switch and calls updateCliProvider', async () => {
    mocks.listCliProviders.mockResolvedValue([provider({ enabled: true })])
    mocks.updateCliProvider.mockResolvedValue(undefined)
    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('.switch').trigger('click')
    await flushPromises()

    expect(mocks.updateCliProvider).toHaveBeenCalledWith('p-1', { enabled: false })
  })

  it('filters rows by category select', async () => {
    mocks.listCliProviders.mockResolvedValue([
      provider(),
      provider({ id: 'p-2', name: 'git', command: 'git', label: '版本控制', category: 'dev' }),
    ])
    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('select').setValue('dev')
    expect(wrapper.text()).toContain('git')
    expect(wrapper.text()).not.toContain('ffmpeg')
  })

  it('deletes after Modal.confirm onOk', async () => {
    mocks.listCliProviders
      .mockResolvedValueOnce([provider()])
      .mockResolvedValue([])
    mocks.deleteCliProvider.mockResolvedValue(undefined)
    const wrapper = mountView()
    await flushPromises()

    await wrapper.get('.delete-btn').trigger('click')
    expect(mocks.modalConfirm).toHaveBeenCalledTimes(1)
    await mocks.modalConfirm.mock.calls[0][0].onOk()
    await flushPromises()

    expect(mocks.deleteCliProvider).toHaveBeenCalledWith('p-1')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('admin.adminCli.deleted')
  })

  it('shows empty state when no providers', async () => {
    mocks.listCliProviders.mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('admin.adminCli.empty')
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/views/admin/__tests__/AdminCliView.spec.ts`
Expected: FAIL（`@/views/admin/AdminCliView.vue` 不存在）

- [ ] **Step 3: 实现 `ui/src/views/admin/AdminCliView.vue`**

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import { useAdminStore } from '@/stores/admin'
import {
  listCliProviders,
  updateCliProvider,
  deleteCliProvider,
  type CliProvider,
} from '@/services/admin-cli'
import CreateOrUpdateCliModal from '@/views/admin/cli/CreateOrUpdateCliModal.vue'

const { t } = useI18n()
const adminStore = useAdminStore()

const loading = ref(false)
const items = ref<CliProvider[]>([])
const keyword = ref('')
const categoryFilter = ref('')
const modalVisible = ref(false)
const editing = ref<CliProvider | null>(null)

const canCreate = computed(() => adminStore.hasPermission('cli:create'))
const canUpdate = computed(() => adminStore.hasPermission('cli:update'))
const canDelete = computed(() => adminStore.hasPermission('cli:delete'))

const categories = computed(() => {
  const set = new Set(items.value.map((item) => item.category).filter(Boolean))
  return [...set].sort()
})

const filtered = computed(() => {
  let list = items.value
  if (categoryFilter.value) {
    list = list.filter((item) => item.category === categoryFilter.value)
  }
  const query = keyword.value.trim().toLowerCase()
  if (!query) return list
  return list.filter((item) =>
    [item.name, item.label, item.command].some((field) =>
      String(field || '').toLowerCase().includes(query),
    ),
  )
})

const loadData = async () => {
  loading.value = true
  try {
    items.value = await listCliProviders()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.adminCli.loadFailed')))
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editing.value = null
  modalVisible.value = true
}

const openEdit = (item: CliProvider) => {
  editing.value = item
  modalVisible.value = true
}

const toggleEnabled = async (item: CliProvider, value: boolean) => {
  try {
    await updateCliProvider(item.id, { enabled: value })
  } catch (error) {
    item.enabled = !value
    Message.error(getErrorMessage(error, t('admin.adminCli.statusFailed')))
  }
}

const confirmDelete = (item: CliProvider) => {
  Modal.confirm({
    title: t('admin.adminCli.deleteConfirmTitle'),
    content: t('admin.adminCli.deleteConfirmContent', { name: item.name }),
    onOk: async () => {
      try {
        await deleteCliProvider(item.id)
        Message.success(t('admin.adminCli.deleted'))
        await loadData()
      } catch (error) {
        Message.error(getErrorMessage(error, t('admin.adminCli.deleteFailed')))
      }
    },
  })
}

onMounted(loadData)
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-4">
      <div>
        <h1 class="text-2xl font-bold">{{ t('admin.adminCli.title') }}</h1>
        <p class="text-gray-600 text-sm mt-1">{{ t('admin.adminCli.description') }}</p>
      </div>
      <button
        v-if="canCreate"
        class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm"
        @click="openCreate"
      >
        {{ t('admin.adminCli.register') }}
      </button>
    </div>

    <div class="flex items-center gap-3 mb-4">
      <a-select v-model="categoryFilter" class="w-40">
        <a-option value="">{{ t('admin.adminCli.categoryAll') }}</a-option>
        <a-option v-for="c in categories" :key="c" :value="c">{{ c }}</a-option>
      </a-select>
      <a-input
        v-model="keyword"
        data-test="search"
        class="w-64"
        :placeholder="t('admin.adminCli.searchPlaceholder')"
        allow-clear
      />
    </div>

    <div v-if="loading" class="text-center py-8 text-gray-500">{{ t('common.loading') }}</div>

    <div v-else-if="!filtered.length" class="text-center py-8 text-gray-500">
      {{ t('admin.adminCli.empty') }}
    </div>

    <template v-else>
      <p class="text-gray-500 text-sm mb-2">
        {{ t('admin.adminCli.total', { count: filtered.length }) }}
      </p>
      <div class="space-y-3">
        <div
          v-for="item in filtered"
          :key="item.id"
          class="border rounded-lg p-4 hover:shadow-sm transition-shadow flex items-center justify-between gap-4"
        >
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="font-medium">{{ item.label || item.name }}</span>
              <span class="text-xs text-gray-400">{{ item.name }}</span>
              <span class="text-xs px-2 py-0.5 rounded bg-gray-100">{{ item.category }}</span>
              <span class="text-xs px-2 py-0.5 rounded bg-blue-50 text-blue-600">
                {{ t('admin.adminCli.columns.tools') }}: {{ item.tool_count }}
              </span>
            </div>
            <div class="text-sm text-gray-600 mt-1 font-mono truncate">
              {{ item.command }} {{ (item.args || []).join(' ') }}
            </div>
            <div v-if="(item.task_keywords || []).length" class="flex flex-wrap gap-1 mt-1">
              <span
                v-for="k in item.task_keywords"
                :key="k"
                class="text-xs px-1.5 py-0.5 rounded bg-gray-50 border border-gray-200"
              >
                {{ k }}
              </span>
            </div>
          </div>
          <div class="flex items-center gap-3 flex-none">
            <a-switch
              v-if="canUpdate"
              :model-value="item.enabled"
              @change="(value: unknown) => toggleEnabled(item, Boolean(value))"
            />
            <button v-if="canUpdate" class="text-sm text-blue-600" @click="openEdit(item)">
              {{ t('admin.adminCli.edit') }}
            </button>
            <button
              v-if="canDelete"
              class="text-sm text-red-600 delete-btn"
              @click="confirmDelete(item)"
            >
              {{ t('admin.adminCli.remove') }}
            </button>
          </div>
        </div>
      </div>
    </template>

    <CreateOrUpdateCliModal
      v-model:visible="modalVisible"
      :provider="editing"
      @saved="loadData"
    />
  </div>
</template>
```

- [ ] **Step 4: 运行确认通过**

Run: `npx vitest run src/views/admin/__tests__/AdminCliView.spec.ts`
Expected: 6 例全 PASS

- [ ] **Step 5: Commit（跳过，待用户授权）**

---

### Task 5: 路由 + 菜单接线（接线审查：入口必须可达）

**Files:**
- Modify: `ui/src/router/index.ts`（`mcp` 路由块之后）
- Modify: `ui/src/layouts/AdminLayout.vue`（`/admin/mcp` 菜单项之后）

- [ ] **Step 1: 注册路由（第 190-195 行 `mcp` 块之后插入）**

```ts
            {
              path: 'cli',
              name: 'admin-cli',
              component: () => import('@/views/admin/AdminCliView.vue'),
              meta: { adminRequired: true, requiresAuth: true, realm: 'admin', permissions: ['cli:read'] },
            },
```

- [ ] **Step 2: 注册菜单（第 87 行 `/admin/mcp` 项之后插入，资源编排组内紧邻 MCP）**

```ts
      { to: '/admin/cli', label: t('admin.adminLayout.menu.cli'), permission: 'cli:read' },
```

- [ ] **Step 3: 权限链自检（不改代码，验证即可）**

Run（cwd=`api`）: `python -m pytest test/app/http -k "rbac" --no-cov -q`
Expected: 与改前基线一致（`cli:*` 四权限已在 `rbac.py PERMISSION_CATALOG` + operator 默认授权 + `support.py ("admin","cli")` 路径映射——本计划后端零改动，不应新增失败）

- [ ] **Step 4: 跑全量相关前端测试**

Run（cwd=`ui`）:

```
npx vitest run src/i18n/__tests__/parity.spec.ts src/views/admin/__tests__/AdminCliView.spec.ts src/views/admin/__tests__/CreateOrUpdateCliModal.spec.ts
```

Expected: 全 PASS（parity 断言 `admin.adminLayout.menu.cli` 与 `admin.adminCli.*` 两侧键集一致且被引用键均可解析）

- [ ] **Step 5: Commit（跳过，待用户授权）**

---

### Task 6: 文档同步 + 类型检查 + 知识图谱 + 收尾自检

- [ ] **Step 1: 修正规格措辞（MCP category 实为自由字符串，非枚举）**

Modify: `docs/superpowers/specs/2026-09-24-cli-admin-ui-design.md` §3.3 第 1 条——
把「category（下拉，对齐 MCP 分类枚举）」改为
「category（文本输入，自由字符串——已核实 `mcp.model` 的 category 为 `String(255)` 无枚举，CLI 对齐同为自由文本，默认 `other`）」。

- [ ] **Step 2: 架构文档同步（AGENTS.md 强制规则）**

Modify: `docs/prd/modules/01-agent-tool-pool.md`（`source_type=cli` 相关节）末尾追加：

```markdown
- 2026-09-24 admin UI 落地：`/admin/cli`（资源编排菜单「CLI 管理」，权限 `cli:read`）——
  列表/注册/编辑/启停/删除；能力说明书（`tool_schema`）表格化行编辑（工具 ID + 描述 +
  折叠参数 JSON，可切 JSON 模式）；env 加密不回显、未编辑不提交（PUT 仅处理传入字段）。
```

- [ ] **Step 3: 类型检查（过滤本计划文件）**

Run（cwd=`ui`）: `npx vue-tsc --noEmit 2>&1 | Select-String -Pattern "admin-cli|AdminCliView|CreateOrUpdateCliModal"`
Expected: 无命中

- [ ] **Step 4: 知识图谱同步**

Run: `python -m graphify update .`
Expected: 更新成功

- [ ] **Step 5: 收尾接线自检（写进回复）**

一行点明入口：「CLI 管理入口：系统菜单 资源编排 → CLI 管理（`/admin/cli`，`cli:read`）→ `admin-cli.ts` → `GET/POST/PUT/DELETE /admin/cli`；生效链路：注册 → `cli_tool` 展开 → 候选池 `_collect_cli_tools` → `ToolSelectorService` → `CliService.build_selected_tools` 执行。」
