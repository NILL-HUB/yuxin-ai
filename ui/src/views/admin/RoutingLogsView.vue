<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import {
  getRoutingLogDistribution,
  getRoutingLogStats,
  getRoutingLogTrend,
  listAdminRoutingLogs,
} from '@/services/admin-routing-logs'
import { createAdminRoutingQualityFeedback } from '@/services/admin-routing-quality'
import type {
  AdminRoutingLogRecord,
  RoutingLogDistributionItem,
  RoutingLogStatsOverview,
  RoutingLogTrendPoint,
} from '@/models/admin-routing-log'
import { getErrorMessage } from '@/utils/error'
import { formatTimestampLong } from '@/utils/time-formatter'
import {
  hasSemantic,
  isUuidLike,
  semanticHint,
  semanticLabel,
  truncateId,
} from '@/utils/semantic-labels'

type DistributionRow = RoutingLogDistributionItem & { dimension: string }

const { t } = useI18n()

const listLoading = ref(false)
const overviewLoading = ref(false)
const logs = ref<AdminRoutingLogRecord[]>([])
const totalRecord = ref(0)

const stats = ref<RoutingLogStatsOverview | null>(null)
const trend = ref<RoutingLogTrendPoint[]>([])
const distributionCache = ref<Record<string, DistributionRow[]>>({})
const overviewRange = ref('30d')
const activeDistribution = ref('execution_mode')
const requestToken = ref(0)

const emptyStats: RoutingLogStatsOverview = {
  total_count: 0,
  success_count: 0,
  fallback_count: 0,
  success_rate: 0,
  fallback_rate: 0,
  total_credits: 0,
  avg_latency_ms: 0,
  agent_pool_hit_rate: 0,
  tool_pool_hit_rate: 0,
  by_status: {},
}

const filters = ref({
  current_page: 1,
  page_size: 20,
  account_id: '',
  status: '',
  invoke_from: '',
  agent_id: '',
  tool_name: '',
  model_id: '',
  start_at: '',
  end_at: '',
})

const searchForm = ref({
  account_id: '',
  status: '',
  invoke_from: '',
  agent_id: '',
  tool_name: '',
  model_id: '',
})

const detailLog = ref<AdminRoutingLogRecord | null>(null)
const detailVisible = ref(false)
const feedbackTarget = ref<AdminRoutingLogRecord | null>(null)
const feedbackForm = ref({
  rating: 5,
  accuracy: 5,
  latency: 5,
  cost: 5,
  safety: 5,
  completeness: 5,
  comment: '',
})

const rangeOptions = computed(() => [
  { key: '7d', label: t('admin.routingLogs.range7d') },
  { key: '30d', label: t('admin.routingLogs.range30d') },
  { key: '90d', label: t('admin.routingLogs.range90d') },
  { key: '180d', label: t('admin.routingLogs.range180d') },
  { key: 'all', label: t('admin.routingLogs.rangeAll') },
])

const statusOptions = computed(() => [
  { key: '', label: t('admin.routingLogs.statusAll') },
  { key: 'success', label: t('admin.routingLogs.statusSuccess') },
  { key: 'fallback', label: t('admin.routingLogs.statusFallback') },
  { key: 'failed', label: t('admin.routingLogs.statusFailed') },
  { key: 'error', label: t('admin.routingLogs.statusError') },
  { key: 'pending', label: t('admin.routingLogs.statusPending') },
])

const invokeFromOptions = computed(() => [
  { key: '', label: t('admin.routingLogs.invokeAll') },
  { key: 'assistant_agent', label: t('admin.routingLogs.sourceAssistantAgent') },
  { key: 'web_app', label: t('admin.routingLogs.sourceWebApp') },
  { key: 'debugger', label: t('admin.routingLogs.sourceDebugger') },
  { key: 'schedule', label: t('admin.routingLogs.sourceSchedule') },
])

const distributionOptions = computed(() => [
  { key: 'execution_mode', label: t('admin.routingLogs.executionMode') },
  { key: 'intent', label: t('admin.routingLogs.intent') },
  { key: 'model_tier', label: t('admin.routingLogs.modelTier') },
])

const rangeDays: Record<string, number | null> = {
  '7d': 7,
  '30d': 30,
  '90d': 90,
  '180d': 180,
  all: null,
}

// 趋势标题随所选时间范围动态化（避免"7 日趋势"标题与 30 天窗口错配）
const trendTitle = computed(() => {
  const rangeKey = overviewRange.value
  const labelMap: Record<string, string> = {
    '7d': t('admin.routingLogs.range7d'),
    '30d': t('admin.routingLogs.range30d'),
    '90d': t('admin.routingLogs.range90d'),
    '180d': t('admin.routingLogs.range180d'),
    all: t('admin.routingLogs.trendAllLabel'),
  }
  return t('admin.routingLogs.trendTitleTemplate', {
    range: labelMap[rangeKey] || labelMap['30d'],
  })
})

const rangeParams = (range: string): { start_at?: string; end_at?: string } | undefined => {
  const days = rangeDays[range]
  if (days == null) return undefined
  const now = Math.floor(Date.now() / 1000)
  return { start_at: String(now - days * 86400), end_at: String(now) }
}

const statusTagClass = (status: string) => {
  switch (status) {
    case 'success':
      return 'bg-emerald-50 text-emerald-700 ring-emerald-200'
    case 'fallback':
      return 'bg-orange-50 text-orange-700 ring-orange-200'
    case 'failed':
      return 'bg-red-50 text-red-700 ring-red-200'
    case 'error':
      return 'bg-red-50 text-red-700 ring-red-200'
    case 'pending':
      return 'bg-gray-100 text-gray-600 ring-gray-200'
    default:
      return 'bg-slate-100 text-slate-600 ring-slate-200'
  }
}

