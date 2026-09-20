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
  type AutomationLevel,
  type BoardAction,
  type BudgetUsage,
  type ScheduleTask,
} from '@/services/admin-agents'
import { getErrorMessage } from '@/utils/error'
import { useAdminStore } from '@/stores/admin'

const { t } = useI18n()
const router = useRouter()
const adminStore = useAdminStore()

const canManage = computed(() => adminStore.hasPermission('agent_pool:manage'))

const loading = ref(false)
const actionLoading = ref(false)
const agents = ref<AdminAgent[]>([])
const assignablePermissions = ref<string[]>([])
const boards = ref<string[]>([])
const boardActions = ref<BoardAction[]>([])

const formatTime = (value: number | null | undefined) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const automationLevelOptions = computed(() => [
  { label: t('admin.agents.levelSupervised'), value: 'supervised' },
  { label: t('admin.agents.levelAutonomous'), value: 'autonomous' },
  { label: t('admin.agents.levelBlocked'), value: 'blocked' },
])

const permissionOptions = computed(() =>
  assignablePermissions.value.map((code) => ({ label: code, value: code })),
)

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

const formatPolicy = (policy: Record<string, AutomationLevel> | undefined) => {
  if (!policy || Object.keys(policy).length === 0) return '-'
  return Object.entries(policy)
    .map(([board, level]) => {
      const labelMap: Record<AutomationLevel, string> = {
        supervised: t('admin.agents.levelSupervised'),
        autonomous: t('admin.agents.levelAutonomous'),
        blocked: t('admin.agents.levelBlocked'),
      }
      return `${board}: ${labelMap[level] || level}`
    })
    .join(', ')
}

const columns = computed(() => [
  { title: t('admin.agents.name'), slotName: 'name' },
  { title: t('admin.agents.permissions'), slotName: 'permissions' },
  { title: t('admin.agents.automationPolicy'), slotName: 'policy' },
  { title: t('admin.agents.budget'), slotName: 'budget' },
  { title: t('admin.agents.enabled'), slotName: 'enabled' },
  { title: t('admin.agents.createdAt'), slotName: 'created_at' },
  { title: t('admin.agents.actions'), slotName: 'actions', width: 320 },
])

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
  <section class="space-y-6 p-6">
    <header class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-semibold text-gray-900">{{ t('admin.agents.title') }}</h1>
        <p class="mt-1 text-sm text-gray-500">{{ t('admin.agents.description') }}</p>
      </div>
      <a-button v-if="canManage" type="primary" @click="openCreate">{{ t('admin.agents.createAgent') }}</a-button>
    </header>

    <a-table
      :loading="loading"
      :data="agents"
      :columns="columns"
      :pagination="false"
      :bordered="{ wrapper: true, cell: true }"
      row-key="id"
    >
      <template #columns>
        <a-table-column v-for="col of columns" :key="col.slotName" :title="col.title" :width="col.width">
          <template #cell="{ record }">
            <template v-if="col.slotName === 'name'">
              <div class="font-medium text-gray-900">{{ record.name }}</div>
              <div v-if="record.description" class="mt-0.5 max-w-xs truncate text-xs text-gray-400">
                {{ record.description }}
              </div>
            </template>
            <template v-else-if="col.slotName === 'permissions'">
              <a-tag v-for="code in record.granted_permissions" :key="code" size="small" color="arcoblue">
                {{ code }}
              </a-tag>
              <span v-if="!record.granted_permissions || !record.granted_permissions.length" class="text-gray-400">-</span>
            </template>
            <template v-else-if="col.slotName === 'policy'">
              <span class="text-xs text-gray-600">{{ formatPolicy(record.automation_policy) }}</span>
            </template>
            <template v-else-if="col.slotName === 'budget'">
              <span class="text-xs text-gray-600">{{ formatBudget(record.budget_config) }}</span>
            </template>
            <template v-else-if="col.slotName === 'enabled'">
              <a-tag v-if="record.enabled" size="small" color="green">{{ t('admin.agents.statusEnabled') }}</a-tag>
              <a-tag v-else size="small" color="red">{{ t('admin.agents.statusDisabled') }}</a-tag>
            </template>
            <template v-else-if="col.slotName === 'created_at'">{{ formatTime(record.created_at) }}</template>
            <template v-else-if="col.slotName === 'actions'">
              <a-space>
                <a-button size="mini" type="primary" @click="openChat(record)">{{ t('admin.agents.chat') }}</a-button>
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
            </template>
          </template>
        </a-table-column>
      </template>
    </a-table>

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
            :options="permissionOptions"
            multiple
            allow-search
            :placeholder="assignablePermissions.length ? t('admin.agents.permissionsPlaceholder') : t('admin.agents.noPermission')"
            :disabled="!assignablePermissions.length"
          />
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
