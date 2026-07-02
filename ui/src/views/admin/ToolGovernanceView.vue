<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  batchUpdateRisk,
  createToolPolicy,
  deleteToolPolicy,
  getToolGovernanceStats,
  listToolAuditLogs,
  listToolPolicies,
  setToolPolicyStatus,
  updateToolPolicy,
} from '@/services/admin-tool-governance'
import { getErrorMessage } from '@/utils/error'

type ToolPolicy = {
  id: string
  tool_id: string
  tool_name: string
  source_type: string
  provider_id: string
  risk_level: string
  visibility: string
  allowed_pools: string[]
  enabled: boolean
  max_invocations_per_request: number
  cooldown_seconds: number
  require_confirmation: boolean
  description: string
  created_at?: number
  updated_at?: number
}

type AuditLog = {
  id: string
  tool_id: string
  tool_name: string
  account_id: string
  conversation_id: string
  invocation_status: string
  duration_ms: number
  error_message: string
  created_at?: number
}

type GovernanceStats = {
  total: number
  enabled: number
  disabled: number
  enabled_rate: number
  risk_distribution: Record<string, number>
  source_distribution: Record<string, number>
  visibility_distribution: Record<string, number>
}

const RISK_LEVELS = ['low', 'medium', 'high', 'critical']
const SOURCE_TYPES = ['api_tool', 'mcp', 'skill', 'builtin', 'knowledge', 'workflow', 'agent_binding']
const VISIBILITIES = ['private', 'tenant', 'public']
const INVOCATION_STATUSES = ['success', 'failed', 'blocked', 'timeout']

const { t } = useI18n()

const loading = ref(false)
const actionLoading = ref(false)
const activeTab = ref('policies')

const policies = ref<ToolPolicy[]>([])
const audits = ref<AuditLog[]>([])
const stats = ref<GovernanceStats>({
  total: 0,
  enabled: 0,
  disabled: 0,
  enabled_rate: 0,
  risk_distribution: {},
  source_distribution: {},
  visibility_distribution: {},
})

const filters = ref({
  current_page: 1,
  page_size: 20,
  source_type: '',
  risk_level: '',
  visibility: '',
  enabled: '',
  keyword: '',
})

const auditFilters = ref({
  current_page: 1,
  page_size: 20,
  tool_id: '',
  status: '',
  start_date: '',
  end_date: '',
})

const policyPaginator = ref({ total_record: 0, total_page: 0, current_page: 1, page_size: 20 })

const auditPaginator = ref({ total_record: 0, total_page: 0, current_page: 1, page_size: 20 })

const selectedIds = ref<string[]>([])
const batchRiskLevel = ref('medium')
const batchModalVisible = ref(false)

const modalVisible = ref(false)
const editMode = ref(false)
const editingId = ref('')
const form = ref({
  tool_id: '',
  tool_name: '',
  source_type: 'api_tool',
  risk_level: 'medium',
  visibility: 'tenant',
  allowed_pools: [] as string[],
  description: '',
})

const riskColor = (risk: string) =>
  ({ low: 'green', medium: 'blue', high: 'orange', critical: 'red' } as Record<string, string>)[risk] || 'gray'

const statusColor = (status: string) =>
  ({ success: 'green', failed: 'red', blocked: 'orange', timeout: 'gray' } as Record<string, string>)[status] || 'gray'

const enabledRatePercent = computed(() => `${Math.round((stats.value.enabled_rate || 0) * 100)}%`)

const riskEntries = computed(() => Object.entries(stats.value.risk_distribution || {}))
const sourceEntries = computed(() => Object.entries(stats.value.source_distribution || {}))

const formatTimestamp = (timestamp?: number) =>
  timestamp ? new Date(timestamp * 1000).toLocaleString() : '-'

