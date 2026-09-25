<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Message, Modal } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  createAgent,
  deleteAgent,
  deleteSchedule,
  createSchedule,
  getBudgetUsage,
  listAgents,
  listAssignablePermissions,
  listBoards,
  listSchedules,
  updateAgent,
  type AdminAgent,
  type AssignablePermission,
  type AutomationLevel,
  type BoardAction,
  type BudgetUsage,
  type ScheduleTask,
} from '@/services/admin-agents'
import { getErrorMessage } from '@/utils/error'
import { useAdminStore } from '@/stores/admin'
import { getAgentAvatarStyle, getAgentAvatarText, formatAgentTime } from '@/utils/admin-agent-display'

const { t } = useI18n()
const router = useRouter()
const adminStore = useAdminStore()

const canManage = computed(() => adminStore.hasPermission('agent_pool:manage'))

const loading = ref(false)
const actionLoading = ref(false)
const agents = ref<AdminAgent[]>([])
const assignablePermissions = ref<AssignablePermission[]>([])
const boards = ref<string[]>([])
const boardActions = ref<BoardAction[]>([])

const formatTime = (value: number | null | undefined) => formatAgentTime(value)

// KPI：由已加载的 Agent 列表统计（列表接口一次返回全量 items，无分页）。
const kpi = computed(() => ({
  total: agents.value.length,
  enabled: agents.value.filter((item) => item.enabled).length,
  disabled: agents.value.filter((item) => !item.enabled).length,
}))

const automationLevelOptions = computed(() => [
  { label: t('admin.agents.levelSupervised'), value: 'supervised' },
  { label: t('admin.agents.levelAutonomous'), value: 'autonomous' },
  { label: t('admin.agents.levelBlocked'), value: 'blocked' },
])

// 权限明细索引：code → 语义对象，供表格展示中文名（与角色权限页同一份目录）。
const permissionByCode = computed(() => {
  const map: Record<string, AssignablePermission> = {}
  assignablePermissions.value.forEach((perm) => {
    map[perm.code] = perm
  })
  return map
})

// 语义化标签：优先取目录中的中文名；目录缺失时回退裸码（不伪造名称）。
const permissionLabel = (code: string) => permissionByCode.value[code]?.name || code

// 资源分组名复用 RBAC 角色页的同一套文案（admin.roles.resources.*），不另建字典。
const resourceLabel = (resource: string) => {
  const key = `admin.roles.resources.${resource}`
  const label = t(key)
  return label === key ? resource : label
}

// 授权选择器按 resource 分组，与角色管理页的权限选择体验保持一致。
const permissionGroups = computed(() => {
  const groups: Record<string, AssignablePermission[]> = {}
  assignablePermissions.value.forEach((perm) => {
    const key = perm.resource || 'other'
    if (!groups[key]) groups[key] = []
    groups[key].push(perm)
  })
  return Object.entries(groups).map(([resource, items]) => ({
    isGroup: true,
    label: resource === 'other' ? t('admin.roles.otherPermission') : resourceLabel(resource),
    options: items.map((item) => ({ value: item.code, label: item.name || item.code })),
  }))
})

const budgetFields = [
  { key: 'daily_executions', label: t('admin.agents.dailyExecutions') },
  { key: 'monthly_executions', label: t('admin.agents.monthlyExecutions') },
  { key: 'daily_tokens', label: t('admin.agents.dailyTokens') },
  { key: 'monthly_tokens', label: t('admin.agents.monthlyTokens') },
] as const

const formatBudget = (budget: Record<string, number> | undefined) => {
  if (!budget || Object.keys(budget).length === 0) return '-'
  return Object.entries(budget)
    .map(([key, value]) => `${key}: ${value}`)
    .join(', ')
}

const loadAgents = async () => {
  loading.value = true
  try {
    agents.value = await listAgents()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agents.loadFailed')))
  } finally {
    loading.value = false
  }
}

const loadMeta = async () => {
  try {
    const [permissions, catalog] = await Promise.all([listAssignablePermissions(), listBoards()])
    assignablePermissions.value = permissions
    boards.value = catalog.boards || []
    boardActions.value = catalog.actions || []
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agents.loadFailed')))
  }
}

