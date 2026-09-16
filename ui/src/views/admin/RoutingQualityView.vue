<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import type {
  AdminRoutingOptimizationSuggestion,
  AdminRoutingQualityGroup,
  AdminRoutingQualityMetrics,
} from '@/models/admin-routing-quality'
import {
  getAdminRoutingQualityMetrics,
  listAdminRoutingQualitySuggestions,
} from '@/services/admin-routing-quality'
import {
  acceptSuggestion,
  dismissSuggestion,
  previewPolicyChange,
  applyPolicyChange,
  type PolicyChangePreview,
} from '@/services/admin-routing-quality-suggestion'
import PolicyChangePreviewModal from './routing-quality/PolicyChangePreviewModal.vue'
import { getErrorMessage } from '@/utils/error'
import { isUuidLike, semanticHint, semanticLabel, truncateId } from '@/utils/semantic-labels'

const { t } = useI18n()
const loading = ref(false)
const metrics = ref<AdminRoutingQualityMetrics | null>(null)
const suggestions = ref<AdminRoutingOptimizationSuggestion[]>([])
const activeRange = ref('30d')
const requestToken = ref(0)

const actionLoading = ref<string>('')
const previewVisible = ref(false)
const previewLoading = ref(false)
const previewData = ref<PolicyChangePreview | null>(null)
const dismissVisible = ref(false)
const dismissSubmitting = ref(false)
const dismissTarget = ref<AdminRoutingOptimizationSuggestion | null>(null)
const dismissReason = ref('')
const applyConfirmVisible = ref(false)
const applySubmitting = ref(false)
const applyTarget = ref<AdminRoutingOptimizationSuggestion | null>(null)

const rangeOptions = computed(() => [
  { key: '7d', label: t('admin.routingQuality.range7d') },
  { key: '30d', label: t('admin.routingQuality.range30d') },
  { key: '90d', label: t('admin.routingQuality.range90d') },
  { key: '180d', label: t('admin.routingQuality.range180d') },
  { key: 'all', label: t('admin.routingQuality.rangeAll') },
])

const rangeDays: Record<string, number | null> = {
  '7d': 7,
  '30d': 30,
  '90d': 90,
  '180d': 180,
  all: null,
}

const rangeParams = (range: string): { start_at?: string; end_at?: string } | undefined => {
  const days = rangeDays[range]
  if (days == null) return undefined
  const now = Math.floor(Date.now() / 1000)
  return { start_at: String(now - days * 86400), end_at: String(now) }
}

const loadData = async () => {
  const token = ++requestToken.value
  const params = rangeParams(activeRange.value)
  loading.value = true
  try {
    const [metricsResult, suggestionsResult] = await Promise.all([
      getAdminRoutingQualityMetrics(params),
      listAdminRoutingQualitySuggestions(),
    ])
    if (token !== requestToken.value) return
    metrics.value = metricsResult
    suggestions.value = suggestionsResult
  } catch (error) {
    if (token !== requestToken.value) return
    Message.error(getErrorMessage(error, t('admin.routingQuality.loadFailed')))
  } finally {
    if (token === requestToken.value) {
      loading.value = false
    }
  }
}

const handleRangeChange = (key: string) => {
  if (key === activeRange.value) return
  activeRange.value = key
  void loadData()
}

onMounted(() => {
  void loadData()
})

const groupEntries = (group?: Record<string, AdminRoutingQualityGroup>) => {
  return Object.entries(group || {})
}

type GroupRow = {
  name: string
  count: number
  rating: number
  percent: number
  color: string
}

type QualityGroup = {
  key: string
  title: string
  rows: GroupRow[]
}

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

const buildRows = (entries: [string, AdminRoutingQualityGroup][]): GroupRow[] => {
  const sorted = [...entries].sort((a, b) => b[1].count - a[1].count)
  const max = sorted.length ? sorted[0][1].count : 0
  return sorted.map(([name, item], index) => ({
    name,
    count: item.count,
    rating: item.avg_rating,
    percent: max > 0 ? Math.max((item.count / max) * 100, 2) : 0,
    color: barColors[index % barColors.length],
  }))
}

