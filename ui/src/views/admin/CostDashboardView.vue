<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import {
  getCostStatsByDimension,
  getCostStatsOverview,
  getCostStatsTimeseries,
} from '@/services/admin-cost-stats'
import type {
  CostStatsByDimension,
  CostStatsOverview,
  CostStatsTimeseries,
} from '@/models/admin-cost-stats'
import { getErrorMessage } from '@/utils/error'
import AiDataTable from '@/components/ai-chat-ui/AiDataTable.vue'

const { t } = useI18n()
const loading = ref(false)
const overview = ref<CostStatsOverview | null>(null)
const dimensionData = ref<CostStatsByDimension | null>(null)
const timeseriesData = ref<CostStatsTimeseries | null>(null)

const filters = ref({
  start_at: '',
  end_at: '',
})

const dimension = ref('user')
const granularity = ref('day')
const dimensionPage = ref(1)
const DIMENSION_PAGE_SIZE = 10

const overviewCards = computed(() => [
  {
    key: 'total_credits',
    label: t('admin.costStats.totalCredits'),
    value: overview.value?.total_credits ?? 0,
  },
  {
    key: 'total_requests',
    label: t('admin.costStats.totalRequests'),
    value: overview.value?.total_requests ?? 0,
  },
  {
    key: 'avg_cost',
    label: t('admin.costStats.avgCost'),
    value: overview.value?.avg_cost_per_request ?? 0,
  },
  {
    key: 'total_tokens',
    label: t('admin.costStats.totalTokens'),
    value: (overview.value?.total_input_tokens ?? 0) + (overview.value?.total_output_tokens ?? 0),
  },
])

const dimensionOptions = computed(() => [
  { value: 'user', label: t('admin.costStats.user') },
  { value: 'model', label: t('admin.costStats.model') },
  { value: 'status', label: t('admin.costStats.status') },
  { value: 'agent_pool', label: t('admin.costStats.agentPool') },
  { value: 'source', label: t('admin.costStats.source') },
])

const dimensionValueLabel = (value: string) => {
  if (!value || value === 'unknown') return t('admin.costStats.unknown')
  if (dimension.value !== 'source') return value
  switch (value) {
    case 'schedule':
      return t('admin.costStats.sourceSchedule')
    case 'assistant_agent':
      return t('admin.costStats.sourceAssistantAgent')
    case 'debugger':
      return t('admin.costStats.sourceDebugger')
    default:
      return value
  }
}

const dimensionTableColumns = computed(() => [
  { key: 'dimension', label: t('admin.costStats.dimension') },
  { key: 'total_credits', label: t('admin.costStats.totalCreditsCol'), align: 'right' as const },
  { key: 'request_count', label: t('admin.costStats.requestCount'), align: 'right' as const },
  { key: 'avg_credits', label: t('admin.costStats.avgCredits'), align: 'right' as const },
  { key: 'percentage', label: t('admin.costStats.percentage'), align: 'right' as const },
])

const dimensionTableRows = computed(() =>
  (dimensionData.value?.items || []).map((item) => ({
    dimension: dimensionValueLabel(item.name),
    total_credits: item.total_credits,
    request_count: item.request_count,
    avg_credits: item.avg_credits,
    percentage: `${item.percentage}%`,
  })),
)

const pagedDimensionTableRows = computed(() => {
  const start = (Math.max(1, dimensionPage.value) - 1) * DIMENSION_PAGE_SIZE
  return dimensionTableRows.value.slice(start, start + DIMENSION_PAGE_SIZE)
})

const granularityOptions = computed(() => [
  { value: 'day', label: t('admin.costStats.day') },
  { value: 'hour', label: t('admin.costStats.hour') },
])

