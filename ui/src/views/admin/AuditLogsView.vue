<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  getAuditLogOverview,
  listAuditLogs,
  type AuditLog,
  type AuditLogOverviewData,
} from '@/services/admin-audit-logs'
import { getErrorMessage } from '@/utils/error'
import { semanticLabel } from '@/utils/semantic-labels'

const { t } = useI18n()

const listLoading = ref(false)
const overviewLoading = ref(false)
const logs = ref<AuditLog[]>([])
const total = ref(0)
const overview = ref<AuditLogOverviewData | null>(null)
const detailTarget = ref<AuditLog | null>(null)
const activeRange = ref('30d')

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
  // 邮箱/可读名原样展示；uuid 或超长内部标识截断（配合 tooltip 显示完整值）
  if (id.includes('@')) return id
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
  upsert: 'admin.auditLogs.actionUpsert',
  file_delete: 'admin.auditLogs.actionFileDelete',
  bind_superior: 'admin.auditLogs.actionBindSuperior',
  unbind_superior: 'admin.auditLogs.actionUnbindSuperior',
  close_order: 'admin.auditLogs.actionCloseOrder',
  import_mcp_json: 'admin.auditLogs.actionImportMcpJson',
  import_url: 'admin.auditLogs.actionImportUrl',
  import_json: 'admin.auditLogs.actionImportJson',
  publish: 'admin.auditLogs.actionPublish',
  unpublish: 'admin.auditLogs.actionUnpublish',
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
  storage_file: 'admin.auditLogs.resourceStorageFile',
  storage: 'admin.auditLogs.resourceStorageFile',
  billing_config: 'admin.auditLogs.resourceBillingConfig',
  distribution_relation: 'admin.auditLogs.resourceDistributionRelation',
  purchase_order: 'admin.auditLogs.resourcePurchaseOrder',
  skill_package: 'admin.auditLogs.resourceSkill',
  mcp_provider: 'admin.auditLogs.resourceMcp',
  knowledge_base: 'admin.auditLogs.resourceKnowledgeBase',
  system_prompt: 'admin.auditLogs.resourceSystemPrompt',
  knowledge_document: 'admin.auditLogs.resourceKnowledgeDocument',
  upload_file: 'admin.auditLogs.resourceUploadFile',
  os_file: 'admin.auditLogs.resourceOsFile',
  schedule_task: 'admin.auditLogs.resourceScheduleTask',
  external_data_source: 'admin.auditLogs.resourceExternalDataSource',
  conversation: 'admin.auditLogs.resourceConversation',
  memory: 'admin.auditLogs.resourceMemory',
  dataset: 'admin.auditLogs.resourceDataset',
}

const actionLabel = (action: string | null | undefined): string => {
  if (!action) return '-'
  const key = ACTION_LABELS[action]
  if (key) return t(key)
  // 点分复合 action：storage.file_delete → 资源·动作
  if (action.includes('.')) {
    const dotIndex = action.indexOf('.')
    const prefix = action.slice(0, dotIndex)
    const suffix = action.slice(dotIndex + 1)
    const prefixKey = RESOURCE_TYPE_LABELS[prefix]
    const suffixKey = ACTION_LABELS[suffix]
    if (prefixKey && suffixKey) return `${t(prefixKey)} · ${t(suffixKey)}`
    if (suffixKey) return t(suffixKey)
    if (prefixKey) return t(prefixKey)
  }
  // 兜底：语义字典
  return semanticLabel('action', action, action)
}

const resourceTypeLabel = (resourceType: string | null | undefined): string => {
  if (!resourceType) return t('admin.auditLogs.unknownResource')
  const key = RESOURCE_TYPE_LABELS[resourceType]
  if (key) return t(key)
  return semanticLabel('resource_type', resourceType, resourceType)
}

const actionColor = (action: string | null | undefined): string => {
  if (!action) return 'gray'
  const colors: Record<string, string> = {
    create: 'green',
    update: 'arcoblue',
    disable: 'orange',
    delete: 'red',
  }
  return colors[action] || 'gray'
}