const qualityGroups = computed<QualityGroup[]>(() => {
  const groups: QualityGroup[] = []
  const append = (titleKey: string, entries: [string, AdminRoutingQualityGroup][]) => {
    groups.push({
      key: titleKey,
      title: t(`admin.routingQuality.${titleKey}`),
      rows: buildRows(entries),
    })
  }
  append('byTaskType', groupEntries(metrics.value?.quality_by_task_type))
  append('byAgentPool', groupEntries(metrics.value?.quality_by_agent_pool))
  append('byToolPool', groupEntries(metrics.value?.quality_by_tool_pool))
  append('byModel', groupEntries(metrics.value?.quality_by_model))
  return groups
})

const fullStars = (rating: number) => Math.round(Math.max(0, Math.min(5, rating)))

// 分组行名语义化：任务类型/Agent池/工具来源/模型档位分别走对应字典
const groupRowLabel = (groupKey: string, name: string) => {
  const keyMap: Record<string, string> = {
    byTaskType: 'task_type',
    byAgentPool: 'agent_pool',
    byToolPool: 'tool_source_type',
    byModel: 'model_tier',
  }
  const semanticKey = keyMap[groupKey]
  if (!semanticKey) return name
  return semanticLabel(semanticKey, name, name)
}

const groupRowRaw = (groupKey: string, name: string): string | undefined => {
  const keyMap: Record<string, string> = {
    byTaskType: 'task_type',
    byAgentPool: 'agent_pool',
    byToolPool: 'tool_source_type',
    byModel: 'model_tier',
  }
  const semanticKey = keyMap[groupKey]
  if (!semanticKey) return undefined
  return semanticHint(semanticKey, name)
}

const formatCount = (value: number | undefined | null) =>
  value == null ? '--' : Number(value).toLocaleString()

const formatRating = (value: number | undefined | null) =>
  value == null ? '--' : Number(value).toFixed(1)

const formatRate = (value: number | undefined | null) =>
  value == null ? '--' : `${(Number(value) * 100).toFixed(1)}%`

const formatLatency = (value: number | undefined | null) =>
  value == null ? '--' : `${Math.round(Number(value))} ms`

const formatCost = (value: number | undefined | null) =>
  value == null ? '--' : Number(value).toFixed(2)

type KpiCard = {
  key: string
  label: string
  hint: string
  value: string
  iconBg: string
  iconPaths: string[]
}