const statusLabel = (status: string) => {
  switch (status) {
    case 'success':
      return t('admin.routingLogs.statusSuccess')
    case 'fallback':
      return t('admin.routingLogs.statusFallback')
    case 'failed':
      return t('admin.routingLogs.statusFailed')
    case 'error':
      return t('admin.routingLogs.statusError')
    case 'pending':
      return t('admin.routingLogs.statusPending')
    default:
      return status
  }
}

const invokeFromLabel = (source: string | undefined) => {
  switch (source) {
    case 'assistant_agent':
      return t('admin.routingLogs.sourceAssistantAgent')
    case 'web_app':
      return t('admin.routingLogs.sourceWebApp')
    case 'debugger':
      return t('admin.routingLogs.sourceDebugger')
    case 'schedule':
      return t('admin.routingLogs.sourceSchedule')
    default:
      return '—'
  }
}

const costPolicyLabel = (allowed: unknown) => {
  if (allowed === true) return t('admin.routingLogs.costAllowed')
  if (allowed === false) return t('admin.routingLogs.costDenied')
  return '—'
}

const formatCount = (value: number | undefined | null) =>
  value == null ? '--' : Number(value).toLocaleString()

const formatRate = (value: number | undefined | null) => {
  if (value == null || Number.isNaN(Number(value))) return '--'
  return `${(Number(value) * 100).toFixed(1)}%`
}

const formatLatency = (value: number | undefined | null) =>
  value == null ? '--' : `${Math.round(Number(value))} ms`

const formatNumber = (value: number | undefined | null) =>
  value == null ? '--' : Math.round(Number(value)).toLocaleString()

const displayCost = (log: { cost_summary?: Record<string, unknown> | null } | null) => {
  const cs = log?.cost_summary ?? {}
  const raw =
    cs.estimated_credits ?? cs.actual_credits ?? cs.total_credits ?? cs.credits ?? 0
  return formatNumber(Number(raw) || 0)
}

const activeStats = computed(() => stats.value || emptyStats)

const loadOverview = async () => {
  const token = ++requestToken.value
  const params = rangeParams(overviewRange.value)
  overviewLoading.value = true
  try {
    const [statsResult, trendResult] = await Promise.all([
      getRoutingLogStats(params),
      getRoutingLogTrend({ ...params, granularity: 'day' }),
    ])
    if (token !== requestToken.value) return
    stats.value = statsResult
    trend.value = trendResult.points || []
  } catch (error) {
    if (token !== requestToken.value) return
    Message.error(getErrorMessage(error, t('admin.routingLogs.overviewLoadFailed')))
  } finally {
    if (token === requestToken.value) {
      overviewLoading.value = false
    }
  }
  await loadDistribution()
}

const handleRangeChange = (key: string) => {
  if (key === overviewRange.value) return
  overviewRange.value = key
  distributionCache.value = {}
  void loadOverview()
}

const distributionLoading = ref(false)
const distributionToken = ref(0)
const distributionDimensions = ['execution_mode', 'intent', 'model_tier']

const loadDistribution = async () => {
  const params = rangeParams(overviewRange.value)
  const dimensions = distributionDimensions.filter(
    (dimension) => !distributionCache.value[dimension]?.length,
  )
  if (!dimensions.length) return
  const token = ++distributionToken.value
  distributionLoading.value = true
  try {
    const results = await Promise.all(
      dimensions.map((dimension) =>
        getRoutingLogDistribution({ ...params, dimension, limit: 8 }),
      ),
    )
    if (token !== distributionToken.value) return
    const next = { ...distributionCache.value }
    dimensions.forEach((dimension, index) => {
      next[dimension] = (results[index].items || []).map((item) => ({
        ...item,
        dimension,
      }))
    })
    distributionCache.value = next
  } catch (error) {
    if (token !== distributionToken.value) return
    Message.error(getErrorMessage(error, t('admin.routingLogs.overviewLoadFailed')))
  } finally {
    if (token === distributionToken.value) {
      distributionLoading.value = false
    }
  }
}

const handleDistributionChange = (dimension: string) => {
  if (dimension === activeDistribution.value) return
  activeDistribution.value = dimension
  void loadDistribution()
}

const chartWidth = 720
const chartHeight = 120
const chartPadX = 12
const chartPadBottom = 18

type ChartBar = {
  x: number
  y: number
  width: number
  height: number
  requestCount: number
  fallbackCount: number
  dateLabel: string
  leftPercent: number
}

