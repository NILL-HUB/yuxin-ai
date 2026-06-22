<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
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
const SOURCE_TYPES = ['api_tool', 'mcp', 'skill', 'builtin']
const VISIBILITIES = ['private', 'tenant', 'public']
const INVOCATION_STATUSES = ['success', 'failed', 'blocked', 'timeout']

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
    const data = result as { list?: ToolPolicy[] }
    policies.value = data.list || []
    selectedIds.value = []
  } catch (error) {
    Message.error(getErrorMessage(error, '加载治理策略失败'))
  } finally {
    loading.value = false
  }
}

const loadStats = async () => {
  try {
    const result = await getToolGovernanceStats()
    stats.value = result as GovernanceStats
  } catch (error) {
    Message.error(getErrorMessage(error, '加载治理统计失败'))
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
    const data = result as { list?: AuditLog[]; paginator?: typeof auditPaginator.value }
    audits.value = data.list || []
    auditPaginator.value = data.paginator || auditPaginator.value
  } catch (error) {
    Message.error(getErrorMessage(error, '加载审计日志失败'))
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
      Message.success('治理策略已更新')
    } else {
      await createToolPolicy(payload)
      Message.success('治理策略已创建')
    }
    modalVisible.value = false
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '保存治理策略失败'))
  } finally {
    actionLoading.value = false
  }
}

const toggleStatus = async (policy: ToolPolicy, enabled: boolean) => {
  actionLoading.value = true
  try {
    await setToolPolicyStatus(policy.id, enabled)
    Message.success(enabled ? '已启用' : '已停用')
    await loadPolicies()
  } catch (error) {
    Message.error(getErrorMessage(error, '更新状态失败'))
  } finally {
    actionLoading.value = false
  }
}

const remove = async (policy: ToolPolicy) => {
  actionLoading.value = true
  try {
    await deleteToolPolicy(policy.id)
    Message.success('策略已删除')
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '删除策略失败'))
  } finally {
    actionLoading.value = false
  }
}

const openBatchRisk = () => {
  if (!selectedIds.value.length) {
    Message.warning('请先选择策略')
    return
  }
  batchRiskLevel.value = 'medium'
  batchModalVisible.value = true
}

const submitBatchRisk = async () => {
  actionLoading.value = true
  try {
    await batchUpdateRisk(selectedIds.value, batchRiskLevel.value)
    Message.success('批量调整风险等级成功')
    batchModalVisible.value = false
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '批量调整失败'))
  } finally {
    actionLoading.value = false
  }
}

const onSelectionChange = (rowKeys: string[]) => {
  selectedIds.value = rowKeys
}

const onAuditPageChange = (page: number) => {
  auditFilters.value.current_page = page
  loadAudits()
}

onMounted(loadAll)
</script>