const kpiCards = computed<KpiCard[]>(() => {
  const m = metrics.value
  return [
    {
      key: 'total',
      label: t('admin.routingQuality.totalCount'),
      hint: t('admin.routingQuality.totalCountHint'),
      value: formatCount(m?.total_count),
      iconBg: 'bg-sky-50 text-sky-600',
      iconPaths: ['M4 4h7v7H4z', 'M13 4h7v7h-7z', 'M4 13h7v7H4z', 'M13 13h7v7h-7z'],
    },
    {
      key: 'feedback',
      label: t('admin.routingQuality.feedbackCount'),
      hint: t('admin.routingQuality.feedbackCountHint'),
      value: formatCount(m?.feedback_count),
      iconBg: 'bg-violet-50 text-violet-600',
      iconPaths: [
        'M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z',
        'M9.5 11.5h.01M12.5 11.5h.01M15.5 11.5h.01',
      ],
    },
    {
      key: 'rating',
      label: t('admin.routingQuality.avgRating'),
      hint: t('admin.routingQuality.avgRatingHint'),
      value: formatRating(m?.avg_rating),
      iconBg: 'bg-amber-50 text-amber-600',
      iconPaths: ['M12 3.4l2.7 5.6 6.1.8-4.5 4.3 1.1 6L12 17.2l-5.4 2.9 1.1-6L3.2 9.8l6.1-.8z'],
    },
    {
      key: 'fallback',
      label: t('admin.routingQuality.fallbackRate'),
      hint: t('admin.routingQuality.fallbackRateHint'),
      value: formatRate(m?.fallback_rate),
      iconBg: 'bg-rose-50 text-rose-600',
      iconPaths: [
        'M16 3h5v5',
        'M8 21H3v-5',
        'm21 3-7.5 7.5',
        'm3 21 7.5-7.5',
        'M13.5 10.5v2a2 2 0 0 1-2 2h-2',
      ],
    },
    {
      key: 'latency',
      label: t('admin.routingQuality.avgLatency'),
      hint: t('admin.routingQuality.avgLatencyHint'),
      value: formatLatency(m?.avg_latency_ms),
      iconBg: 'bg-emerald-50 text-emerald-600',
      iconPaths: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 7v5l3 2'],
    },
    {
      key: 'cost',
      label: t('admin.routingQuality.avgCost'),
      hint: t('admin.routingQuality.avgCostHint'),
      value: formatCost(m?.avg_cost_credits),
      iconBg: 'bg-cyan-50 text-cyan-600',
      iconPaths: ['M4 7h16v10H4z', 'M4 11h16', 'M7 15h4'],
    },
  ]
})

const severityBadgeClass = (severity: string) => {
  switch (severity) {
    case 'high':
      return 'bg-red-50 text-red-700 ring-red-200'
    case 'medium':
      return 'bg-orange-50 text-orange-700 ring-orange-200'
    default:
      return 'bg-gray-100 text-gray-600 ring-gray-200'
  }
}

const severityLabel = (severity: string) => {
  switch (severity) {
    case 'high':
      return t('admin.routingQuality.severityHigh')
    case 'medium':
      return t('admin.routingQuality.severityMedium')
    case 'low':
      return t('admin.routingQuality.severityLow')
    default:
      return severity
  }
}

const statusBadgeClass = (status: string) => {
  switch (status) {
    case 'accepted':
      return 'bg-sky-50 text-sky-700'
    case 'dismissed':
      return 'bg-red-50 text-red-600'
    case 'applied':
      return 'bg-emerald-50 text-emerald-700'
    default:
      return 'bg-slate-100 text-slate-600'
  }
}

const statusLabel = (status: string) => {
  switch (status) {
    case 'open':
      return t('admin.routingQuality.statusOpen')
    case 'accepted':
      return t('admin.routingQuality.statusAccepted')
    case 'dismissed':
      return t('admin.routingQuality.statusDismissed')
    case 'applied':
      return t('admin.routingQuality.statusApplied')
    default:
      return status
  }
}

const openSuggestions = computed(() => suggestions.value.filter((s) => s.status === 'open').length)

const reloadAfterAction = async () => {
  try {
    const result = await listAdminRoutingQualitySuggestions()
    suggestions.value = result
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.routingQuality.loadFailed')))
  }
}

const handleAccept = async (suggestion: AdminRoutingOptimizationSuggestion) => {
  if (!suggestion.id) return
  actionLoading.value = `accept-${suggestion.id}`
  try {
    await acceptSuggestion(suggestion.id)
    Message.success(t('policyChange.acceptSuccess'))
    await reloadAfterAction()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.routingQuality.loadFailed')))
  } finally {
    actionLoading.value = ''
  }
}

const openDismiss = (suggestion: AdminRoutingOptimizationSuggestion) => {
  dismissTarget.value = suggestion
  dismissReason.value = ''
  dismissVisible.value = true
}

const submitDismiss = async () => {
  if (!dismissTarget.value?.id) return
  if (!dismissReason.value.trim()) return
  dismissSubmitting.value = true
  try {
    await dismissSuggestion(dismissTarget.value.id, dismissReason.value.trim())
    Message.success(t('policyChange.dismissSuccess'))
    dismissVisible.value = false
    await reloadAfterAction()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.routingQuality.loadFailed')))
  } finally {
    dismissSubmitting.value = false
  }
}