const loadPolicies = async () => {
  loading.value = true
  try {
    const result = await listToolPolicies({
      current_page: filters.value.current_page,
      page_size: filters.value.page_size,
      source_type: filters.value.source_type,
      risk_level: filters.value.risk_level,
      visibility: filters.value.visibility,
      enabled: filters.value.enabled,
      keyword: filters.value.keyword,
    })
    const data = (result as { data?: { list?: ToolPolicy[]; paginator?: typeof policyPaginator.value } }).data
    policies.value = data?.list || []
    policyPaginator.value = data?.paginator || policyPaginator.value
    selectedIds.value = []
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.toolGovernance.messages.loadPoliciesFailed')))
  } finally {
    loading.value = false
  }
}

const loadStats = async () => {
  try {
    const result = await getToolGovernanceStats()
    stats.value = (result as { data?: GovernanceStats }).data || stats.value
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.toolGovernance.messages.loadStatsFailed')))
  }
}

const loadAudits = async () => {
  loading.value = true
  try {
    const result = await listToolAuditLogs({
      current_page: auditFilters.value.current_page,
      page_size: auditFilters.value.page_size,
      tool_id: auditFilters.value.tool_id,
      status: auditFilters.value.status,
      start_date: auditFilters.value.start_date,
      end_date: auditFilters.value.end_date,
    })
    const data = (result as { data?: { list?: AuditLog[]; paginator?: typeof auditPaginator.value } }).data
    audits.value = data?.list || []
    auditPaginator.value = data?.paginator || auditPaginator.value
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.toolGovernance.messages.loadAuditsFailed')))
  } finally {
    loading.value = false
  }
}

const loadAll = async () => {
  await Promise.all([loadPolicies(), loadStats()])
}

const openCreate = () => {
  editMode.value = false
  editingId.value = ''
  form.value = {
    tool_id: '',
    tool_name: '',
    source_type: 'api_tool',
    risk_level: 'medium',
    visibility: 'tenant',
    allowed_pools: [],
    description: '',
  }
  modalVisible.value = true
}

const openEdit = (policy: ToolPolicy) => {
  editMode.value = true
  editingId.value = policy.id
  form.value = {
    tool_id: policy.tool_id,
    tool_name: policy.tool_name,
    source_type: policy.source_type,
    risk_level: policy.risk_level,
    visibility: policy.visibility,
    allowed_pools: [...(policy.allowed_pools || [])],
    description: policy.description || '',
  }
  modalVisible.value = true
}

const submit = async () => {
  actionLoading.value = true
  try {
    const payload = { ...form.value }
    if (editMode.value) {
      await updateToolPolicy(editingId.value, payload)
      Message.success(t('admin.toolGovernance.messages.updateSuccess'))
    } else {
      await createToolPolicy(payload)
      Message.success(t('admin.toolGovernance.messages.createSuccess'))
    }
    modalVisible.value = false
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.toolGovernance.messages.saveFailed')))
  } finally {
    actionLoading.value = false
  }
}

const toggleStatus = async (policy: ToolPolicy, enabled: boolean) => {
  actionLoading.value = true
  try {
    await setToolPolicyStatus(policy.id, enabled)
    Message.success(enabled ? t('admin.toolGovernance.messages.enabled') : t('admin.toolGovernance.messages.disabled'))
    await loadPolicies()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.toolGovernance.messages.toggleStatusFailed')))
  } finally {
    actionLoading.value = false
  }
}

const remove = async (policy: ToolPolicy) => {
  actionLoading.value = true
  try {
    await deleteToolPolicy(policy.id)
    Message.success(t('admin.toolGovernance.messages.deleteSuccess'))
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.toolGovernance.messages.deleteFailed')))
  } finally {
    actionLoading.value = false
  }
}

const openBatchRisk = () => {
  if (!selectedIds.value.length) {
    Message.warning(t('admin.toolGovernance.messages.selectFirst'))
    return
  }
  batchRiskLevel.value = 'medium'
  batchModalVisible.value = true
}

const submitBatchRisk = async () => {
  actionLoading.value = true
  try {
    await batchUpdateRisk(selectedIds.value, batchRiskLevel.value)
    Message.success(t('admin.toolGovernance.messages.batchSuccess'))
    batchModalVisible.value = false
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.toolGovernance.messages.batchFailed')))
  } finally {
    actionLoading.value = false
  }
}

const onPolicyPageChange = (page: number) => {
  filters.value.current_page = page
  loadPolicies()
}

