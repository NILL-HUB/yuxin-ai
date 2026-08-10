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

const granularityOptions = computed(() => [
  { value: 'day', label: t('admin.costStats.day') },
  { value: 'hour', label: t('admin.costStats.hour') },
])

const loadData = async () => {
  loading.value = true
  try {
    const [overviewResult, dimensionResult, timeseriesResult] = await Promise.all([
      getCostStatsOverview(filters.value),
      getCostStatsByDimension({ ...filters.value, dimension: dimension.value, limit: 10 }),
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
      <table v-if="dimensionData?.items.length" class="w-full text-left text-sm">
        <thead class="bg-gray-50 text-gray-500">
          <tr>
            <th class="p-3">{{ t('admin.costStats.dimension') }}</th>
            <th class="p-3">{{ t('admin.costStats.totalCreditsCol') }}</th>
            <th class="p-3">{{ t('admin.costStats.requestCount') }}</th>
            <th class="p-3">{{ t('admin.costStats.avgCredits') }}</th>
            <th class="p-3">{{ t('admin.costStats.percentage') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in dimensionData.items" :key="item.name" class="border-b">
            <td class="p-3 font-medium">{{ dimensionValueLabel(item.name) }}</td>
            <td class="p-3">{{ item.total_credits }}</td>
            <td class="p-3">{{ item.request_count }}</td>
            <td class="p-3">{{ item.avg_credits }}</td>
            <td class="p-3">{{ item.percentage }}%</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="py-8 text-center text-sm text-gray-400">{{ t('admin.costStats.noData') }}</p>
    </section>
  </div>
</template>