const handlePreview = async (suggestion: AdminRoutingOptimizationSuggestion) => {
  if (!suggestion.id) return
  previewVisible.value = true
  previewLoading.value = true
  previewData.value = null
  try {
    const res = await previewPolicyChange(suggestion.id)
    previewData.value = res.data
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.routingQuality.loadFailed')))
    previewVisible.value = false
  } finally {
    previewLoading.value = false
  }
}

const openApply = (suggestion: AdminRoutingOptimizationSuggestion) => {
  applyTarget.value = suggestion
  applyConfirmVisible.value = true
}

const submitApply = async () => {
  if (!applyTarget.value?.id) return
  applySubmitting.value = true
  try {
    const previewRes = await previewPolicyChange(applyTarget.value.id)
    await applyPolicyChange(applyTarget.value.id, previewRes.data)
    Message.success(t('policyChange.applySuccess'))
    applyConfirmVisible.value = false
    await reloadAfterAction()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.routingQuality.loadFailed')))
  } finally {
    applySubmitting.value = false
  }
}

const actionableTypes = ['review_model_cost', 'review_tool_health', 'review_fallback_rate']

const canPreview = (suggestion: AdminRoutingOptimizationSuggestion) =>
  actionableTypes.includes(suggestion.suggestion_type) &&
  ['open', 'accepted'].includes(suggestion.status) &&
  !!suggestion.id

const reasonLabel = (suggestion: AdminRoutingOptimizationSuggestion) =>
  semanticLabel('suggestion_reason', suggestion.suggestion_type, suggestion.reason)

const suggestionActionKeys = (suggestion: AdminRoutingOptimizationSuggestion): string[] => {
  if (!suggestion.id) return []
  const keys: string[] = []
  if (canPreview(suggestion)) keys.push('preview')
  if (
    suggestion.status === 'open' &&
    actionableTypes.includes(suggestion.suggestion_type)
  ) {
    keys.push('accept', 'dismiss')
  }
  if (
    suggestion.status === 'open' &&
    suggestion.suggestion_type === 'collect_more_feedback'
  ) {
    keys.push('dismiss')
  }
  if (
    suggestion.status === 'accepted' &&
    actionableTypes.includes(suggestion.suggestion_type)
  ) {
    keys.push('dismiss', 'apply')
  }
  return keys
}
</script>