// ---------- 新建 / 编辑 ----------

const modalVisible = ref(false)
const editMode = ref(false)
const editingId = ref('')
const form = ref<{
  name: string
  description: string
  prompt_key: string
  granted_permissions: string[]
  automation_policy: Record<string, AutomationLevel>
  budget: Record<string, number>
  enabled: boolean
}>({
  name: '',
  description: '',
  prompt_key: '',
  granted_permissions: [],
  automation_policy: {},
  budget: {},
  enabled: true,
})

const boardLevels = computed(() =>
  boards.value.map((board) => ({
    board,
    level: form.value.automation_policy[board] || 'supervised',
  })),
)

const actionsForBoard = (board: string) =>
  boardActions.value
    .filter((action) => action.board === board)
    .map((action) => ({ label: `${action.action}（${action.kind}）`, value: action.action }))

const openCreate = () => {
  editMode.value = false
  editingId.value = ''
  form.value = {
    name: '',
    description: '',
    prompt_key: '',
    granted_permissions: [],
    automation_policy: {},
    budget: {},
    enabled: true,
  }
  modalVisible.value = true
}

const openEdit = (agent: AdminAgent) => {
  editMode.value = true
  editingId.value = agent.id
  form.value = {
    name: agent.name,
    description: agent.description || '',
    prompt_key: agent.prompt_key || '',
    granted_permissions: agent.granted_permissions || [],
    automation_policy: { ...(agent.automation_policy || {}) },
    budget: { ...(agent.budget_config || {}) },
    enabled: agent.enabled,
  }
  modalVisible.value = true
}

const submit = async () => {
  if (!form.value.name.trim()) {
    Message.warning(t('admin.agents.nameRequired'))
    return
  }
  const automation_policy: Record<string, AutomationLevel> = {}
  for (const { board, level } of boardLevels.value) {
    if (level) automation_policy[board] = level
  }
  const budget = { ...form.value.budget }
  Object.keys(budget).forEach((key) => {
    if (budget[key] === null || budget[key] === undefined || budget[key] === 0) {
      delete budget[key]
    }
  })

  actionLoading.value = true
  try {
    if (editMode.value) {
      await updateAgent(editingId.value, {
        name: form.value.name.trim(),
        description: form.value.description,
        prompt_key: form.value.prompt_key || null,
        granted_permissions: form.value.granted_permissions,
        automation_policy,
        budget_config: budget,
        enabled: form.value.enabled,
      })
      Message.success(t('admin.agents.updated'))
    } else {
      await createAgent({
        name: form.value.name.trim(),
        description: form.value.description,
        prompt_key: form.value.prompt_key || null,
        granted_permissions: form.value.granted_permissions,
        automation_policy,
        budget_config: budget,
      })
      Message.success(t('admin.agents.created'))
    }
    modalVisible.value = false
    await loadAgents()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agents.saveFailed')))
  } finally {
    actionLoading.value = false
  }
}

// ---------- 删除 ----------

const handleDelete = (agent: AdminAgent) => {
  Modal.confirm({
    title: t('admin.agents.deleteTitle'),
    content: () => h('p', t('admin.agents.deleteDesc', { name: agent.name })),
    okText: t('common.actions.confirm'),
    okButtonProps: { status: 'danger' },
    cancelText: t('common.actions.cancel'),
    onBeforeOk: async () => {
      try {
        await deleteAgent(agent.id)
        Message.success(t('admin.agents.deleteSuccess'))
        await loadAgents()
        return true
      } catch (error) {
        Message.error(getErrorMessage(error, t('admin.agents.deleteFailed')))
        return false
      }
    },
  })
}

// ---------- 对话入口 ----------

const openChat = (agent: AdminAgent) => {
  router.push(`/admin/agents/${agent.id}/chat`)
}

// ---------- 定时任务 ----------

const scheduleModalVisible = ref(false)
const scheduleAgentId = ref('')
const scheduleLoading = ref(false)
const schedules = ref<ScheduleTask[]>([])
const scheduleForm = ref({
  name: '',
  cron_expression: '',
  board: '',
  action: '',
  payload: '',
})

