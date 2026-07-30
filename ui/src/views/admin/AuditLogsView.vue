<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { listAuditLogs, type AuditLog } from '@/services/admin-audit-logs'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()

const loading = ref(false)
const logs = ref<AuditLog[]>([])
const total = ref(0)
const detailTarget = ref<AuditLog | null>(null)

const RESOURCE_TYPE_COLORS: Record<string, string> = {
  app: 'arcoblue',
  workflow: 'purple',
  dataset: 'cyan',
  tool: 'orange',
  api_tool: 'orangered',
  mcp: 'magenta',
  skill: 'green',
  agent_pool_config: 'blue',
  tool_governance_policy: 'gold',
  model: 'pinkpurple',
  orchestration_flag: 'red',
  sub_pool_definition: 'lime',
}

const getResourceTypeColor = (resourceType: string | null | undefined): string => {
  if (!resourceType) return 'gray'
  return RESOURCE_TYPE_COLORS[resourceType] || 'gray'
}

const truncateId = (id: string | null | undefined): string => {
  if (!id) return ''
  return id.length > 8 ? `${id.slice(0, 8)}...` : id
}

const ACTION_LABELS: Record<string, string> = {
  create: 'admin.auditLogs.actionCreate',
  update: 'admin.auditLogs.actionUpdate',
  disable: 'admin.auditLogs.actionDisable',
  enable: 'admin.auditLogs.actionEnable',
  delete: 'admin.auditLogs.actionDelete',
  reset_password: 'admin.auditLogs.actionResetPassword',
  revoke_sessions: 'admin.auditLogs.actionRevokeSessions',
  assign: 'admin.auditLogs.actionAssign',
  revoke: 'admin.auditLogs.actionRevoke',
  generate: 'admin.auditLogs.actionGenerate',
  set_status: 'admin.auditLogs.actionSetStatus',
  sync: 'admin.auditLogs.actionSync',
  rollback: 'admin.auditLogs.actionRollback',
  confirm: 'admin.auditLogs.actionConfirm',
  cancel: 'admin.auditLogs.actionCancel',
  tool_invocation: 'admin.auditLogs.actionToolInvocation',
  policy_change_apply: 'admin.auditLogs.actionPolicyApply',
  policy_change_rollback: 'admin.auditLogs.actionPolicyRollback',
}

const RESOURCE_TYPE_LABELS: Record<string, string> = {
  admin_user: 'admin.auditLogs.resourceAdminUser',
  customer_user: 'admin.auditLogs.resourceCustomerUser',
  role: 'admin.auditLogs.resourceRole',
  app: 'admin.auditLogs.resourceApp',
  app_assignment: 'admin.auditLogs.resourceAppAssignment',
  workflow: 'admin.auditLogs.resourceWorkflow',
  tool: 'admin.auditLogs.resourceTool',
  api_tool: 'admin.auditLogs.resourceApiTool',
  mcp: 'admin.auditLogs.resourceMcp',
  skill: 'admin.auditLogs.resourceSkill',
  plan: 'admin.auditLogs.resourcePlan',
  redeem_code: 'admin.auditLogs.resourceRedeemCode',
  redeem_code_batch: 'admin.auditLogs.resourceRedeemCodeBatch',
  system_knowledge: 'admin.auditLogs.resourceSystemKnowledge',
  agent_pool_config: 'admin.auditLogs.resourceAgentPoolConfig',
  tool_governance_policy: 'admin.auditLogs.resourceToolGovernancePolicy',
  model: 'admin.auditLogs.resourceModel',
  orchestration_flag: 'admin.auditLogs.resourceOrchestrationFlag',
  sub_pool_definition: 'admin.auditLogs.resourceSubPoolDefinition',
  policy_change_draft: 'admin.auditLogs.resourcePolicyChangeDraft',
}

const actionLabel = (action: string | null | undefined): string => {
  if (!action) return '-'
  const key = ACTION_LABELS[action]
  return key ? t(key) : action
}