const onPolicyPageSizeChange = (size: number) => {
  filters.value.page_size = size
  filters.value.current_page = 1
  loadPolicies()
}

const handlePolicySearch = () => {
  filters.value.current_page = 1
  loadPolicies()
}

const onAuditPageChange = (page: number) => {
  auditFilters.value.current_page = page
  loadAudits()
}

const onAuditPageSizeChange = (size: number) => {
  auditFilters.value.page_size = size
  auditFilters.value.current_page = 1
  loadAudits()
}

const handleAuditSearch = () => {
  auditFilters.value.current_page = 1
  loadAudits()
}

onMounted(loadAll)
</script>

<template>
  <section class="space-y-6 p-6">
    <header>
      <h1 class="text-2xl font-semibold text-gray-900">{{ $t('admin.toolGovernance.title') }}</h1>
      <p class="mt-1 text-sm text-gray-500">{{ $t('admin.toolGovernance.description') }}</p>
    </header>

    <div class="grid gap-4 md:grid-cols-4">
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ $t('admin.toolGovernance.stats.total') }}</p>
        <strong class="text-xl">{{ stats.total }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ $t('admin.toolGovernance.stats.enabledRate') }}</p>
        <strong class="text-xl">{{ enabledRatePercent }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ $t('admin.toolGovernance.stats.riskDistribution') }}</p>
        <div class="mt-1 flex flex-wrap gap-1">
          <a-tag v-for="[risk, count] in riskEntries" :key="risk" :color="riskColor(risk)" size="small">{{ risk }}: {{ count }}</a-tag>
          <span v-if="!riskEntries.length" class="text-gray-400">-</span>
        </div>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ $t('admin.toolGovernance.stats.sourceDistribution') }}</p>
        <div class="mt-1 flex flex-wrap gap-1">
          <a-tag v-for="[source, count] in sourceEntries" :key="source" size="small">{{ source }}: {{ count }}</a-tag>
          <span v-if="!sourceEntries.length" class="text-gray-400">-</span>
        </div>
      </article>
    </div>

    <a-tabs v-model:active-key="activeTab" type="rounded" @change="(key: string | number) => key === 'audit' && loadAudits()">
      <a-tab-pane key="policies" :title="$t('admin.toolGovernance.tabs.policy')">
        <div class="mb-3 flex flex-wrap items-end gap-3">
          <a-input v-model="filters.keyword" :placeholder="$t('admin.toolGovernance.placeholder.keyword')" style="width: 200px" allow-clear />
          <a-select v-model="filters.source_type" :placeholder="$t('admin.toolGovernance.field.sourceType')" style="width: 140px" allow-clear>
            <a-option v-for="s in SOURCE_TYPES" :key="s" :value="s">{{ s }}</a-option>
          </a-select>
          <a-select v-model="filters.risk_level" :placeholder="$t('admin.toolGovernance.field.riskLevel')" style="width: 140px" allow-clear>
            <a-option v-for="r in RISK_LEVELS" :key="r" :value="r">{{ r }}</a-option>
          </a-select>
          <a-select v-model="filters.visibility" :placeholder="$t('admin.toolGovernance.field.visibility')" style="width: 140px" allow-clear>
            <a-option v-for="v in VISIBILITIES" :key="v" :value="v">{{ v }}</a-option>
          </a-select>
          <a-button :loading="loading" @click="handlePolicySearch">{{ $t('admin.toolGovernance.search') }}</a-button>
          <a-button :disabled="!selectedIds.length" @click="openBatchRisk">{{ $t('admin.toolGovernance.batchRisk') }}</a-button>
          <div class="ml-auto">
            <a-button type="primary" @click="openCreate">{{ $t('admin.toolGovernance.createPolicy') }}</a-button>
          </div>
        </div>
        <a-spin :loading="loading" class="block">
          <div class="overflow-hidden rounded-lg border bg-white">
            <a-table
              :data="policies"
              row-key="id"
              :row-selection="{ type: 'checkbox', showCheckedAll: true, width: 60 }"
              v-model:selectedKeys="selectedIds"
              :pagination="false"
              :bordered="{ wrapper: true, cell: true }"
            >
              <template #empty>{{ $t('admin.toolGovernance.empty.policies') }}</template>
              <template #columns>
                <a-table-column :title="$t('admin.toolGovernance.field.toolName')" data-index="tool_name">
                  <template #cell="{ record }">
                    <span class="font-medium">{{ record.tool_name || '-' }}</span>
                    <p class="text-xs text-gray-400">{{ record.tool_id }}</p>
                  </template>
                </a-table-column>
                <a-table-column :title="$t('admin.toolGovernance.field.sourceType')" data-index="source_type" :width="110" />
                <a-table-column :title="$t('admin.toolGovernance.field.riskLevel')" data-index="risk_level" :width="110">
                  <template #cell="{ record }">
                    <a-tag :color="riskColor(record.risk_level)" size="small">{{ record.risk_level }}</a-tag>
                  </template>
                </a-table-column>
                <a-table-column :title="$t('admin.toolGovernance.field.visibility')" data-index="visibility" :width="100" />
                <a-table-column :title="$t('admin.toolGovernance.field.allowedPools')" data-index="allowed_pools">
                  <template #cell="{ record }">
                    <a-tag v-for="pool in record.allowed_pools" :key="pool" size="small">{{ pool }}</a-tag>
                    <span v-if="!record.allowed_pools?.length" class="text-gray-400">-</span>
                  </template>
                </a-table-column>
                <a-table-column :title="$t('admin.toolGovernance.field.status')" :width="80">
                  <template #cell="{ record }">
                    <a-switch
                      :model-value="record.enabled"
                      :loading="actionLoading"
                      @change="(v: string | number | boolean) => toggleStatus(record, Boolean(v))"
                    />
                  </template>
                </a-table-column>
                <a-table-column :title="$t('admin.toolGovernance.field.actions')" :width="160">
                  <template #cell="{ record }">
                    <a-space>
                      <a-button size="mini" @click="openEdit(record)">{{ $t('admin.toolGovernance.actions.edit') }}</a-button>
                      <a-button size="mini" status="danger" @click="remove(record)">{{ $t('admin.toolGovernance.actions.delete') }}</a-button>
                    </a-space>
                  </template>
                </a-table-column>
              </template>
            </a-table>
          </div>
        </a-spin>
        <div class="mt-3 flex justify-end">
          <a-pagination
            :total="policyPaginator.total_record"
            :current="filters.current_page"
            :page-size="filters.page_size"
            show-total
            show-page-size
            :page-size-options="[10, 20, 50, 100]"
            @change="onPolicyPageChange"
            @page-size-change="onPolicyPageSizeChange"
          />
        </div>
      </a-tab-pane>

      <a-tab-pane key="audit" :title="$t('admin.toolGovernance.tabs.audit')">
        <div class="mb-3 flex flex-wrap items-end gap-3">
          <a-input v-model="auditFilters.tool_id" :placeholder="$t('admin.toolGovernance.field.toolId')" style="width: 200px" allow-clear />
          <a-select v-model="auditFilters.status" :placeholder="$t('admin.toolGovernance.field.invocationStatus')" style="width: 160px" allow-clear>
            <a-option v-for="s in INVOCATION_STATUSES" :key="s" :value="s">{{ s }}</a-option>
          </a-select>
          <a-date-picker v-model="auditFilters.start_date" :placeholder="$t('admin.toolGovernance.placeholder.startDate')" style="width: 180px" />
          <a-date-picker v-model="auditFilters.end_date" :placeholder="$t('admin.toolGovernance.placeholder.endDate')" style="width: 180px" />
          <a-button :loading="loading" @click="handleAuditSearch">{{ $t('admin.toolGovernance.search') }}</a-button>
        </div>
        <a-spin :loading="loading" class="block">
          <div class="overflow-hidden rounded-lg border bg-white">
            <table class="w-full text-left text-sm">
              <thead class="bg-gray-50 text-gray-500">
                <tr>
                  <th class="p-3">{{ $t('admin.toolGovernance.field.toolName') }}</th>
                  <th class="p-3">{{ $t('admin.toolGovernance.field.toolId') }}</th>
                  <th class="p-3">{{ $t('admin.toolGovernance.field.caller') }}</th>
                  <th class="p-3">{{ $t('admin.toolGovernance.field.status') }}</th>
                  <th class="p-3">{{ $t('admin.toolGovernance.field.duration') }}</th>
                  <th class="p-3">{{ $t('admin.toolGovernance.field.errorMessage') }}</th>
                  <th class="p-3">{{ $t('admin.toolGovernance.field.time') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!audits.length">
                  <td class="p-6 text-center text-gray-400" colspan="7">{{ $t('admin.toolGovernance.empty.audits') }}</td>
                </tr>
                <tr v-for="log in audits" :key="log.id" class="border-t">
                  <td class="p-3">{{ log.tool_name || '-' }}</td>
                  <td class="p-3 font-mono text-xs">{{ log.tool_id }}</td>
                  <td class="p-3 font-mono text-xs">{{ log.account_id || '-' }}</td>
                  <td class="p-3">
                    <a-tag :color="statusColor(log.invocation_status)" size="small">{{ log.invocation_status }}</a-tag>
                  </td>
                  <td class="p-3">{{ log.duration_ms ?? '-' }}</td>
                  <td class="p-3 text-gray-500">{{ log.error_message || '-' }}</td>
                  <td class="p-3">{{ formatTimestamp(log.created_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </a-spin>
        <div class="mt-3 flex justify-end">
          <a-pagination
            :current="auditPaginator.current_page"
            :page-size="auditPaginator.page_size"
            :total="auditPaginator.total_record"
            show-total
            show-page-size
            :page-size-options="[10, 20, 50, 100]"
            @change="onAuditPageChange"
            @page-size-change="onAuditPageSizeChange"
          />
        </div>
      </a-tab-pane>
    </a-tabs>

    <a-modal
      v-model:visible="modalVisible"
      :title="editMode ? $t('admin.toolGovernance.editPolicyTitle') : $t('admin.toolGovernance.createPolicyTitle')"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submit"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item :label="$t('admin.toolGovernance.field.toolId')" field="tool_id">
          <a-input v-model="form.tool_id" :placeholder="$t('admin.toolGovernance.placeholder.toolId')" :disabled="editMode" />
        </a-form-item>
        <a-form-item :label="$t('admin.toolGovernance.field.toolName')" field="tool_name">
          <a-input v-model="form.tool_name" :placeholder="$t('admin.toolGovernance.placeholder.toolName')" />
        </a-form-item>
        <a-form-item :label="$t('admin.toolGovernance.field.sourceType')" field="source_type">
          <a-select v-model="form.source_type">
            <a-option v-for="s in SOURCE_TYPES" :key="s" :value="s">{{ s }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="$t('admin.toolGovernance.field.riskLevel')" field="risk_level">
          <a-select v-model="form.risk_level">
            <a-option v-for="r in RISK_LEVELS" :key="r" :value="r">{{ r }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="$t('admin.toolGovernance.field.visibility')" field="visibility">
          <a-select v-model="form.visibility">
            <a-option v-for="v in VISIBILITIES" :key="v" :value="v">{{ v }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="$t('admin.toolGovernance.field.allowedPools')" field="allowed_pools">
          <a-select v-model="form.allowed_pools" multiple allow-search allow-create>
            <a-option value="tenant">tenant</a-option>
            <a-option value="system">system</a-option>
            <a-option value="global">global</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="$t('admin.toolGovernance.form.description')" field="description">
          <a-input v-model="form.description" :placeholder="$t('admin.toolGovernance.placeholder.description')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:visible="batchModalVisible"
      :title="$t('admin.toolGovernance.batchModal.title')"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submitBatchRisk"
    >
      <p class="mb-3 text-sm text-gray-500">{{ $t('admin.toolGovernance.batchModal.description', { count: selectedIds.length }) }}</p>
      <a-select v-model="batchRiskLevel">
        <a-option v-for="r in RISK_LEVELS" :key="r" :value="r">{{ r }}</a-option>
      </a-select>
    </a-modal>
  </section>
</template>