const loadData = async () => {
  loading.value = true
  dimensionPage.value = 1
  try {
    const [overviewResult, dimensionResult, timeseriesResult] = await Promise.all([
      getCostStatsOverview(filters.value),
      getCostStatsByDimension({ ...filters.value, dimension: dimension.value, limit: 100 }),
      getCostStatsTimeseries({ ...filters.value, granularity: granularity.value }),
    ])
    overview.value = overviewResult
    dimensionData.value = dimensionResult
    timeseriesData.value = timeseriesResult
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.costStats.loadFailed')))
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="space-y-6">
    <section class="rounded-3xl border border-slate-200 bg-white p-6">
      <h1 class="text-2xl font-semibold text-slate-900">{{ t('admin.costStats.title') }}</h1>
      <p class="mt-1 text-sm text-slate-500">{{ t('admin.costStats.description') }}</p>
    </section>

    <section class="rounded-2xl border border-slate-200 bg-white p-4">
      <div class="flex flex-wrap items-end gap-3">
        <div>
          <label class="mb-1 block text-xs text-slate-500">{{ t('admin.costStats.startAt') }}</label>
          <a-input v-model="filters.start_at" placeholder="1234567890" style="width: 180px" />
        </div>
        <div>
          <label class="mb-1 block text-xs text-slate-500">{{ t('admin.costStats.endAt') }}</label>
          <a-input v-model="filters.end_at" placeholder="1234567890" style="width: 180px" />
        </div>
        <a-button type="primary" :loading="loading" @click="loadData">
          {{ t('admin.costStats.search') }}
        </a-button>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article
        v-for="card in overviewCards"
        :key="card.key"
        class="rounded-lg border bg-white p-4"
      >
        <p class="text-sm text-gray-500">{{ card.label }}</p>
        <strong class="text-xl">{{ card.value }}</strong>
      </article>
    </section>

    <section class="rounded-2xl border border-slate-200 bg-white p-4">
      <div class="mb-3 flex items-center justify-between">
        <h2 class="text-lg font-semibold">{{ t('admin.costStats.timeseries') }}</h2>
        <a-select v-model="granularity" style="width: 120px" @change="loadData">
          <a-option
            v-for="opt in granularityOptions"
            :key="opt.value"
            :value="opt.value"
          >
            {{ opt.label }}
          </a-option>
        </a-select>
      </div>
      <div v-if="timeseriesData?.points.length" class="space-y-1">
        <div
          v-for="point in timeseriesData.points"
          :key="point.timestamp"
          class="flex items-center justify-between border-b py-1 text-sm last:border-0"
        >
          <span class="text-gray-600">{{ new Date(point.timestamp * 1000).toLocaleString() }}</span>
          <span class="font-medium">{{ point.total_credits }} credits ({{ point.request_count }} requests)</span>
        </div>
      </div>
      <p v-else class="py-8 text-center text-sm text-gray-400">{{ t('admin.costStats.noData') }}</p>
    </section>

    <section class="rounded-2xl border border-slate-200 bg-white p-4">
      <div class="mb-3 flex items-center justify-between">
        <h2 class="text-lg font-semibold">{{ t('admin.costStats.byDimension') }}</h2>
        <a-select v-model="dimension" style="width: 140px" @change="loadData">
          <a-option
            v-for="opt in dimensionOptions"
            :key="opt.value"
            :value="opt.value"
          >
            {{ opt.label }}
          </a-option>
        </a-select>
      </div>
      <ai-data-table
        v-if="dimensionData?.items.length"
        :columns="dimensionTableColumns"
        :rows="pagedDimensionTableRows"
      />
      <p v-else class="py-8 text-center text-sm text-gray-400">{{ t('admin.costStats.noData') }}</p>
      <div
        v-if="dimensionTableRows.length > DIMENSION_PAGE_SIZE"
        class="flex items-center justify-between gap-3 pt-4"
      >
        <span class="text-xs text-gray-500">
          {{ t('admin.costStats.totalItems', { total: dimensionTableRows.length }) }}
        </span>
        <a-pagination
          :current="dimensionPage"
          :page-size="DIMENSION_PAGE_SIZE"
          :total="dimensionTableRows.length"
          @change="(page: number) => (dimensionPage = page)"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.space-y-6 :deep(> section) {
  border-color: var(--aicss-border) !important;
  border-radius: var(--aicss-radius) !important;
  background: var(--aicss-surface) !important;
  box-shadow: var(--aicss-shadow-card) !important;
}

.space-y-6 :deep(h1),
.space-y-6 :deep(h2) {
  color: var(--aicss-text) !important;
}

.space-y-6 :deep(p),
.space-y-6 :deep(label) {
  color: var(--aicss-muted) !important;
}

.space-y-6 :deep(strong) {
  color: var(--aicss-text) !important;
}

@media (max-width: 640px) {
  .space-y-6 :deep(> section) {
    padding: 16px !important;
  }
}
</style>