const actionOptions = computed(() => [
  { label: t('admin.auditLogs.allActions'), value: '' },
  { label: t('admin.auditLogs.actionCreate'), value: 'create' },
  { label: t('admin.auditLogs.actionUpdate'), value: 'update' },
  { label: t('admin.auditLogs.actionDisable'), value: 'disable' },
  { label: t('admin.auditLogs.actionEnable'), value: 'enable' },
  { label: t('admin.auditLogs.actionDelete'), value: 'delete' },
  { label: t('admin.auditLogs.actionResetPassword'), value: 'reset_password' },
  { label: t('admin.auditLogs.actionRevokeSessions'), value: 'revoke_sessions' },
  { label: t('admin.auditLogs.actionAssign'), value: 'assign' },
  { label: t('admin.auditLogs.actionRevoke'), value: 'revoke' },
  { label: t('admin.auditLogs.actionGenerate'), value: 'generate' },
  { label: t('admin.auditLogs.actionSetStatus'), value: 'set_status' },
  { label: t('admin.auditLogs.actionSync'), value: 'sync' },
  { label: t('admin.auditLogs.actionRollback'), value: 'rollback' },
  { label: t('admin.auditLogs.actionConfirm'), value: 'confirm' },
  { label: t('admin.auditLogs.actionCancel'), value: 'cancel' },
  { label: t('admin.auditLogs.actionToolInvocation'), value: 'tool_invocation' },
  { label: t('admin.auditLogs.actionPolicyApply'), value: 'policy_change_apply' },
  { label: t('admin.auditLogs.actionPolicyRollback'), value: 'policy_change_rollback' },
])

const rangeOptions = computed(() => [
  { key: '7d', label: t('admin.auditLogs.range7d') },
  { key: '30d', label: t('admin.auditLogs.range30d') },
  { key: '90d', label: t('admin.auditLogs.range90d') },
  { key: '180d', label: t('admin.auditLogs.range180d') },
  { key: 'all', label: t('admin.auditLogs.rangeAll') },
])

const RANGE_DAYS: Record<string, number | null> = {
  '7d': 7,
  '30d': 30,
  '90d': 90,
  '180d': 180,
  all: null,
}

const rangeToSeconds = (range: string): { start?: number; end?: number } => {
  const days = RANGE_DAYS[range]
  if (days == null) return {}
  const now = Math.floor(Date.now() / 1000)
  return { start: now - days * 86400, end: now }
}

const pad = (value: number) => String(value).padStart(2, '0')