const openSchedules = async (agent: AdminAgent) => {
  scheduleAgentId.value = agent.id
  scheduleForm.value = { name: '', cron_expression: '', board: '', action: '', payload: '' }
  scheduleModalVisible.value = true
  await loadSchedules()
}

const loadSchedules = async () => {
  if (!scheduleAgentId.value) return
  scheduleLoading.value = true
  try {
    const res = await listSchedules(scheduleAgentId.value)
    schedules.value = res.items || []
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agents.scheduleLoadFailed')))
  } finally {
    scheduleLoading.value = false
  }
}

const scheduleBoardOptions = computed(() =>
  boards.value.map((board) => ({ label: board, value: board })),
)

const scheduleActionOptions = computed(() => actionsForBoard(scheduleForm.value.board))

const submitSchedule = async () => {
  const formData = scheduleForm.value
  if (!formData.name.trim() || !formData.cron_expression.trim() || !formData.board || !formData.action) {
    Message.warning(t('admin.agents.scheduleSaveFailed'))
    return
  }
  let payload: Record<string, unknown> = {}
  if (formData.payload.trim()) {
    try {
      payload = JSON.parse(formData.payload.trim())
    } catch {
      Message.warning(t('admin.agents.schedulePayloadPlaceholder'))
      return
    }
  }
  actionLoading.value = true
  try {
    await createSchedule(scheduleAgentId.value, {
      name: formData.name.trim(),
      cron_expression: formData.cron_expression.trim(),
      board: formData.board,
      action: formData.action,
      prompt: formData.name.trim(),
      payload,
    })
    Message.success(t('admin.agents.scheduleCreateSuccess'))
    scheduleForm.value = { name: '', cron_expression: '', board: '', action: '', payload: '' }
    await loadSchedules()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agents.scheduleSaveFailed')))
  } finally {
    actionLoading.value = false
  }
}

const handleDeleteSchedule = (task: ScheduleTask) => {
  Modal.confirm({
    title: t('admin.agents.scheduleDeleteTitle'),
    content: () => h('p', t('admin.agents.scheduleDeleteDesc', { name: task.name })),
    okText: t('common.actions.confirm'),
    okButtonProps: { status: 'danger' },
    cancelText: t('common.actions.cancel'),
    onBeforeOk: async () => {
      try {
        await deleteSchedule(scheduleAgentId.value, task.id)
        Message.success(t('admin.agents.scheduleDeleteSuccess'))
        await loadSchedules()
        return true
      } catch (error) {
        Message.error(getErrorMessage(error, t('admin.agents.scheduleLoadFailed')))
        return false
      }
    },
  })
}

// ---------- 用量 ----------

const usageModalVisible = ref(false)
const usageLoading = ref(false)
const usage = ref<BudgetUsage | null>(null)

const openUsage = async (agent: AdminAgent) => {
  usageModalVisible.value = true
  usageLoading.value = true
  usage.value = null
  try {
    usage.value = await getBudgetUsage(agent.id)
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agents.usageLoadFailed')))
  } finally {
    usageLoading.value = false
  }
}

const usageRows = computed(() => {
  if (!usage.value) return []
  const cfg = usage.value.budget_config || {}
  const u = usage.value.usage || {}
  const rows: { label: string; used: number; limit: number }[] = []
  const defs = [
    { key: 'daily_executions', label: t('admin.agents.usageExecutionsDaily') },
    { key: 'monthly_executions', label: t('admin.agents.usageExecutionsMonthly') },
    { key: 'daily_tokens', label: t('admin.agents.usageTokensDaily') },
    { key: 'monthly_tokens', label: t('admin.agents.usageTokensMonthly') },
  ]
  for (const def of defs) {
    rows.push({ label: def.label, used: u[def.key as keyof typeof u] || 0, limit: cfg[def.key] || 0 })
  }
  return rows
})

onMounted(async () => {
  await loadMeta()
  await loadAgents()
})
</script>