const chartBars = computed<{ bars: ChartBar[]; hasFallbackData: boolean }>(() => {
  if (!trend.value.length) return { bars: [], hasFallbackData: false }
  const plotWidth = chartWidth - chartPadX * 2
  const plotHeight = chartHeight - chartPadBottom
  const slotWidth = plotWidth / trend.value.length
  const barWidth = Math.max(Math.min(slotWidth * 0.62, 36), 2)
  const reqMax = Math.max(...trend.value.map((point) => point.request_count), 1)
  const hasFallbackData = trend.value.some((point) => Number(point.fallback_count) > 0)
  const hOf = (value: number) => (value / reqMax) * (plotHeight - 4)

  const bars = trend.value.map((point, index) => {
    const date = new Date(point.timestamp * 1000)
    const dateLabel = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(
      date.getDate(),
    ).padStart(2, '0')}`
    const requestCount = Number(point.request_count) || 0
    const fallbackCount = Number(point.fallback_count) || 0
    const x = chartPadX + slotWidth * index + (slotWidth - barWidth) / 2
    const totalHeight = hOf(requestCount)
    const y = plotHeight - totalHeight
    return {
      x,
      y,
      width: barWidth,
      height: totalHeight,
      requestCount,
      fallbackCount,
      dateLabel,
      leftPercent: ((x + barWidth / 2) / chartWidth) * 100,
    }
  })

  return { bars, hasFallbackData }
})

const formatLabel = (timestamp: number) => {
  const date = new Date(timestamp * 1000)
  return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

const chartLabels = computed(() =>
  trend.value.map((point, index) => ({
    x: chartPadX + ((chartWidth - chartPadX * 2) / Math.max(trend.value.length, 1)) * index + (chartWidth - chartPadX * 2) / Math.max(trend.value.length, 1) / 2,
    label: formatLabel(point.timestamp),
  })),
)

const hoveredTrendIndex = ref<number | null>(null)

const hoveredTrend = computed(() => {
  const bar = hoveredTrendIndex.value != null ? chartBars.value.bars[hoveredTrendIndex.value] : null
  if (!bar) return null
  return bar
})

const trendTotal = computed(() =>
  trend.value.reduce((total, point) => total + point.request_count, 0),
)

const trendPeak = computed(() => {
  if (!trend.value.length) return 0
  return Math.max(...trend.value.map((point) => point.request_count))
})

const distributionGroup = (dimension: string): DistributionRow[] =>
  [...(distributionCache.value[dimension] || [])].sort((a, b) => b.count - a.count)

const distributionPercent = (item: RoutingLogDistributionItem, dimension: string) => {
  const group = distributionGroup(dimension)
  const max = group.length ? Math.max(...group.map((entry) => entry.count)) : 0
  return max > 0 ? Math.max((item.count / max) * 100, 2) : 0
}

// 语义化标签渲染：有映射返回中文，无映射返回原值
const semanticVal = (key: string, value: unknown): string => {
  if (value == null || value === '') return '—'
  return semanticLabel(key, String(value))
}

// 语义化英文悬停提示：有映射返回英文原值（供 tooltip），无映射返回空
const semanticTip = (key: string, value: unknown): string => {
  if (value == null || value === '') return ''
  return semanticHint(key, String(value)) || ''
}

// 分布图 item 名语义化（execution_mode / intent / model_tier 维度）
const distributionItemLabel = (dimension: string, name: string) => {
  if (name === '') return '—'
  if (dimension === 'execution_mode') return semanticLabel('execution_mode', name, name)
  if (dimension === 'intent') return semanticLabel('intent', name, name)
  if (dimension === 'model_tier') return semanticLabel('model_tier', name, name)
  return name
}

// 用户/账号 ID 展示：uuid 截断 + 悬停完整值；可读名直接显示
const displayAccountId = (id: string | undefined) => {
  if (!id) return '—'
  if (isUuidLike(id)) return truncateId(id)
  return id
}

const textValue = (value: unknown, fallback = '—') => {
  if (value == null || value === '') return fallback
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return fallback
}

const openDetail = (log: AdminRoutingLogRecord) => {
  detailLog.value = log
  detailVisible.value = true
}

const openFeedback = (log: AdminRoutingLogRecord) => {
  feedbackTarget.value = log
  feedbackForm.value = {
    rating: 5,
    accuracy: 5,
    latency: 5,
    cost: 5,
    safety: 5,
    completeness: 5,
    comment: '',
  }
}

const submitFeedback = async () => {
  if (!feedbackTarget.value) return
  try {
    await createAdminRoutingQualityFeedback({
      routing_log_id: feedbackTarget.value.id,
      rating: feedbackForm.value.rating,
      dimension_scores: {
        accuracy: feedbackForm.value.accuracy,
        latency: feedbackForm.value.latency,
        cost: feedbackForm.value.cost,
        safety: feedbackForm.value.safety,
        completeness: feedbackForm.value.completeness,
      },
      comment: feedbackForm.value.comment,
    })
    Message.success(t('admin.routingLogs.feedbackSuccess'))
    feedbackTarget.value = null
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.routingLogs.feedbackFailed')))
  }
}

const jsonBlock = (value: unknown) => {
  if (value == null) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

const detailJson = computed(() => {
  if (!detailLog.value) return ''
  return jsonBlock(detailLog.value)
})

const loadRoutingLogs = async () => {
  listLoading.value = true
  try {
    const result = await listAdminRoutingLogs(filters.value)
    logs.value = result.list
    totalRecord.value = Number(result.paginator?.total_record ?? 0) || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.routingLogs.loadFailed')))
  } finally {
    listLoading.value = false
  }
}

const resetSearch = () => {
  searchForm.value = {
    account_id: '',
    status: '',
    invoke_from: '',
    agent_id: '',
    tool_name: '',
    model_id: '',
  }
  filters.value = {
    ...filters.value,
    ...searchForm.value,
    start_at: rangeParams(overviewRange.value)?.start_at || '',
    end_at: rangeParams(overviewRange.value)?.end_at || '',
    current_page: 1,
  }
  void loadRoutingLogs()
  void loadOverview()
}

const runSearch = () => {
  filters.value = {
    ...filters.value,
    ...searchForm.value,
    current_page: 1,
  }
  void loadRoutingLogs()
  void loadOverview()
}

const changePage = (page: number) => {
  filters.value.current_page = page
  void loadRoutingLogs()
}

onMounted(() => {
  void loadRoutingLogs()
  void loadOverview()
})
</script>

<template>
  <section class="space-y-6 p-6">
    <header class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight text-slate-900">
          {{ t('admin.routingLogs.title') }}
        </h1>
        <p class="mt-1 text-sm leading-6 text-slate-500">
          {{ t('admin.routingLogs.description') }}
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <span
          class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-100 p-1 shadow-sm"
          role="group"
          :aria-label="t('admin.routingLogs.timeRange')"
        >
          <button
            v-for="range in rangeOptions"
            :key="range.key"
            type="button"
            class="rounded-md px-3 py-1.5 text-sm font-medium transition"
            :class="
              overviewRange === range.key
                ? 'bg-white text-sky-700 shadow-sm'
                : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
            "
            :aria-pressed="overviewRange === range.key"
            @click="handleRangeChange(range.key)"
          >
            {{ range.label }}
          </button>
        </span>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition hover:bg-slate-50"
          :disabled="overviewLoading"
          @click="loadOverview"
        >
          <svg
            class="h-4 w-4"
            :class="overviewLoading ? 'animate-spin' : ''"
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
          {{ t('admin.routingLogs.refresh') }}
        </button>
      </div>
    </header>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-sm font-medium text-slate-500">
              {{ t('admin.routingLogs.totalRequests') }}
            </p>
            <div v-if="overviewLoading && !stats" class="mt-2 h-8 w-20 animate-pulse rounded bg-slate-100" />
            <strong v-else class="mt-2 block text-2xl font-semibold tracking-tight text-slate-900">
              {{ formatCount(activeStats.total_count) }}
            </strong>
          </div>
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sky-50 text-sky-600">
            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M4 4h7v7H4z" />
              <path d="M13 4h7v7h-7z" />
              <path d="M4 13h7v7H4z" />
              <path d="M13 13h7v7h-7z" />
            </svg>
          </span>
        </div>
        <p class="mt-3 text-xs leading-5 text-slate-400">
          {{ t('admin.routingLogs.successCountHint', { count: formatCount(activeStats.success_count) }) }}
        </p>
      </article>
      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-sm font-medium text-slate-500">
              {{ t('admin.routingLogs.successRate') }}
            </p>
            <div v-if="overviewLoading && !stats" class="mt-2 h-8 w-20 animate-pulse rounded bg-slate-100" />
            <strong v-else class="mt-2 block text-2xl font-semibold tracking-tight text-emerald-600">
              {{ formatRate(activeStats.success_rate) }}
            </strong>
          </div>
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600">
            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="m22 7-8.5 8.5-5-5L2 17" />
              <path d="M16 7h6v6" />
            </svg>
          </span>
        </div>
        <p class="mt-3 text-xs leading-5 text-slate-400">
          {{ t('admin.routingLogs.successRateHint') }}
        </p>
      </article>
      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-sm font-medium text-slate-500">
              {{ t('admin.routingLogs.fallbackRate') }}
            </p>
            <div v-if="overviewLoading && !stats" class="mt-2 h-8 w-20 animate-pulse rounded bg-slate-100" />
            <strong v-else class="mt-2 block text-2xl font-semibold tracking-tight text-orange-600">
              {{ formatRate(activeStats.fallback_rate) }}
            </strong>
          </div>
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-orange-50 text-orange-600">
            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M16 3h5v5" />
              <path d="M8 21H3v-5" />
              <path d="m21 3-7.5 7.5" />
              <path d="m3 21 7.5-7.5" />
            </svg>
          </span>
        </div>
        <p class="mt-3 text-xs leading-5 text-slate-400">
          {{ t('admin.routingLogs.fallbackCountHint', { count: formatCount(activeStats.fallback_count) }) }}
        </p>
      </article>
      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-sm font-medium text-slate-500">
              {{ t('admin.routingLogs.avgLatency') }}
            </p>
            <div v-if="overviewLoading && !stats" class="mt-2 h-8 w-20 animate-pulse rounded bg-slate-100" />
            <strong v-else class="mt-2 block text-2xl font-semibold tracking-tight text-slate-900">
              {{ formatLatency(activeStats.avg_latency_ms) }}
            </strong>
          </div>
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z" />
              <path d="M12 7v5l3 2" />
            </svg>
          </span>
        </div>
        <p class="mt-3 text-xs leading-5 text-slate-400">
          {{ t('admin.routingLogs.avgLatencyHint') }}
        </p>
      </article>
      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-sm font-medium text-slate-500">
              {{ t('admin.routingLogs.totalCredits') }}
            </p>
            <div v-if="overviewLoading && !stats" class="mt-2 h-8 w-20 animate-pulse rounded bg-slate-100" />
            <strong v-else class="mt-2 block text-2xl font-semibold tracking-tight text-slate-900">
              {{ formatNumber(activeStats.total_credits) }}
            </strong>
          </div>
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-violet-50 text-violet-600">
            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M4 7h16v10H4z" />
              <path d="M4 11h16" />
            </svg>
          </span>
        </div>
        <p class="mt-3 text-xs leading-5 text-slate-400">
          {{ t('admin.routingLogs.totalCreditsHint') }}
        </p>
      </article>
      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-sm font-medium text-slate-500">
              {{ t('admin.routingLogs.agentPoolHitRate') }}
            </p>
            <div v-if="overviewLoading && !stats" class="mt-2 h-8 w-20 animate-pulse rounded bg-slate-100" />
            <strong v-else class="mt-2 block text-2xl font-semibold tracking-tight text-slate-900">
              {{ formatRate(activeStats.agent_pool_hit_rate) }}
            </strong>
          </div>
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-cyan-50 text-cyan-600">
            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M12 21s-7-4.35-9.5-8A5.5 5.5 0 0 1 12 6.5 5.5 5.5 0 0 1 21.5 13c-2.5 3.65-9.5 8-9.5 8z" />
              <circle cx="12" cy="10" r="2.5" />
            </svg>
          </span>
        </div>
        <p class="mt-3 text-xs leading-5 text-slate-400">
          {{ t('admin.routingLogs.toolPoolHitRateHint', { rate: formatRate(activeStats.tool_pool_hit_rate) }) }}
        </p>
      </article>
    </section>

    <section
      class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm"
      aria-label="trend-section"
    >
      <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 class="text-base font-semibold text-slate-900">
            {{ trendTitle }}
          </h2>
          <p class="mt-0.5 text-xs text-slate-400">
            {{ t('admin.routingLogs.trendDescription') }}
          </p>
        </div>
        <div class="flex items-center gap-5 text-xs text-slate-500">
          <span class="flex items-center gap-1.5">
            <span class="inline-block h-2 w-2 rounded-full bg-sky-500" />
            {{ t('admin.routingLogs.trendRequests') }}
          </span>
          <span v-if="chartBars.hasFallbackData" class="flex items-center gap-1.5">
            <span class="inline-block h-2 w-2 rounded-full bg-amber-500" />
            {{ t('admin.routingLogs.trendFallback') }}
          </span>
        </div>
      </div>
      <div v-if="overviewLoading && !trend.length" class="mt-4 h-40 animate-pulse rounded-lg bg-slate-100" />
      <div v-else-if="!trend.length" class="mt-4 py-10 text-center text-sm text-slate-400">
        {{ t('admin.routingLogs.noData') }}
      </div>
      <div v-else class="mt-3 grid gap-6 lg:grid-cols-[1fr_auto] lg:items-center">
        <div class="min-w-0">
          <div class="relative w-full">
            <div
              v-if="hoveredTrend"
              class="pointer-events-none absolute z-10 -translate-x-1/2 whitespace-nowrap rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 shadow-sm"
              :style="{ left: `${hoveredTrend.leftPercent}%`, top: '0' }"
            >
              {{ hoveredTrend.dateLabel }} · 请求 {{ hoveredTrend.requestCount }}
              <span v-if="hoveredTrend.fallbackCount > 0" class="text-amber-600">
                · 降级 {{ hoveredTrend.fallbackCount }}
              </span>
            </div>
            <svg
              viewBox="0 0 720 120"
              preserveAspectRatio="xMidYMid meet"
              class="block w-full text-slate-200"
              style="aspect-ratio: 720 / 120; height: auto;"
            >
              <line x1="12" y1="8" x2="708" y2="8" stroke="currentColor" stroke-width="1" />
              <line x1="12" y1="52" x2="708" y2="52" stroke="currentColor" stroke-width="1" />
              <line x1="12" y1="102" x2="708" y2="102" stroke="currentColor" stroke-width="1" />
              <template v-for="(bar, index) in chartBars.bars" :key="index">
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
                  v-if="bar.fallbackCount > 0"
                  :x="bar.x"
                  :y="bar.y"
                  :width="bar.width"
                  :height="Math.min((bar.fallbackCount / Math.max(bar.requestCount, 1)) * bar.height, bar.height)"
                  rx="2"
                  fill="#f59e0b"
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
              v-for="label in chartLabels"
              :key="label.x"
              class="absolute -translate-x-1/2"
              :style="{ left: `${(label.x / chartWidth) * 100}%` }"
            >
              {{ label.label }}
            </span>
          </div>
        </div>
        <dl class="grid grid-cols-2 gap-3 lg:grid-cols-1">
          <div class="rounded-lg bg-slate-50 px-4 py-3">
            <dt class="text-xs text-slate-500">{{ t('admin.routingLogs.totalRequests') }}</dt>
            <dd class="mt-1 text-lg font-semibold text-slate-900">
              {{ formatCount(trendTotal) }}
            </dd>
          </div>
          <div class="rounded-lg bg-slate-50 px-4 py-3">
            <dt class="text-xs text-slate-500">{{ t('admin.routingLogs.trendPeak') }}</dt>
            <dd class="mt-1 text-lg font-semibold text-slate-900">
              {{ formatCount(trendPeak) }}
            </dd>
          </div>
        </dl>
      </div>
    </section>

    <section class="grid gap-4 xl:grid-cols-2">
      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <header class="flex items-center justify-between gap-3">
          <div>
            <h2 class="text-base font-semibold text-slate-900">
              {{ t('admin.routingLogs.distributionExecution') }}
            </h2>
            <p class="mt-0.5 text-xs text-slate-400">
              {{ t('admin.routingLogs.distributionDescription') }}
            </p>
          </div>
          <div class="flex items-center gap-3">
            <button
              v-for="option in distributionOptions"
              :key="option.key"
              type="button"
              class="rounded-md px-2 py-1 text-xs font-medium transition"
              :class="
                activeDistribution === option.key
                  ? 'bg-slate-900 text-white'
                  : 'text-slate-500 hover:bg-slate-100'
              "
              @click="handleDistributionChange(option.key)"
            >
              {{ option.label }}
            </button>
          </div>
        </header>
        <div
          v-if="(overviewLoading || distributionLoading) && !distributionGroup(activeDistribution).length"
          class="mt-4 space-y-3"
        >
          <div v-for="n in 4" :key="n" class="h-8 animate-pulse rounded-lg bg-slate-100" />
        </div>
        <div
          v-else-if="!distributionGroup(activeDistribution).length"
          class="mt-4 py-10 text-center text-sm text-slate-400"
        >
          {{ t('admin.routingLogs.noData') }}
        </div>
        <ul v-else class="mt-4 space-y-4">
          <li
            v-for="row in distributionGroup(activeDistribution)"
            :key="row.name"
            class="flex items-center gap-3"
          >
            <span class="w-24 shrink-0 truncate text-sm font-medium text-slate-700" :title="row.name">
              {{ distributionItemLabel(row.dimension, row.name) }}
            </span>
            <span class="flex h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
              <span
                class="h-full rounded-full"
                :class="row.dimension === 'intent' ? 'bg-indigo-500' : row.dimension === 'model_tier' ? 'bg-violet-500' : 'bg-sky-500'"
                :style="{ width: `${distributionPercent(row, activeDistribution)}%` }"
              />
            </span>
            <span class="w-10 shrink-0 text-right text-sm tabular-nums text-slate-500">
              {{ formatCount(row.count) }}
            </span>
          </li>
        </ul>
      </article>

      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <header>
          <h2 class="text-base font-semibold text-slate-900">
            {{ t('admin.routingLogs.distributionIntent') }}
          </h2>
          <p class="mt-0.5 text-xs text-slate-400">
            {{ t('admin.routingLogs.distributionCreditsLatency') }}
          </p>
        </header>
        <div
          v-if="(overviewLoading || distributionLoading) && !distributionGroup('intent').length"
          class="mt-4 space-y-3"
        >
          <div v-for="n in 4" :key="n" class="h-8 animate-pulse rounded-lg bg-slate-100" />
        </div>
        <div v-else-if="!distributionGroup('intent').length" class="mt-4 py-10 text-center text-sm text-slate-400">
          {{ t('admin.routingLogs.noData') }}
        </div>
        <ul v-else class="mt-4 space-y-4">
          <li v-for="row in distributionGroup('intent')" :key="row.name" class="flex items-center gap-3">
            <span class="w-24 shrink-0 truncate text-sm font-medium text-slate-700" :title="row.name">
              {{ distributionItemLabel(row.dimension, row.name) }}
            </span>
            <span class="flex h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
              <span
                class="h-full rounded-full bg-indigo-500"
                :style="{ width: `${distributionPercent(row, 'intent')}%` }"
              />
            </span>
            <span class="flex shrink-0 items-center gap-3 text-xs tabular-nums text-slate-400">
              <span>{{ formatCount(row.count) }}</span>
              <span>{{ formatNumber(row.credits) }}</span>
              <span>{{ Math.round(row.avg_latency_ms || 0) }}ms</span>
            </span>
          </li>
        </ul>
      </article>
    </section>

    <section class="space-y-4">
      <div class="flex items-end justify-between gap-4">
        <div>
          <h2 class="text-lg font-semibold text-slate-900">
            {{ t('admin.routingLogs.detailTitle') }}
          </h2>
          <p class="mt-1 text-sm text-slate-500">
            {{ t('admin.routingLogs.detailDescription') }}
          </p>
        </div>
        <a-button :loading="listLoading" @click="loadRoutingLogs">
          {{ t('admin.routingLogs.refresh') }}
        </a-button>
      </div>

      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <header class="flex items-center justify-between gap-3">
          <div>
            <h3 class="text-sm font-semibold text-slate-900">
              {{ t('admin.routingLogs.filters') }}
            </h3>
            <p class="mt-0.5 text-xs text-slate-400">
              {{ t('admin.routingLogs.filterDescription') }}
            </p>
          </div>
          <div v-if="totalRecord" class="text-xs text-slate-400">
            {{ t('admin.routingLogs.total', { count: totalRecord }) }}
          </div>
        </header>
        <div class="mt-4 grid gap-3 md:grid-cols-3 xl:grid-cols-7">
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-slate-500">{{ t('admin.routingLogs.status') }}</span>
            <select
              v-model="searchForm.status"
              class="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none transition focus:border-sky-400"
            >
              <option v-for="option in statusOptions" :key="option.key" :value="option.key">
                {{ option.label }}
              </option>
            </select>
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-slate-500">{{ t('admin.routingLogs.invokeFrom') }}</span>
            <select
              v-model="searchForm.invoke_from"
              class="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none transition focus:border-sky-400"
            >
              <option v-for="option in invokeFromOptions" :key="option.key" :value="option.key">
                {{ option.label }}
              </option>
            </select>
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-slate-500">{{ t('admin.routingLogs.account') }}</span>
            <input
              v-model="searchForm.account_id"
              type="text"
              class="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none transition placeholder:text-slate-300 focus:border-sky-400"
              :placeholder="t('admin.routingLogs.accountIdPlaceholder')"
            />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-slate-500">{{ t('admin.routingLogs.agent') }}</span>
            <input
              v-model="searchForm.agent_id"
              type="text"
              class="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none transition placeholder:text-slate-300 focus:border-sky-400"
              :placeholder="t('admin.routingLogs.agentIdPlaceholder')"
            />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-slate-500">{{ t('admin.routingLogs.tool') }}</span>
            <input
              v-model="searchForm.tool_name"
              type="text"
              class="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none transition placeholder:text-slate-300 focus:border-sky-400"
              :placeholder="t('admin.routingLogs.toolNamePlaceholder')"
            />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-slate-500">{{ t('admin.routingLogs.model') }}</span>
            <input
              v-model="searchForm.model_id"
              type="text"
              class="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none transition placeholder:text-slate-300 focus:border-sky-400"
              :placeholder="t('admin.routingLogs.modelIdPlaceholder')"
            />
          </label>
          <div class="flex items-end gap-2">
            <button
              type="button"
              class="inline-flex items-center justify-center rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="listLoading"
              @click="runSearch"
            >
              {{ t('admin.routingLogs.search') }}
            </button>
            <button
              type="button"
              class="inline-flex items-center justify-center rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition hover:bg-slate-50"
              @click="resetSearch"
            >
              {{ t('admin.routingLogs.reset') }}
            </button>
          </div>
        </div>
      </article>

      <article class="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <div v-if="listLoading" class="p-8 text-center text-sm text-slate-400">
          {{ t('admin.routingLogs.loading') }}
        </div>
        <div v-else-if="!logs.length" class="p-8 text-center text-sm text-slate-400">
          {{ t('admin.routingLogs.noData') }}
        </div>
        <template v-else>
          <div class="overflow-x-auto">
            <table class="w-full text-left text-sm">
              <thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th class="px-4 py-3 font-medium">{{ t('admin.routingLogs.createdAt') }}</th>
                  <th class="px-4 py-3 font-medium">{{ t('admin.routingLogs.userQuery') }}</th>
                  <th class="px-4 py-3 font-medium">{{ t('admin.routingLogs.status') }}</th>
                  <th class="px-4 py-3 font-medium">{{ t('admin.routingLogs.executionMode') }}</th>
                  <th class="px-4 py-3 font-medium">{{ t('admin.routingLogs.complexity') }}</th>
                  <th class="px-4 py-3 font-medium">{{ t('admin.routingLogs.model') }}</th>
                  <th class="px-4 py-3 font-medium">{{ t('admin.routingLogs.invokeFrom') }}</th>
                  <th class="px-4 py-3 font-medium">{{ t('admin.routingLogs.latency') }}</th>
                  <th class="px-4 py-3 font-medium">{{ t('admin.routingLogs.credits') }}</th>
                  <th class="px-4 py-3 font-medium">{{ t('admin.routingLogs.operations') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="log in logs" :key="log.id" class="border-t border-slate-100">
                  <td class="whitespace-nowrap px-4 py-3 tabular-nums text-slate-500">
                    {{ formatTimestampLong(log.created_at) }}
                  </td>
                  <td class="max-w-[260px] px-4 py-3">
                    <span class="block truncate text-slate-700" :title="log.user_query || log.id">
                      {{ log.user_query || log.id }}
                    </span>
                  </td>
                  <td class="px-4 py-3">
                    <span
                      class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset"
                      :class="statusTagClass(log.status)"
                    >
                      {{ statusLabel(log.status) }}
                    </span>
                  </td>
                  <td class="px-4 py-3 text-slate-600">
                    <span
                      v-if="hasSemantic('execution_mode', String(log.routing_decision?.execution_mode ?? ''))"
                      :title="semanticTip('execution_mode', log.routing_decision?.execution_mode)"
                    >
                      {{ semanticVal('execution_mode', log.routing_decision?.execution_mode) }}
                    </span>
                    <span v-else>{{ textValue(log.routing_decision?.execution_mode) }}</span>
                  </td>
                  <td class="px-4 py-3 text-slate-600">
                    <span
                      v-if="hasSemantic('complexity', String(log.task_classification?.complexity ?? ''))"
                      :title="semanticTip('complexity', log.task_classification?.complexity)"
                    >
                      {{ semanticVal('complexity', log.task_classification?.complexity) }}
                    </span>
                    <span v-else>{{ textValue(log.task_classification?.complexity) }}</span>
                  </td>
                  <td class="max-w-[200px] px-4 py-3">
                    <span class="block truncate text-slate-600" :title="textValue(log.model_selection?.model_id)">
                      {{ textValue(log.model_selection?.model_id) }}
                    </span>
                  </td>
                  <td class="px-4 py-3">
                    <span class="text-xs text-slate-500">{{ invokeFromLabel(log.invoke_from) }}</span>
                  </td>
                  <td class="whitespace-nowrap px-4 py-3 tabular-nums text-slate-500">
                    {{ log.latency_ms }} ms
                  </td>
                  <td class="whitespace-nowrap px-4 py-3 tabular-nums text-slate-600">
                    {{ displayCost(log) }}
                  </td>
                  <td class="whitespace-nowrap px-4 py-3">
                    <button
                      type="button"
                      class="rounded-md px-2.5 py-1 text-xs font-medium text-sky-600 transition hover:bg-sky-50"
                      @click="openDetail(log)"
                    >
                      {{ t('admin.routingLogs.detail') }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <footer class="flex items-center justify-between border-t border-slate-100 px-4 py-3">
            <span class="text-xs text-slate-400">
              {{ t('admin.routingLogs.total', { count: totalRecord }) }}
            </span>
            <a-pagination
              :total="totalRecord"
              :current="filters.current_page"
              :page-size="filters.page_size"
              show-total
              @change="changePage"
            />
          </footer>
        </template>
      </article>
    </section>

    <a-drawer
      :visible="detailVisible"
      :width="720"
      :footer="false"
      @cancel="detailVisible = false"
    >
      <template #title>
        <div class="flex items-center justify-between gap-3 pr-8">
          <span class="text-base font-semibold text-slate-900">
            {{ t('admin.routingLogs.detailTitle') }}
          </span>
          <button
            type="button"
            class="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition hover:bg-slate-50"
            @click="detailVisible = false"
          >
            {{ t('admin.routingLogs.close') }}
          </button>
        </div>
      </template>
      <div v-if="detailLog" class="space-y-5">
        <div class="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-slate-50/60 p-4">
          <span
            class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset"
            :class="statusTagClass(detailLog.status)"
          >
            {{ statusLabel(detailLog.status) }}
          </span>
          <span class="text-xs text-slate-500">
            {{ formatTimestampLong(detailLog.created_at) }}
          </span>
          <span class="text-xs text-slate-500">
            {{ t('admin.routingLogs.invokeFrom') }}: {{ invokeFromLabel(detailLog.invoke_from) }}
          </span>
          <span class="text-xs text-slate-500">
            {{ t('admin.routingLogs.account') }}:
            <a-tooltip v-if="isUuidLike(detailLog.account_id)" :content="detailLog.account_id" position="top" mini>
              <span class="cursor-help font-mono">{{ displayAccountId(detailLog.account_id) }}</span>
            </a-tooltip>
            <template v-else>{{ detailLog.account_id || '—' }}</template>
          </span>
          <a-tag v-if="detailLog.agent_pool_hits?.[0]?.pool" size="small" color="arcoblue">
            <a-tooltip
              content="Agent 子池：路由决策时命中的 Agent 候选池名称（英文标记）"
              position="top"
              mini
            >
              <span class="cursor-help">{{ t('admin.routingLogs.agentPool') }}: {{ detailLog.agent_pool_hits[0].pool }}</span>
            </a-tooltip>
          </a-tag>
          <a-tag v-if="detailLog.tool_pool_hits?.[0]?.pool" size="small" color="green">
            <a-tooltip
              content="工具子池：路由决策时命中的工具候选池名称（英文标记）"
              position="top"
              mini
            >
              <span class="cursor-help">{{ t('admin.routingLogs.toolPool') }}: {{ detailLog.tool_pool_hits[0].pool }}</span>
            </a-tooltip>
          </a-tag>
        </div>

        <div class="rounded-lg border border-slate-200 p-4">
          <h4 class="text-sm font-semibold text-slate-900">
            {{ t('admin.routingLogs.userQuery') }}
          </h4>
          <p class="mt-2 break-words text-sm leading-6 text-slate-600">
            {{ detailLog.user_query || '—' }}
          </p>
        </div>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div class="rounded-lg border border-slate-200 p-4">
            <p class="text-xs text-slate-500">{{ t('admin.routingLogs.executionMode') }}</p>
            <p
              class="mt-1 text-sm font-medium text-slate-800"
              :title="semanticTip('execution_mode', detailLog.routing_decision?.execution_mode)"
            >
              {{ semanticVal('execution_mode', detailLog.routing_decision?.execution_mode) }}
            </p>
          </div>
          <div class="rounded-lg border border-slate-200 p-4">
            <p class="text-xs text-slate-500">{{ t('admin.routingLogs.intent') }}</p>
            <p
              class="mt-1 text-sm font-medium text-slate-800"
              :title="semanticTip('intent', detailLog.routing_decision?.intent)"
            >
              {{ semanticVal('intent', detailLog.routing_decision?.intent) }}
            </p>
          </div>
          <div class="rounded-lg border border-slate-200 p-4">
            <p class="text-xs text-slate-500">{{ t('admin.routingLogs.riskLevel') }}</p>
            <p
              class="mt-1 text-sm font-medium text-slate-800"
              :title="semanticTip('risk_level', detailLog.routing_decision?.risk_level)"
            >
              {{ semanticVal('risk_level', detailLog.routing_decision?.risk_level) }}
            </p>
          </div>
          <div class="rounded-lg border border-slate-200 p-4">
            <p class="text-xs text-slate-500">{{ t('admin.routingLogs.complexity') }}</p>
            <p
              class="mt-1 text-sm font-medium text-slate-800"
              :title="semanticTip('complexity', detailLog.task_classification?.complexity)"
            >
              {{ semanticVal('complexity', detailLog.task_classification?.complexity) }}
            </p>
          </div>
          <div class="rounded-lg border border-slate-200 p-4">
            <p class="text-xs text-slate-500">{{ t('admin.routingLogs.model') }}</p>
            <p class="mt-1 truncate text-sm font-medium text-slate-800" :title="textValue(detailLog.model_selection?.model_id)">
              {{ textValue(detailLog.model_selection?.model_id) }}
            </p>
          </div>
          <div class="rounded-lg border border-slate-200 p-4">
            <p class="text-xs text-slate-500">{{ t('admin.routingLogs.costPolicy') }}</p>
            <p class="mt-1 text-sm font-medium text-slate-800">
              {{ costPolicyLabel(detailLog.routing_decision?.cost_policy?.allowed) }}
            </p>
          </div>
          <div class="rounded-lg border border-slate-200 p-4">
            <p class="text-xs text-slate-500">{{ t('admin.routingLogs.latency') }}</p>
            <p class="mt-1 text-sm font-medium text-slate-800">{{ detailLog.latency_ms }} ms</p>
          </div>
          <div class="rounded-lg border border-slate-200 p-4">
            <p class="text-xs text-slate-500">{{ t('admin.routingLogs.credits') }}</p>
            <p class="mt-1 text-sm font-medium text-slate-800">
              {{ displayCost(detailLog) }}
            </p>
          </div>
          <div class="rounded-lg border border-slate-200 p-4">
            <p class="text-xs text-slate-500">{{ t('admin.routingLogs.fallbackReason') }}</p>
            <p class="mt-1 text-sm font-medium text-slate-800">
              {{ detailLog.fallback_reason || '—' }}
            </p>
          </div>
        </div>

        <div>
          <div class="flex items-center justify-between gap-3">
            <h4 class="text-sm font-semibold text-slate-900">
              {{ t('admin.routingLogs.routingDecisionJson') }}
            </h4>
            <button
              type="button"
              class="rounded-md border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 shadow-sm transition hover:bg-slate-50"
              @click="openFeedback(detailLog)"
            >
              {{ t('admin.routingLogs.feedback') }}
            </button>
          </div>
          <pre class="mt-2 max-h-96 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs leading-5 text-slate-600"><code>{{ detailJson }}</code></pre>
        </div>
      </div>
    </a-drawer>

    <a-modal
      v-if="feedbackTarget"
      :visible="true"
      :title="t('admin.routingLogs.feedbackForm')"
      @cancel="feedbackTarget = null"
      @ok="submitFeedback"
      @close="feedbackTarget = null"
    >
      <div class="space-y-4">
        <p class="text-sm text-slate-500">
          {{ detailLog ? detailLog.id : feedbackTarget.id }}
        </p>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-slate-500">{{ t('admin.routingLogs.rating') }}</span>
            <select
              v-model.number="feedbackForm.rating"
              class="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none transition focus:border-sky-400"
            >
              <option v-for="score in 5" :key="score" :value="score">{{ score }}</option>
            </select>
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-slate-500">{{ t('admin.routingLogs.accuracy') }}</span>
            <select
              v-model.number="feedbackForm.accuracy"
              class="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none transition focus:border-sky-400"
            >
              <option v-for="score in 5" :key="score" :value="score">{{ score }}</option>
            </select>
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-slate-500">{{ t('admin.routingLogs.latencyScore') }}</span>
            <select
              v-model.number="feedbackForm.latency"
              class="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none transition focus:border-sky-400"
            >
              <option v-for="score in 5" :key="score" :value="score">{{ score }}</option>
            </select>
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-slate-500">{{ t('admin.routingLogs.costScore') }}</span>
            <select
              v-model.number="feedbackForm.cost"
              class="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none transition focus:border-sky-400"
            >
              <option v-for="score in 5" :key="score" :value="score">{{ score }}</option>
            </select>
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-slate-500">{{ t('admin.routingLogs.safetyScore') }}</span>
            <select
              v-model.number="feedbackForm.safety"
              class="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none transition focus:border-sky-400"
            >
              <option v-for="score in 5" :key="score" :value="score">{{ score }}</option>
            </select>
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-slate-500">{{ t('admin.routingLogs.completenessScore') }}</span>
            <select
              v-model.number="feedbackForm.completeness"
              class="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none transition focus:border-sky-400"
            >
              <option v-for="score in 5" :key="score" :value="score">{{ score }}</option>
            </select>
          </label>
        </div>
        <label class="block">
          <span class="mb-1 block text-xs font-medium text-slate-500">{{ t('admin.routingLogs.comment') }}</span>
          <textarea
            v-model="feedbackForm.comment"
            rows="3"
            class="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none transition placeholder:text-slate-300 focus:border-sky-400"
            :placeholder="t('admin.routingLogs.commentPlaceholder')"
          />
        </label>
      </div>
    </a-modal>
  </section>
</template>