<template>
  <section class="space-y-6 p-6">
    <header>
      <h1 class="text-2xl font-semibold text-gray-900">工具池治理</h1>
      <p class="mt-1 text-sm text-gray-500">维护工具治理策略、风险等级与可见性，并审计工具调用记录。</p>
    </header>

    <div class="grid gap-4 md:grid-cols-4">
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">策略总数</p>
        <strong class="text-xl">{{ stats.total }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">启用率</p>
        <strong class="text-xl">{{ enabledRatePercent }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">风险分布</p>
        <div class="mt-1 flex flex-wrap gap-1">
          <a-tag v-for="[risk, count] in riskEntries" :key="risk" :color="riskColor(risk)" size="small">{{ risk }}: {{ count }}</a-tag>
          <span v-if="!riskEntries.length" class="text-gray-400">-</span>
        </div>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">来源分布</p>
        <div class="mt-1 flex flex-wrap gap-1">
          <a-tag v-for="[source, count] in sourceEntries" :key="source" size="small">{{ source }}: {{ count }}</a-tag>
          <span v-if="!sourceEntries.length" class="text-gray-400">-</span>
        </div>
      </article>
    </div>

    <a-tabs v-model:active-key="activeTab" type="rounded" @change="(key: string | number) => key === 'audit' && loadAudits()">
      <a-tab-pane key="policies" title="治理策略">
        <div class="mb-3 flex flex-wrap items-end gap-3">
          <a-input v-model="filters.keyword" placeholder="工具名/ID 关键词" style="width: 200px" allow-clear />
          <a-select v-model="filters.source_type" placeholder="来源类型" style="width: 140px" allow-clear>
            <a-option v-for="s in SOURCE_TYPES" :key="s" :value="s">{{ s }}</a-option>
          </a-select>
          <a-select v-model="filters.risk_level" placeholder="风险等级" style="width: 140px" allow-clear>
            <a-option v-for="r in RISK_LEVELS" :key="r" :value="r">{{ r }}</a-option>
          </a-select>
          <a-select v-model="filters.visibility" placeholder="可见性" style="width: 140px" allow-clear>
            <a-option v-for="v in VISIBILITIES" :key="v" :value="v">{{ v }}</a-option>
          </a-select>
          <a-button :loading="loading" @click="loadPolicies">查询</a-button>
          <a-button :disabled="!selectedIds.length" @click="openBatchRisk">批量改风险</a-button>
          <div class="ml-auto">
            <a-button type="primary" @click="openCreate">新建策略</a-button>
          </div>
        </div>
        <a-spin :loading="loading" class="block">
          <div class="overflow-hidden rounded-lg border bg-white">
            <a-table
              :data="policies"
              :row-key="(record: ToolPolicy) => record.id"
              :row-selection="{ showCheckedAll: true }"
              :selected-keys="selectedIds"
              :pagination="false"
              :bordered="{ wrapper: true, cell: true }"
              @selection-change="onSelectionChange"
            >
              <template #empty>暂无治理策略</template>
              <a-table-column title="工具名" data-index="tool_name">
                <template #cell="{ record }">
                  <span class="font-medium">{{ record.tool_name || '-' }}</span>
                  <p class="text-xs text-gray-400">{{ record.tool_id }}</p>
                </template>
              </a-table-column>
              <a-table-column title="来源类型" data-index="source_type" :width="110" />
              <a-table-column title="风险等级" data-index="risk_level" :width="110">
                <template #cell="{ record }">
                  <a-tag :color="riskColor(record.risk_level)" size="small">{{ record.risk_level }}</a-tag>
                </template>
              </a-table-column>
              <a-table-column title="可见性" data-index="visibility" :width="100" />
              <a-table-column title="允许池" data-index="allowed_pools">
                <template #cell="{ record }">
                  <a-tag v-for="pool in record.allowed_pools" :key="pool" size="small">{{ pool }}</a-tag>
                  <span v-if="!record.allowed_pools?.length" class="text-gray-400">-</span>
                </template>
              </a-table-column>
              <a-table-column title="状态" :width="80">
                <template #cell="{ record }">
                  <a-switch
                    :model-value="record.enabled"
                    :loading="actionLoading"
                    @change="(v: string | number | boolean) => toggleStatus(record, Boolean(v))"
                  />
                </template>
              </a-table-column>
              <a-table-column title="操作" :width="160">
                <template #cell="{ record }">
                  <a-space>
                    <a-button size="mini" @click="openEdit(record)">编辑</a-button>
                    <a-button size="mini" status="danger" @click="remove(record)">删除</a-button>
                  </a-space>
                </template>
              </a-table-column>
            </a-table>
          </div>
        </a-spin>
      </a-tab-pane>

      <a-tab-pane key="audit" title="调用审计">
        <div class="mb-3 flex flex-wrap items-end gap-3">
          <a-input v-model="auditFilters.tool_id" placeholder="工具 ID" style="width: 200px" allow-clear />
          <a-select v-model="auditFilters.status" placeholder="调用状态" style="width: 160px" allow-clear>
            <a-option v-for="s in INVOCATION_STATUSES" :key="s" :value="s">{{ s }}</a-option>
          </a-select>
          <a-date-picker v-model="auditFilters.start_date" placeholder="开始日期" style="width: 180px" />
          <a-date-picker v-model="auditFilters.end_date" placeholder="结束日期" style="width: 180px" />
          <a-button :loading="loading" @click="loadAudits">查询</a-button>
        </div>
        <a-spin :loading="loading" class="block">
          <div class="overflow-hidden rounded-lg border bg-white">
            <table class="w-full text-left text-sm">
              <thead class="bg-gray-50 text-gray-500">
                <tr>
                  <th class="p-3">工具名</th>
                  <th class="p-3">工具 ID</th>
                  <th class="p-3">调用者</th>
                  <th class="p-3">状态</th>
                  <th class="p-3">耗时(ms)</th>
                  <th class="p-3">错误信息</th>
                  <th class="p-3">时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!audits.length">
                  <td class="p-6 text-center text-gray-400" colspan="7">暂无审计日志</td>
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
            @change="onAuditPageChange"
          />
        </div>
      </a-tab-pane>
    </a-tabs>

    <a-modal
      v-model:visible="modalVisible"
      :title="editMode ? '编辑治理策略' : '新建治理策略'"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submit"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item label="工具 ID" field="tool_id">
          <a-input v-model="form.tool_id" placeholder="如 weather_api" :disabled="editMode" />
        </a-form-item>
        <a-form-item label="工具名" field="tool_name">
          <a-input v-model="form.tool_name" placeholder="如 天气查询" />
        </a-form-item>
        <a-form-item label="来源类型" field="source_type">
          <a-select v-model="form.source_type">
            <a-option v-for="s in SOURCE_TYPES" :key="s" :value="s">{{ s }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="风险等级" field="risk_level">
          <a-select v-model="form.risk_level">
            <a-option v-for="r in RISK_LEVELS" :key="r" :value="r">{{ r }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="可见性" field="visibility">
          <a-select v-model="form.visibility">
            <a-option v-for="v in VISIBILITIES" :key="v" :value="v">{{ v }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="允许池" field="allowed_pools">
          <a-select v-model="form.allowed_pools" multiple allow-search allow-create>
            <a-option value="tenant">tenant</a-option>
            <a-option value="system">system</a-option>
            <a-option value="global">global</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="描述" field="description">
          <a-input v-model="form.description" placeholder="可选" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:visible="batchModalVisible"
      title="批量调整风险等级"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submitBatchRisk"
    >
      <p class="mb-3 text-sm text-gray-500">已选 {{ selectedIds.length }} 条策略，将统一调整为以下风险等级：</p>
      <a-select v-model="batchRiskLevel">
        <a-option v-for="r in RISK_LEVELS" :key="r" :value="r">{{ r }}</a-option>
      </a-select>
    </a-modal>
  </section>
</template>