const resourceTypeLabel = (resourceType: string | null | undefined): string => {
  if (!resourceType) return t('admin.auditLogs.unknownResource')
  const key = RESOURCE_TYPE_LABELS[resourceType]
  return key ? t(key) : resourceType
}

const actionOptions = computed(() => [
  { label: t('admin.auditLogs.allActions'), value: '' },
  { label: t('admin.auditLogs.actionCreate'), value: 'create' },
  { label: t('admin.auditLogs.actionUpdate'), value: 'update' },
  { label: t('admin.auditLogs.actionDisable'), value: 'disable' },
  { label: t('admin.auditLogs.actionDelete'), value: 'delete' },
])

const filters = ref({
  action: '',
  resource_type: '',
  start: '',
  end: '',
  current_page: 1,
  page_size: 20,
})

const formatTime = (value: number | null | undefined) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const toUnix = (value: string) => {
  if (!value) return undefined
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return undefined
  return Math.floor(time / 1000)
}

const loadLogs = async () => {
  loading.value = true
  try {
    const res = await listAuditLogs({
      action: filters.value.action || undefined,
      resource_type: filters.value.resource_type || undefined,
      start_time: toUnix(filters.value.start),
      end_time: toUnix(filters.value.end),
      current_page: filters.value.current_page,
      page_size: filters.value.page_size,
    })
    logs.value = res.data.list || []
    total.value = res.data.paginator.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.auditLogs.loadFailed')))
  } finally {
    loading.value = false
  }
}

const handleSearch = async () => {
  filters.value.current_page = 1
  await loadLogs()
}

const onPageChange = async (page: number) => {
  filters.value.current_page = page
  await loadLogs()
}

const onPageSizeChange = async (size: number) => {
  filters.value.page_size = size
  filters.value.current_page = 1
  await loadLogs()
}

const openDetail = (log: AuditLog) => {
  detailTarget.value = log
}

const stringify = (value: Record<string, unknown> | undefined) => {
  if (!value) return '-'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return '-'
  }
}

onMounted(loadLogs)
</script>