<template>
  <section class="space-y-6 p-6">
    <header class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight text-slate-900">
          {{ t('admin.routingQuality.title') }}
        </h1>
        <p class="mt-1 text-sm leading-6 text-slate-500">
          {{ t('admin.routingQuality.description') }}
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <span
          class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-100 p-1 shadow-sm"
          role="group"
          :aria-label="t('admin.routingQuality.timeRange')"
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
          :disabled="loading"
          :title="t('admin.routingQuality.refresh')"
          @click="loadData"
        >
          <svg
            class="h-4 w-4"
            :class="loading ? 'animate-spin' : ''"
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
          {{ t('admin.routingQuality.refresh') }}
        </button>
      </div>
    </header>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
      <article
        v-for="card in kpiCards"
        :key="card.key"
        class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-sm font-medium text-slate-500">{{ card.label }}</p>
            <strong class="mt-2 block text-2xl font-semibold tracking-tight text-slate-900">
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

    <section class="grid gap-4 xl:grid-cols-2">
      <article
        v-for="(group, index) in qualityGroups"
        :key="group.key"
        class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm"
        :class="qualityGroups.length === 1 && index === 0 ? 'xl:col-span-2' : ''"
      >
        <header class="flex items-center justify-between gap-3">
          <div>
            <h2 class="text-base font-semibold text-slate-900">{{ group.title }}</h2>
            <p class="mt-0.5 text-xs text-slate-400">
              {{ t('admin.routingQuality.countLabel') }} ·
              {{ t('admin.routingQuality.avgRatingLabel') }}
            </p>
          </div>
          <span
            class="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600"
          >
            {{ group.rows.length }}
          </span>
        </header>
        <ul v-if="group.rows.length" class="mt-4 space-y-4">
          <li v-for="row in group.rows" :key="row.name">
            <div class="flex items-center justify-between gap-3">
              <a-tooltip
                :content="row.name"
                :disabled="!groupRowRaw(group.key, row.name)"
                position="top"
                mini
              >
                <span class="truncate text-sm font-medium text-slate-700">
                  {{ groupRowLabel(group.key, row.name) }}
                </span>
              </a-tooltip>
              <span class="flex shrink-0 items-center gap-3">
                <span class="text-sm text-slate-500">{{ row.count }}</span>
                <span class="flex items-center text-amber-400" aria-hidden="true">
                  <template v-for="star in 5" :key="star">
                    <svg
                      v-if="star <= fullStars(row.rating)"
                      class="h-3 w-3"
                      viewBox="0 0 24 24"
                      fill="currentColor"
                    >
                      <path
                        d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.6L12 17.4 6.1 20.6l1.2-6.6L2.5 9.4l6.6-.9z"
                      />
                    </svg>
                    <svg
                      v-else
                      class="h-3 w-3 text-slate-200"
                      viewBox="0 0 24 24"
                      fill="currentColor"
                    >
                      <path
                        d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.6L12 17.4 6.1 20.6l1.2-6.6L2.5 9.4l6.6-.9z"
                      />
                    </svg>
                  </template>
                  <span class="ml-1 text-xs tabular-nums text-slate-400">
                    {{ row.rating.toFixed(1) }}
                  </span>
                </span>
              </span>
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
          {{ t('admin.routingQuality.empty') }}
        </p>
      </article>
    </section>

    <section>
      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <header class="flex items-center justify-between gap-3">
          <div>
            <h2 class="text-base font-semibold text-slate-900">
              {{ t('admin.routingQuality.suggestions') }}
            </h2>
            <p v-if="openSuggestions" class="mt-0.5 text-xs text-slate-400">
              {{ t('admin.routingQuality.openSuggestions', { count: openSuggestions }) }}
            </p>
          </div>
          <span
            class="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600"
          >
            {{ suggestions.length }}
          </span>
        </header>

        <div v-if="loading && !suggestions.length" class="mt-4 space-y-3">
          <div v-for="n in 2" :key="n" class="h-24 animate-pulse rounded-lg bg-slate-100" />
        </div>

        <p v-else-if="!suggestions.length" class="mt-4 text-sm text-slate-400">
          {{ t('admin.routingQuality.noSuggestions') }}
        </p>

        <ul v-else class="mt-4 grid gap-3 md:grid-cols-2">
          <li
            v-for="suggestion in suggestions"
            :key="`${suggestion.target_type}-${suggestion.target_id}-${suggestion.suggestion_type}`"
            class="flex flex-col rounded-lg border border-slate-200 bg-slate-50/60 p-4"
          >
            <div class="flex items-start justify-between gap-3">
              <span
                class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset"
                :class="severityBadgeClass(suggestion.severity)"
              >
                <span class="inline-block h-1.5 w-1.5 rounded-full bg-current opacity-70" />
                {{ severityLabel(suggestion.severity) }}
              </span>
              <span
                class="shrink-0 rounded-full px-2 py-0.5 text-xs font-medium"
                :class="statusBadgeClass(suggestion.status)"
              >
                {{ statusLabel(suggestion.status) }}
              </span>
            </div>
            <p class="mt-3 text-sm font-medium text-slate-800">
              <a-tooltip
                :content="suggestion.suggestion_type"
                :disabled="semanticLabel('suggestion_type', suggestion.suggestion_type, suggestion.suggestion_type) === suggestion.suggestion_type"
                position="top"
                mini
              >
                <span class="cursor-help">
                  {{ semanticLabel('suggestion_type', suggestion.suggestion_type, suggestion.suggestion_type) }}
                </span>
              </a-tooltip>
            </p>
            <p class="mt-1 text-xs text-slate-500">
              {{ t('admin.routingQuality.target') }}:
              {{ semanticLabel('target_type', suggestion.target_type, suggestion.target_type) }} /
              <a-tooltip
                v-if="isUuidLike(suggestion.target_id)"
                :content="suggestion.target_id"
                position="top"
                mini
              >
                <span class="cursor-help font-medium text-slate-600">{{ truncateId(suggestion.target_id) }}</span>
              </a-tooltip>
              <span v-else class="font-medium text-slate-600">{{ suggestion.target_id }}</span>
            </p>
            <p class="mt-2 text-sm leading-6 text-slate-600">
              <a-tooltip
                :content="suggestion.reason"
                :disabled="reasonLabel(suggestion) === suggestion.reason"
                position="top"
              >
                <span class="cursor-help">{{ reasonLabel(suggestion) }}</span>
              </a-tooltip>
            </p>
            <div
              v-if="suggestionActionKeys(suggestion).length"
              class="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3"
            >
              <button
                v-if="suggestionActionKeys(suggestion).includes('accept')"
                type="button"
                class="rounded-md px-2.5 py-1 text-xs font-medium text-sky-600 transition hover:bg-sky-50 disabled:cursor-not-allowed disabled:opacity-60"
                :disabled="actionLoading === `accept-${suggestion.id}`"
                @click="handleAccept(suggestion)"
              >
                {{ actionLoading === `accept-${suggestion.id}` ? '…' : t('policyChange.accept') }}
              </button>
              <button
                v-if="suggestionActionKeys(suggestion).includes('preview')"
                type="button"
                class="rounded-md px-2.5 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-100"
                @click="handlePreview(suggestion)"
              >
                {{ t('policyChange.preview') }}
              </button>
              <button
                v-if="suggestionActionKeys(suggestion).includes('apply')"
                type="button"
                class="rounded-md px-2.5 py-1 text-xs font-medium text-emerald-600 transition hover:bg-emerald-50"
                @click="openApply(suggestion)"
              >
                {{ t('policyChange.apply') }}
              </button>
              <button
                v-if="suggestionActionKeys(suggestion).includes('dismiss')"
                type="button"
                class="rounded-md px-2.5 py-1 text-xs font-medium text-red-500 transition hover:bg-red-50"
                @click="openDismiss(suggestion)"
              >
                {{ t('policyChange.dismiss') }}
              </button>
            </div>
          </li>
        </ul>
      </article>
    </section>

    <PolicyChangePreviewModal
      v-model:visible="previewVisible"
      :loading="previewLoading"
      :data="previewData"
    />

    <a-modal
      :visible="dismissVisible"
      :title="t('policyChange.dismiss')"
      :ok-text="t('common.actions.confirm')"
      :cancel-text="t('common.cancel')"
      :ok-loading="dismissSubmitting"
      @ok="submitDismiss"
      @cancel="dismissVisible = false"
    >
      <p class="text-sm text-slate-600">{{ t('policyChange.confirmDismiss') }}</p>
      <a-textarea
        v-model="dismissReason"
        class="mt-3"
        :placeholder="t('policyChange.dismissReason')"
        :max-length="200"
      />
    </a-modal>

    <a-modal
      :visible="applyConfirmVisible"
      :title="t('policyChange.apply')"
      :ok-text="t('common.actions.confirm')"
      :cancel-text="t('common.cancel')"
      :ok-loading="applySubmitting"
      @ok="submitApply"
      @cancel="applyConfirmVisible = false"
    >
      <p class="text-sm text-slate-600">{{ t('policyChange.confirmApply') }}</p>
    </a-modal>
  </section>
</template>