const toInputValue = (seconds: number | undefined): string => {
  if (!seconds) return ''
  const date = new Date(seconds * 1000)
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

const initialRange = rangeToSeconds(activeRange.value)

const filters = ref({
  action: '',
  resource_type: '',
  start: toInputValue(initialRange.start),
  end: toInputValue(initialRange.end),
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

const formatCount = (value: number | undefined | null) =>
  value == null ? '--' : Number(value).toLocaleString()

const loadLogs = async () => {
  listLoading.value = true
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
    listLoading.value = false
  }
}

const loadOverview = async () => {
  overviewLoading.value = true
  try {
    const res = await getAuditLogOverview({
      action: filters.value.action || undefined,
      resource_type: filters.value.resource_type || undefined,
      start_time: toUnix(filters.value.start),
      end_time: toUnix(filters.value.end),
    })
    overview.value = res.data
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.auditLogs.loadFailed')))
  } finally {
    overviewLoading.value = false
  }
}

const reloadAll = async () => {
  await Promise.all([loadOverview(), loadLogs()])
}

const handleRangeChange = (key: string) => {
  if (key === activeRange.value) return
  activeRange.value = key
  const range = rangeToSeconds(key)
  filters.value.start = toInputValue(range.start)
  filters.value.end = toInputValue(range.end)
  filters.value.current_page = 1
  void reloadAll()
}

const handleSearch = async () => {
  filters.value.current_page = 1
  await reloadAll()
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

onMounted(() => {
  void reloadAll()
})

const overviewData = computed<AuditLogOverviewData>(() => {
  const data = overview.value
  return data
    ? data
    : { total: 0, by_action: [], by_resource_type: [], trend: [], top_admins: [] }
})

const activeAdminCount = computed(() => (overview.value ? overview.value.top_admins.length : 0))

const trendValues = computed(() => overviewData.value.trend.map((point) => point.count))

const trendTotal = computed(() => trendValues.value.reduce((sum, value) => sum + value, 0))

const trendPeak = computed(() => {
  if (!trendValues.value.length) return 0
  return Math.max(...trendValues.value)
})

type KpiCard = {
  key: string
  label: string
  hint: string
  value: string
  iconBg: string
  iconPaths: string[]
}

const kpiCards = computed<KpiCard[]>(() => [
  {
    key: 'total',
    label: t('admin.auditLogs.totalCount'),
    hint: t('admin.auditLogs.totalCountHint'),
    value: formatCount(overviewData.value.total),
    iconBg: 'bg-sky-50 text-sky-600',
    iconPaths: ['M4 4h7v7H4z', 'M13 4h7v7h-7z', 'M4 13h7v7H4z', 'M13 13h7v7h-7z'],
  },
  {
    key: 'admins',
    label: t('admin.auditLogs.activeAdmins'),
    hint: t('admin.auditLogs.activeAdminsHint'),
    value: formatCount(activeAdminCount.value),
    iconBg: 'bg-violet-50 text-violet-600',
    iconPaths: ['M12 21s-7-4.35-9.5-8A5.5 5.5 0 0 1 12 6.5 5.5 5.5 0 0 1 21.5 13c-2.5 3.65-9.5 8-9.5 8z', 'M9.5 10.5h.01M14.5 10.5h.01'],
  },
  {
    key: 'trendTotal',
    label: t('admin.auditLogs.trendTotal'),
    hint: t('admin.auditLogs.trendTotalHint'),
    value: formatCount(trendTotal.value),
    iconBg: 'bg-emerald-50 text-emerald-600',
    iconPaths: ['M3 3v18h18', 'm7 14 4-4 3 3 5-6'],
  },
  {
    key: 'peak',
    label: t('admin.auditLogs.trendPeak'),
    hint: t('admin.auditLogs.trendPeakHint'),
    value: formatCount(trendPeak.value),
    iconBg: 'bg-amber-50 text-amber-600',
    iconPaths: ['M4 4h7v7H4z', 'M13 4h7v7h-7z', 'M4 13h7v7H4z', 'M13 13h7v7h-7z', 'M9.5 9.5v.01', 'M16.5 16.5v.01'],
  },
])

const TREND_W = 640
const TREND_H = 120
const TREND_PAD_X = 12
const TREND_PAD_BOTTOM = 18

type TrendBar = {
  x: number
  y: number
  width: number
  height: number
  count: number
  dateLabel: string
  leftPercent: number
}

const trendBars = computed<TrendBar[]>(() => {
  const points = overviewData.value.trend
  if (!points.length) return []
  const plotWidth = TREND_W - TREND_PAD_X * 2
  const plotHeight = TREND_H - TREND_PAD_BOTTOM
  const slotWidth = plotWidth / points.length
  const barWidth = Math.max(Math.min(slotWidth * 0.62, 36), 2)
  const max = trendValues.value.length ? Math.max(...trendValues.value) : 0
  const hOf = (value: number) => (max > 0 ? (value / max) * (plotHeight - 4) : 0)
  return points.map((point, index) => {
    const date = new Date(point.timestamp * 1000)
    const dateLabel = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(
      date.getDate(),
    ).padStart(2, '0')}`
    const count = point.count || 0
    const x = TREND_PAD_X + slotWidth * index + (slotWidth - barWidth) / 2
    const height = hOf(count)
    return {
      x,
      y: plotHeight - height,
      width: barWidth,
      height,
      count,
      dateLabel,
      leftPercent: ((x + barWidth / 2) / TREND_W) * 100,
    }
  })
})

const trendLabels = computed(() => {
  const format = (timestamp: number) => {
    const date = new Date(timestamp * 1000)
    return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
  }
  return overviewData.value.trend.map((point, index) => {
    const points = overviewData.value.trend
    const plotWidth = TREND_W - TREND_PAD_X * 2
    const slotWidth = plotWidth / Math.max(points.length, 1)
    return {
      x: TREND_PAD_X + slotWidth * index + slotWidth / 2,
      label: format(point.timestamp),
    }
  })
})

// 趋势图互动：hover 柱显示日期与数量浮层
const hoveredTrendIndex = ref<number | null>(null)

const hoveredTrend = computed(() => {
  if (hoveredTrendIndex.value == null) return null
  const bar = trendBars.value[hoveredTrendIndex.value]
  if (!bar) return null
  return bar
})

const barColors = [
  'bg-sky-500',
  'bg-indigo-500',
  'bg-emerald-500',
  'bg-amber-500',
  'bg-violet-500',
  'bg-rose-500',
  'bg-cyan-500',
  'bg-orange-500',
]

type DistRow = {
  name: string
  label: string
  count: number
  percent: number
  color: string
}

const buildDistRows = (
  items: Array<{ name: string; count: number }>,
  labelFor: (name: string) => string,
  limit: number,
): DistRow[] => {
  const sorted = [...items].sort((a, b) => b.count - a.count).slice(0, limit)
  const max = sorted.length ? sorted[0].count : 0
  return sorted.map((item, index) => ({
    name: item.name,
    label: labelFor(item.name),
    count: item.count,
    percent: max > 0 ? Math.max((item.count / max) * 100, 2) : 0,
    color: barColors[index % barColors.length],
  }))
}

const DISTRIBUTION_LIMIT = 6

const actionRows = computed<DistRow[]>(() =>
  buildDistRows(overviewData.value.by_action, actionLabel, DISTRIBUTION_LIMIT),
)

const resourceRows = computed<DistRow[]>(() =>
  buildDistRows(overviewData.value.by_resource_type, resourceTypeLabel, DISTRIBUTION_LIMIT),
)

const topAdminRows = computed<DistRow[]>(() =>
  buildDistRows(overviewData.value.top_admins, (name) => truncateId(name) || name, 6),
)
</script>

<template>
  <section class="space-y-6 p-6">
    <header class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight text-slate-900">
          {{ t('admin.auditLogs.title') }}
        </h1>
        <p class="mt-1 text-sm leading-6 text-slate-500">
          {{ t('admin.auditLogs.description') }}
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <span
          class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-100 p-1 shadow-sm"
          role="group"
          :aria-label="t('admin.auditLogs.timeRange')"
        >
          <button
            v-for="range in rangeOptions"
            :key="range.key"
            type="button"
            class="rounded-md px-3 py-1.5 text-sm font-medium transition"
            :class="
              activeRange === range.key
                ? 'bg-white text-sky-700 shadow-sm'
                : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
            "
            :aria-pressed="activeRange === range.key"
            @click="handleRangeChange(range.key)"
          >
            {{ range.label }}
          </button>
        </span>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="overviewLoading || listLoading"
          @click="reloadAll"
        >
          <svg
            class="h-4 w-4"
            :class="overviewLoading || listLoading ? 'animate-spin' : ''"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M21 12a9 9 0 1 1-2.64-6.36" />
            <path d="M21 3v6h-6" />
          </svg>
          {{ t('admin.auditLogs.refresh') }}
        </button>
      </div>
    </header>

    <section
      class="grid gap-4 md:grid-cols-2 xl:grid-cols-4"
      aria-label="overview-section"
    >
      <article
        v-for="card in kpiCards"
        :key="card.key"
        class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-sm font-medium text-slate-500">{{ card.label }}</p>
            <div
              v-if="overviewLoading && !overview"
              class="mt-2 h-8 w-20 animate-pulse rounded bg-slate-100"
              aria-hidden="true"
            />
            <strong v-else class="mt-2 block text-2xl font-semibold tracking-tight text-slate-900">
              {{ card.value }}
            </strong>
          </div>
          <span
            class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
            :class="card.iconBg"
          >
            <svg
              class="h-4 w-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path v-for="(path, index) in card.iconPaths" :key="index" :d="path" />
            </svg>
          </span>
        </div>
        <p class="mt-3 text-xs leading-5 text-slate-400">{{ card.hint }}</p>
      </article>
    </section>

    <section
      class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm"
      aria-label="trend-section"
    >
      <header class="flex items-start justify-between gap-4">
        <div>
          <h2 class="text-base font-semibold text-slate-900">
            {{ t('admin.auditLogs.trendTitle') }}
          </h2>
          <p class="mt-0.5 text-xs text-slate-400">
            {{ t('admin.auditLogs.trendDescription') }}
          </p>
        </div>
        <span class="flex items-center gap-1.5 text-xs text-slate-500">
          <span class="inline-block h-2 w-2 rounded-full bg-sky-500" />
          {{ t('admin.auditLogs.trendTotal') }}
        </span>
      </header>
      <div
        v-if="overviewLoading && !trendValues.length"
        class="mt-4 h-40 animate-pulse rounded-lg bg-slate-100"
        aria-hidden="true"
      />
      <div v-else-if="!trendValues.length" class="mt-4 py-10 text-center text-sm text-slate-400">
        {{ t('admin.auditLogs.noData') }}
      </div>
      <div v-else class="mt-3 grid gap-6 lg:grid-cols-[1fr_auto] lg:items-center">
        <div class="min-w-0">
          <div class="relative">
            <div
              v-if="hoveredTrend"
              class="pointer-events-none absolute z-10 -translate-x-1/2 whitespace-nowrap rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 shadow-sm"
              :style="{ left: `${hoveredTrend.leftPercent}%`, top: '0' }"
            >
              {{ hoveredTrend.dateLabel }} · {{ formatCount(hoveredTrend.count) }}
            </div>
            <svg
              viewBox="0 0 640 120"
              preserveAspectRatio="xMidYMid meet"
              class="block w-full text-slate-200"
              style="aspect-ratio: 640 / 120; height: auto;"
            >
              <line x1="12" y1="8" x2="628" y2="8" stroke="currentColor" stroke-width="1" />
              <line x1="12" y1="50" x2="628" y2="50" stroke="currentColor" stroke-width="1" />
              <line x1="12" y1="102" x2="628" y2="102" stroke="currentColor" stroke-width="1" />
              <template v-for="(bar, index) in trendBars" :key="index">
                <rect
                  :x="bar.x"
                  :y="bar.y"
                  :width="bar.width"
                  :height="bar.height"
                  rx="2"
                  fill="#0ea5e9"
                  class="cursor-pointer"
                  @mouseenter="hoveredTrendIndex = index"
                  @mouseleave="hoveredTrendIndex = null"
                />
                <rect
                  :x="bar.x - 3"
                  :y="bar.y - 3"
                  :width="bar.width + 6"
                  :height="Math.max(bar.height + 6, 6)"
                  fill="transparent"
                  class="cursor-pointer"
                  @mouseenter="hoveredTrendIndex = index"
                  @mouseleave="hoveredTrendIndex = null"
                />
              </template>
            </svg>
          </div>
          <div class="relative h-4 text-[10px] text-slate-400">
            <span
              v-for="label in trendLabels"
              :key="label.x"
              class="absolute -translate-x-1/2"
              :style="{ left: `${(label.x / TREND_W) * 100}%` }"
            >
              {{ label.label }}
            </span>
          </div>
        </div>
        <dl class="grid grid-cols-2 gap-3 lg:grid-cols-1">
          <div class="rounded-lg bg-slate-50 px-4 py-3">
            <dt class="text-xs text-slate-500">{{ t('admin.auditLogs.trendTotal') }}</dt>
            <dd class="mt-1 text-lg font-semibold text-slate-900">
              {{ formatCount(trendTotal) }}
            </dd>
          </div>
          <div class="rounded-lg bg-slate-50 px-4 py-3">
            <dt class="text-xs text-slate-500">{{ t('admin.auditLogs.trendPeak') }}</dt>
            <dd class="mt-1 text-lg font-semibold text-slate-900">
              {{ formatCount(trendPeak) }}
            </dd>
          </div>
        </dl>
      </div>
    </section>

    <section
      class="grid gap-4 xl:grid-cols-3"
      aria-label="distribution-section"
    >
      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <header class="flex items-center justify-between gap-3">
          <div>
            <h2 class="text-base font-semibold text-slate-900">
              {{ t('admin.auditLogs.actionDistribution') }}
            </h2>
            <p class="mt-0.5 text-xs text-slate-400">
              {{ t('admin.auditLogs.actionDistributionDesc') }}
            </p>
          </div>
          <span
            class="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600"
          >
            {{ actionRows.length }}
          </span>
        </header>
        <ul v-if="actionRows.length" class="mt-4 space-y-4">
          <li v-for="row in actionRows" :key="row.name">
            <div class="flex items-center justify-between gap-3">
              <span class="truncate text-sm font-medium text-slate-700" :title="row.name">
                {{ row.label }}
              </span>
              <span class="text-sm tabular-nums text-slate-500">{{ row.count }}</span>
            </div>
            <div class="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-slate-100">
              <div
                class="h-full rounded-full"
                :class="row.color"
                :style="{ width: `${row.percent}%` }"
              />
            </div>
          </li>
        </ul>
        <p v-else class="mt-4 text-sm text-slate-400">
          {{ t('admin.auditLogs.noData') }}
        </p>
      </article>

      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <header class="flex items-center justify-between gap-3">
          <div>
            <h2 class="text-base font-semibold text-slate-900">
              {{ t('admin.auditLogs.resourceDistribution') }}
            </h2>
            <p class="mt-0.5 text-xs text-slate-400">
              {{ t('admin.auditLogs.resourceDistributionDesc') }}
            </p>
          </div>
          <span
            class="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600"
          >
            {{ resourceRows.length }}
          </span>
        </header>
        <ul v-if="resourceRows.length" class="mt-4 space-y-4">
          <li v-for="row in resourceRows" :key="row.name">
            <div class="flex items-center justify-between gap-3">
              <span class="truncate text-sm font-medium text-slate-700" :title="row.name">
                {{ row.label }}
              </span>
              <span class="text-sm tabular-nums text-slate-500">{{ row.count }}</span>
            </div>
            <div class="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-slate-100">
              <div
                class="h-full rounded-full"
                :class="row.color"
                :style="{ width: `${row.percent}%` }"
              />
            </div>
          </li>
        </ul>
        <p v-else class="mt-4 text-sm text-slate-400">
          {{ t('admin.auditLogs.noData') }}
        </p>
      </article>

      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <header class="flex items-center justify-between gap-3">
          <div>
            <h2 class="text-base font-semibold text-slate-900">
              {{ t('admin.auditLogs.topAdmins') }}
            </h2>
            <p class="mt-0.5 text-xs text-slate-400">
              {{ t('admin.auditLogs.topAdminsDesc') }}
            </p>
          </div>
          <span
            class="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600"
          >
            {{ topAdminRows.length }}
          </span>
        </header>
        <ul v-if="topAdminRows.length" class="mt-4 space-y-4">
          <li v-for="row in topAdminRows" :key="row.name">
            <div class="flex items-center justify-between gap-3">
              <span class="truncate text-sm font-medium text-slate-700" :title="row.name">
                {{ row.label }}
              </span>
              <span class="text-sm tabular-nums text-slate-500">{{ row.count }}</span>
            </div>
            <div class="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-slate-100">
              <div
                class="h-full rounded-full"
                :class="row.color"
                :style="{ width: `${row.percent}%` }"
              />
            </div>
          </li>
        </ul>
        <p v-else class="mt-4 text-sm text-slate-400">
          {{ t('admin.auditLogs.noData') }}
        </p>
      </article>
    </section>

    <section class="space-y-4" aria-label="list-section">
      <header class="flex items-end justify-between gap-4">
        <div>
          <h2 class="text-lg font-semibold text-slate-900">
            {{ t('admin.auditLogs.listTitle') }}
          </h2>
          <p class="mt-1 text-sm text-slate-500">
            {{ t('admin.auditLogs.listDescription') }}
          </p>
        </div>
        <span
          v-if="total"
          class="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600"
        >
          {{ formatCount(total) }}
        </span>
      </header>

      <div class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div class="grid gap-3 md:grid-cols-4">
          <a-select
            v-model="filters.action"
            :options="actionOptions"
            :placeholder="t('admin.auditLogs.actionTypePlaceholder')"
          />
          <a-input
            v-model="filters.resource_type"
            :placeholder="t('admin.auditLogs.resourceTypePlaceholder')"
            allow-clear
          />
          <input
            v-model="filters.start"
            type="datetime-local"
            class="h-8 w-full rounded-lg border border-slate-200 bg-white px-2 text-sm text-slate-700 outline-none transition focus:border-sky-400"
            :placeholder="t('admin.auditLogs.startTimePlaceholder')"
          />
          <input
            v-model="filters.end"
            type="datetime-local"
            class="h-8 w-full rounded-lg border border-slate-200 bg-white px-2 text-sm text-slate-700 outline-none transition focus:border-sky-400"
            :placeholder="t('admin.auditLogs.endTimePlaceholder')"
          />
        </div>
        <a-button
          class="mt-3"
          type="primary"
          :loading="listLoading || overviewLoading"
          @click="handleSearch"
        >
          {{ t('admin.auditLogs.search') }}
        </a-button>
      </div>

      <article class="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <div v-if="listLoading && !logs.length" class="p-8 text-center text-sm text-slate-400">
          {{ t('admin.auditLogs.loading') }}
        </div>
        <div v-else-if="!logs.length" class="p-8 text-center text-sm text-slate-400">
          {{ t('admin.auditLogs.noData') }}
        </div>
        <template v-else>
          <div class="overflow-x-auto">
            <table class="w-full text-left text-sm">
              <thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th class="px-4 py-3 font-medium">{{ t('admin.auditLogs.time') }}</th>
                  <th class="px-4 py-3 font-medium">{{ t('admin.auditLogs.admin') }}</th>
                  <th class="px-4 py-3 font-medium">{{ t('admin.auditLogs.action') }}</th>
                  <th class="px-4 py-3 font-medium">{{ t('admin.auditLogs.resourceType') }}</th>
                  <th class="px-4 py-3 font-medium">{{ t('admin.auditLogs.resourceId') }}</th>
                  <th class="px-4 py-3 font-medium">IP</th>
                  <th class="px-4 py-3 font-medium">{{ t('admin.auditLogs.detail') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="log in logs" :key="log.id" class="border-t border-slate-100">
                  <td class="whitespace-nowrap px-4 py-3 tabular-nums text-slate-500">
                    {{ formatTime(log.created_at) }}
                  </td>
                  <td class="px-4 py-3 text-slate-700">
                    <span v-if="log.admin_user_name" class="font-medium">{{ log.admin_user_name }}</span>
                    <span v-else-if="log.account_name">{{ log.account_name }}</span>
                    <a-tooltip
                      v-else-if="log.admin_user_id"
                      :content="log.admin_user_id"
                      position="top"
                      mini
                    >
                      <span class="cursor-help font-mono text-slate-400">{{ truncateId(log.admin_user_id) }}</span>
                    </a-tooltip>
                    <span v-else class="text-slate-400">-</span>
                  </td>
                  <td class="px-4 py-3">
                    <a-tag size="small" :color="actionColor(log.action)">
                      {{ actionLabel(log.action) }}
                    </a-tag>
                  </td>
                  <td class="px-4 py-3">
                    <a-tag
                      v-if="log.resource_type"
                      size="small"
                      :color="getResourceTypeColor(log.resource_type)"
                    >
                      {{ resourceTypeLabel(log.resource_type) }}
                    </a-tag>
                    <a-tag v-else size="small" color="gray">
                      {{ t('admin.auditLogs.unknownResource') }}
                    </a-tag>
                  </td>
                  <td class="px-4 py-3 font-mono text-xs">
                    <a-tooltip v-if="log.resource_id" :content="log.resource_id" position="top" mini>
                      <span class="text-slate-600">{{ truncateId(log.resource_id) }}</span>
                    </a-tooltip>
                    <span v-else class="text-slate-400">-</span>
                  </td>
                  <td class="px-4 py-3 text-xs text-slate-500">{{ log.ip || '-' }}</td>
                  <td class="whitespace-nowrap px-4 py-3">
                    <button
                      type="button"
                      class="rounded-md px-2.5 py-1 text-xs font-medium text-sky-600 transition hover:bg-sky-50"
                      @click="openDetail(log)"
                    >
                      {{ t('admin.auditLogs.view') }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <footer class="flex justify-end border-t border-slate-100 px-4 py-3">
            <a-pagination
              :total="total"
              :current="filters.current_page"
              :page-size="filters.page_size"
              show-total
              show-page-size
              @change="onPageChange"
              @page-size-change="onPageSizeChange"
            />
          </footer>
        </template>
      </article>
    </section>

    <a-modal
      :visible="!!detailTarget"
      :title="t('admin.auditLogs.detailTitle')"
      :width="640"
      :footer="false"
      @cancel="detailTarget = null"
    >
      <div v-if="detailTarget" class="space-y-4">
        <div class="grid grid-cols-2 gap-3 text-sm">
          <div>
            <span class="text-slate-500">{{ t('admin.auditLogs.admin') }}：</span>
            <template v-if="detailTarget.admin_user_name || detailTarget.account_name">
              {{ detailTarget.admin_user_name || detailTarget.account_name }}
            </template>
            <a-tooltip
              v-else-if="detailTarget.admin_user_id"
              :content="detailTarget.admin_user_id"
              position="top"
              mini
            >
              <span class="cursor-help font-mono">{{ truncateId(detailTarget.admin_user_id) }}</span>
            </a-tooltip>
            <span v-else>-</span>
          </div>
          <div>
            <span class="text-slate-500">{{ t('admin.auditLogs.actionLabel') }}</span>
            <a-tag size="small" :color="actionColor(detailTarget.action)">
              {{ actionLabel(detailTarget.action) }}
            </a-tag>
          </div>
          <div>
            <span class="text-slate-500">{{ t('admin.auditLogs.resourceTypeLabel') }}</span>
            <a-tag size="small" :color="getResourceTypeColor(detailTarget.resource_type)">
              {{ resourceTypeLabel(detailTarget.resource_type) }}
            </a-tag>
          </div>
          <div>
            <span class="text-slate-500">{{ t('admin.auditLogs.resourceIdLabel') }}</span>
            {{ detailTarget.resource_id || '-' }}
          </div>
          <div>
            <span class="text-slate-500">{{ t('admin.auditLogs.ipLabel') }}</span>
            {{ detailTarget.ip || '-' }}
          </div>
          <div>
            <span class="text-slate-500">{{ t('admin.auditLogs.time') }}：</span>
            {{ formatTime(detailTarget.created_at) }}
          </div>
          <div class="col-span-2">
            <span class="text-slate-500">{{ t('admin.auditLogs.userAgentLabel') }}</span>
            {{ detailTarget.user_agent || '-' }}
          </div>
        </div>
        <div>
          <p class="mb-1 text-sm font-medium text-slate-700">{{ t('admin.auditLogs.beforeChange') }}</p>
          <pre class="max-h-48 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600">{{ stringify(detailTarget.before_data) }}</pre>
        </div>
        <div>
          <p class="mb-1 text-sm font-medium text-slate-700">{{ t('admin.auditLogs.afterChange') }}</p>
          <pre class="max-h-48 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600">{{ stringify(detailTarget.after_data) }}</pre>
        </div>
      </div>
    </a-modal>
  </section>
</template>