<template>
  <section class="space-y-6 p-6">
    <header>
      <h1 class="text-2xl font-semibold text-gray-900">{{ t('admin.auditLogs.title') }}</h1>
      <p class="mt-1 text-sm text-gray-500">{{ t('admin.auditLogs.description') }}</p>
    </header>

    <div class="rounded-lg border bg-white p-4">
      <div class="grid gap-3 md:grid-cols-4">
        <a-select v-model="filters.action" :options="actionOptions" :placeholder="t('admin.auditLogs.actionTypePlaceholder')" />
        <a-input v-model="filters.resource_type" :placeholder="t('admin.auditLogs.resourceTypePlaceholder')" allow-clear />
        <input
          v-model="filters.start"
          type="datetime-local"
          class="h-8 w-full rounded border border-gray-300 px-2 text-sm"
          :placeholder="t('admin.auditLogs.startTimePlaceholder')"
        />
        <input
          v-model="filters.end"
          type="datetime-local"
          class="h-8 w-full rounded border border-gray-300 px-2 text-sm"
          :placeholder="t('admin.auditLogs.endTimePlaceholder')"
        />
      </div>
      <a-button class="mt-3" type="primary" :loading="loading" @click="handleSearch">{{ t('admin.auditLogs.search') }}</a-button>
    </div>

    <a-spin :loading="loading" class="block">
      <div class="overflow-hidden rounded-lg border bg-white">
        <table class="w-full text-left text-sm">
          <thead class="bg-gray-50 text-gray-500">
            <tr>
              <th class="p-3">{{ t('admin.auditLogs.time') }}</th>
              <th class="p-3">{{ t('admin.auditLogs.admin') }}</th>
              <th class="p-3">{{ t('admin.auditLogs.action') }}</th>
              <th class="p-3">{{ t('admin.auditLogs.resourceType') }}</th>
              <th class="p-3">{{ t('admin.auditLogs.resourceId') }}</th>
              <th class="p-3">IP</th>
              <th class="p-3">{{ t('admin.auditLogs.detail') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!logs.length">
              <td class="p-6 text-center text-gray-400" colspan="7">{{ t('admin.auditLogs.empty') }}</td>
            </tr>
            <tr v-for="log in logs" :key="log.id" class="border-t">
              <td class="p-3 whitespace-nowrap">{{ formatTime(log.created_at) }}</td>
              <td class="p-3">
                <span v-if="log.admin_user_name">{{ log.admin_user_name }}</span>
                <span v-else-if="log.account_name">{{ log.account_name }}</span>
                <span v-else class="text-gray-400">{{ truncateId(log.admin_user_id) || '-' }}</span>
              </td>
              <td class="p-3">
                <a-tag size="small">{{ actionLabel(log.action) }}</a-tag>
              </td>
              <td class="p-3">
                <a-tag v-if="log.resource_type" :color="getResourceTypeColor(log.resource_type)" size="small">{{ resourceTypeLabel(log.resource_type) }}</a-tag>
                <a-tag v-else color="gray" size="small">{{ t('admin.auditLogs.unknownResource') }}</a-tag>
              </td>
              <td class="p-3 font-mono text-xs">
                <a-tooltip v-if="log.resource_id" :content="log.resource_id" position="top" mini>
                  <span class="text-gray-600">{{ truncateId(log.resource_id) }}</span>
                </a-tooltip>
                <span v-else class="text-gray-400">-</span>
              </td>
              <td class="p-3 text-xs">{{ log.ip || '-' }}</td>
              <td class="p-3">
                <a-button size="mini" @click="openDetail(log)">{{ t('admin.auditLogs.view') }}</a-button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </a-spin>

    <div class="flex justify-end">
      <a-pagination
        :total="total"
        :current="filters.current_page"
        :page-size="filters.page_size"
        show-total
        show-page-size
        @change="onPageChange"
        @page-size-change="onPageSizeChange"
      />
    </div>

    <a-modal :visible="!!detailTarget" :width="640" :footer="false" @cancel="detailTarget = null">
      <template #title>{{ t('admin.auditLogs.detailTitle') }}</template>
      <div v-if="detailTarget" class="space-y-4">
        <div class="grid grid-cols-2 gap-3 text-sm">
          <div><span class="text-gray-500">{{ t('admin.auditLogs.admin') }}</span>{{ detailTarget.admin_user_name || detailTarget.account_name || truncateId(detailTarget.admin_user_id) || '-' }}</div>
          <div><span class="text-gray-500">{{ t('admin.auditLogs.actionLabel') }}</span>{{ actionLabel(detailTarget.action) }}</div>
          <div><span class="text-gray-500">{{ t('admin.auditLogs.resourceTypeLabel') }}</span>{{ resourceTypeLabel(detailTarget.resource_type) }}</div>
          <div><span class="text-gray-500">{{ t('admin.auditLogs.resourceIdLabel') }}</span>{{ detailTarget.resource_id || '-' }}</div>
          <div><span class="text-gray-500">IP：</span>{{ detailTarget.ip || '-' }}</div>
          <div class="col-span-2"><span class="text-gray-500">User-Agent：</span>{{ detailTarget.user_agent || '-' }}</div>
        </div>
        <div>
          <p class="mb-1 text-sm font-medium text-gray-700">{{ t('admin.auditLogs.beforeChange') }}</p>
          <pre class="max-h-48 overflow-auto rounded bg-gray-50 p-3 text-xs">{{ stringify(detailTarget.before_data) }}</pre>
        </div>
        <div>
          <p class="mb-1 text-sm font-medium text-gray-700">{{ t('admin.auditLogs.afterChange') }}</p>
          <pre class="max-h-48 overflow-auto rounded bg-gray-50 p-3 text-xs">{{ stringify(detailTarget.after_data) }}</pre>
        </div>
      </div>
    </a-modal>
  </section>
</template>