<template>
  <section class="space-y-6">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold text-slate-900">{{ t('admin.agents.title') }}</h1>
        <p class="mt-1 text-sm text-slate-500">{{ t('admin.agents.description') }}</p>
      </div>
      <a-button v-if="canManage" type="primary" @click="openCreate">
        <template #icon><icon-plus /></template>
        {{ t('admin.agents.createAgent') }}
      </a-button>
    </header>

    <!-- KPI 概览 -->
    <section class="grid gap-4 md:grid-cols-3">
      <article class="rounded-xl border border-slate-200 bg-white p-4">
        <div class="flex items-center justify-between">
          <p class="text-sm text-slate-500">{{ t('admin.agents.kpiTotal') }}</p>
          <span class="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
            <icon-robot />
          </span>
        </div>
        <strong class="mt-2 block text-3xl font-semibold text-slate-900">{{ kpi.total }}</strong>
      </article>
      <article class="rounded-xl border border-slate-200 bg-white p-4">
        <div class="flex items-center justify-between">
          <p class="text-sm text-slate-500">{{ t('admin.agents.statusEnabled') }}</p>
          <span class="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-green-50 text-green-600">
            <icon-check-circle-fill />
          </span>
        </div>
        <strong class="mt-2 block text-3xl font-semibold text-green-600">{{ kpi.enabled }}</strong>
      </article>
      <article class="rounded-xl border border-slate-200 bg-white p-4">
        <div class="flex items-center justify-between">
          <p class="text-sm text-slate-500">{{ t('admin.agents.statusDisabled') }}</p>
          <span class="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-400">
            <icon-pause-circle-fill />
          </span>
        </div>
        <strong class="mt-2 block text-3xl font-semibold text-slate-500">{{ kpi.disabled }}</strong>
      </article>
    </section>

    <div class="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <table class="w-full text-left text-sm">
        <thead class="bg-slate-50 text-slate-500">
          <tr>
            <th class="p-3 font-medium">{{ t('admin.agents.name') }}</th>
            <th class="p-3 font-medium">{{ t('admin.agents.permissions') }}</th>
            <th class="p-3 font-medium">{{ t('admin.agents.automationPolicy') }}</th>
            <th class="p-3 font-medium">{{ t('admin.agents.budget') }}</th>
            <th class="p-3 font-medium">{{ t('admin.agents.enabled') }}</th>
            <th class="p-3 font-medium">{{ t('admin.agents.createdAt') }}</th>
            <th class="p-3 font-medium" style="width: 320px">{{ t('admin.agents.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading && !agents.length">
            <td colspan="7" class="p-6 text-center text-slate-400">…</td>
          </tr>
          <tr v-else-if="!agents.length">
            <td colspan="7" class="p-6 text-center">
              <a-empty :description="t('admin.agents.empty')" />
            </td>
          </tr>
          <tr v-for="record in agents" :key="record.id" class="border-t border-slate-100 hover:bg-slate-50/60">
            <td class="p-3">
              <div class="flex items-center gap-2.5">
                <span
                  class="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-xs font-semibold tracking-wide text-white"
                  :style="getAgentAvatarStyle(`${record.id}:${record.name}`)"
                >
                  {{ getAgentAvatarText(record.name) }}
                </span>
                <div class="min-w-0">
                  <div class="truncate font-medium text-slate-800">{{ record.name }}</div>
                  <div v-if="record.description" class="mt-0.5 max-w-xs truncate text-xs text-slate-400">
                    {{ record.description }}
                  </div>
                </div>
              </div>
            </td>
            <td class="p-3">
              <a-space v-if="record.granted_permissions && record.granted_permissions.length" :size="4" wrap>
                <a-tooltip
                  v-for="code in record.granted_permissions.slice(0, 2)"
                  :key="code"
                  :content="code"
                  position="tl"
                >
                  <a-tag size="small" color="arcoblue" class="cursor-help">
                    {{ permissionLabel(code) }}
                  </a-tag>
                </a-tooltip>
                <a-tooltip
                  v-if="record.granted_permissions.length > 2"
                  :content="record.granted_permissions.map((c) => permissionLabel(c)).join('、')"
                  position="tl"
                >
                  <a-tag size="small" color="gray" class="cursor-help">+{{ record.granted_permissions.length - 2 }}</a-tag>
                </a-tooltip>
              </a-space>
              <span v-else class="text-slate-300">-</span>
            </td>
            <td class="p-3">
              <div class="flex flex-wrap gap-1">
                <a-tag
                  v-for="(level, board) in record.automation_policy || {}"
                  :key="board"
                  size="small"
                  :color="level === 'autonomous' ? 'green' : level === 'blocked' ? 'red' : 'orange'"
                >
                  {{ board }}
                </a-tag>
                <span v-if="!Object.keys(record.automation_policy || {}).length" class="text-slate-300">-</span>
              </div>
            </td>
            <td class="p-3">
              <span class="text-xs text-slate-600">{{ formatBudget(record.budget_config) }}</span>
            </td>
            <td class="p-3">
              <a-tag v-if="record.enabled" size="small" color="green">{{ t('admin.agents.statusEnabled') }}</a-tag>
              <a-tag v-else size="small" color="red">{{ t('admin.agents.statusDisabled') }}</a-tag>
            </td>
            <td class="p-3 text-xs text-slate-500">{{ formatTime(record.created_at) }}</td>
            <td class="p-3">
              <a-space :size="4" wrap>
                <a-button size="mini" type="primary" @click="openChat(record)">
                  <template #icon><icon-message /></template>
                  {{ t('admin.agents.chat') }}
                </a-button>
                <a-button v-if="canManage" size="mini" @click="openEdit(record)">{{ t('admin.agents.edit') }}</a-button>
                <a-button v-if="canManage" size="mini" @click="openSchedules(record)">{{ t('admin.agents.schedules') }}</a-button>
                <a-button size="mini" @click="openUsage(record)">{{ t('admin.agents.usage') }}</a-button>
                <a-button
                  v-if="canManage"
                  size="mini"
                  status="danger"
                  @click="handleDelete(record)"
                >{{ t('admin.agents.deleteTitle') }}</a-button>
              </a-space>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 新建/编辑 Agent 弹窗 -->
    <a-modal
      v-model:visible="modalVisible"
      :title="editMode ? t('admin.agents.editAgent') : t('admin.agents.createAgent')"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submit"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item :label="t('admin.agents.name')" field="name">
          <a-input v-model="form.name" :placeholder="t('admin.agents.namePlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('admin.agents.descriptionLabel')" field="description">
          <a-textarea v-model="form.description" :placeholder="t('admin.agents.descriptionPlaceholder')" :auto-size="{ minRows: 2 }" />
        </a-form-item>
        <a-form-item :label="t('admin.agents.promptKey')" field="prompt_key">
          <a-input v-model="form.prompt_key" :placeholder="t('admin.agents.promptKeyPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('admin.agents.permissions')" field="granted_permissions">
          <a-select
            v-model="form.granted_permissions"
            :options="permissionGroups"
            multiple
            allow-search
            :placeholder="assignablePermissions.length ? t('admin.agents.permissionsPlaceholder') : t('admin.agents.noPermission')"
            :disabled="!assignablePermissions.length"
          >
            <template #label="{ data }">
              {{ permissionLabel(data.value) }}
            </template>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.agents.automationLevel')" field="automation_policy">
          <div class="w-full space-y-2">
            <div v-for="row in boardLevels" :key="row.board" class="flex items-center gap-2">
              <span class="w-40 shrink-0 text-sm text-gray-600">{{ row.board }}</span>
              <a-select v-model="row.level" :options="automationLevelOptions" size="small" class="flex-1" />
            </div>
            <span v-if="!boards.length" class="text-xs text-gray-400">{{ t('admin.agents.noPermission') }}</span>
          </div>
        </a-form-item>
        <a-form-item :label="t('admin.agents.budget')" field="budget">
          <div class="w-full space-y-2">
            <div v-for="field in budgetFields" :key="field.key" class="flex items-center gap-2">
              <span class="w-40 shrink-0 text-sm text-gray-600">{{ field.label }}</span>
              <a-input-number
                :model-value="form.budget[field.key]"
                :min="0"
                :placeholder="t('admin.agents.budgetHint')"
                class="flex-1"
                @change="(value: number | undefined) => {
                  if (value === undefined || value === null || value === 0) {
                    delete form.budget[field.key]
                  } else {
                    form.budget[field.key] = value
                  }
                }"
              />
            </div>
          </div>
        </a-form-item>
        <a-form-item v-if="editMode" :label="t('admin.agents.enabled')" field="enabled">
          <a-switch v-model="form.enabled" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 定时任务弹窗 -->
    <a-modal
      v-model:visible="scheduleModalVisible"
      :title="t('admin.agents.scheduleTitle')"
      :footer="false"
      :mask-closable="false"
    >
      <div class="mb-4 rounded border bg-gray-50 p-3">
        <p class="mb-2 text-sm font-medium text-gray-700">{{ t('admin.agents.scheduleCreate') }}</p>
        <a-form :model="scheduleForm" layout="vertical">
          <a-form-item :label="t('admin.agents.scheduleName')" field="name">
            <a-input v-model="scheduleForm.name" :placeholder="t('admin.agents.scheduleNamePlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('admin.agents.scheduleCron')" field="cron_expression">
            <a-input v-model="scheduleForm.cron_expression" :placeholder="t('admin.agents.scheduleCronPlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('admin.agents.scheduleBoard')" field="board">
            <a-select v-model="scheduleForm.board" :options="scheduleBoardOptions" :placeholder="t('admin.agents.scheduleBoard')" />
          </a-form-item>
          <a-form-item :label="t('admin.agents.scheduleAction')" field="action">
            <a-select
              v-model="scheduleForm.action"
              :options="scheduleActionOptions"
              :placeholder="t('admin.agents.scheduleAction')"
              :disabled="!scheduleForm.board"
            />
          </a-form-item>
          <a-form-item :label="t('admin.agents.schedulePayload')" field="payload">
            <a-textarea v-model="scheduleForm.payload" :placeholder="t('admin.agents.schedulePayloadPlaceholder')" :auto-size="{ minRows: 2 }" />
          </a-form-item>
          <a-button type="primary" :loading="actionLoading" @click="submitSchedule">{{ t('admin.agents.scheduleCreate') }}</a-button>
        </a-form>
      </div>
      <a-spin :loading="scheduleLoading">
        <a-empty v-if="!schedules.length" :description="t('admin.agents.scheduleListEmpty')" />
        <a-table v-else :data="schedules" :pagination="false" :bordered="{ wrapper: true, cell: true }" row-key="id">
          <a-table-column title="name" data-index="name" />
          <a-table-column title="cron" data-index="cron_expression" />
          <a-table-column title="status" data-index="status" />
          <a-table-column :title="t('admin.agents.actions')">
            <template #cell="{ record }">
              <a-button size="mini" status="danger" @click="handleDeleteSchedule(record)">{{ t('admin.agents.deleteTitle') }}</a-button>
            </template>
          </a-table-column>
        </a-table>
      </a-spin>
    </a-modal>

    <!-- 用量弹窗 -->
    <a-modal
      v-model:visible="usageModalVisible"
      :title="t('admin.agents.usageTitle')"
      :footer="false"
    >
      <a-spin :loading="usageLoading" style="width: 100%">
        <div class="space-y-3">
          <div v-for="row in usageRows" :key="row.label" class="flex items-center justify-between rounded border bg-gray-50 px-3 py-2">
            <span class="text-sm text-gray-600">{{ row.label }}</span>
            <span class="text-sm font-medium text-gray-900">
              {{ row.used }}<span v-if="row.limit"> / {{ row.limit }}</span>
              <span v-else class="text-gray-400">（{{ t('admin.agents.usageUnlimited') }}）</span>
            </span>
          </div>
          <p v-if="!usageRows.length" class="text-sm text-gray-400">{{ t('admin.agents.usageUnlimited') }}</p>
        </div>
      </a-spin>
    </a-modal>
  </section>
</template>
