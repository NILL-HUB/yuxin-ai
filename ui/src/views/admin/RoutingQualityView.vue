<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import type {
  AdminRoutingOptimizationSuggestion,
  AdminRoutingQualityMetrics,
} from '@/models/admin-routing-quality'
import {
  getAdminRoutingQualityMetrics,
  listAdminRoutingQualitySuggestions,
} from '@/services/admin-routing-quality'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()
const loading = ref(false)
const metrics = ref<AdminRoutingQualityMetrics | null>(null)
const suggestions = ref<AdminRoutingOptimizationSuggestion[]>([])

const cards = computed(() => [
  { label: t('admin.routingQuality.totalCount'), value: metrics.value?.total_count ?? 0 },
  { label: t('admin.routingQuality.feedbackCount'), value: metrics.value?.feedback_count ?? 0 },
  { label: t('admin.routingQuality.avgRating'), value: metrics.value?.avg_rating ?? 0 },
  { label: t('admin.routingQuality.fallbackRate'), value: metrics.value?.fallback_rate ?? 0 },
  { label: t('admin.routingQuality.avgLatency'), value: metrics.value?.avg_latency_ms ?? 0 },
  { label: t('admin.routingQuality.avgCost'), value: metrics.value?.avg_cost_credits ?? 0 },
])

const loadData = async () => {
  loading.value = true
  try {
    const [metricsResult, suggestionsResult] = await Promise.all([
      getAdminRoutingQualityMetrics(),
      listAdminRoutingQualitySuggestions(),
    ])
    metrics.value = metricsResult
    suggestions.value = suggestionsResult
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.routingQuality.loadFailed')))
  } finally {
    loading.value = false
  }
}

const groupEntries = (group?: Record<string, { count: number; avg_rating: number }>) => {
  return Object.entries(group || {})
}

onMounted(loadData)
</script>

<template>
  <section class="space-y-6 p-6">
    <header>
      <h1 class="text-2xl font-semibold text-gray-900">
        {{ t('admin.routingQuality.title') }}
      </h1>
      <p class="mt-1 text-sm text-gray-500">
        {{ t('admin.routingQuality.description') }}
      </p>
    </header>

    <div class="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
      <article v-for="card in cards" :key="card.label" class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ card.label }}</p>
        <strong class="text-xl">{{ card.value }}</strong>
      </article>
    </div>

    <div class="grid gap-4 md:grid-cols-2">
      <article class="rounded-lg border bg-white p-4">
        <h2 class="font-semibold">{{ t('admin.routingQuality.byTaskType') }}</h2>
        <p v-if="!groupEntries(metrics?.quality_by_task_type).length" class="mt-3 text-sm text-gray-500">
          {{ t('admin.routingQuality.empty') }}
        </p>
        <ul class="mt-3 space-y-2">
          <li v-for="[key, item] in groupEntries(metrics?.quality_by_task_type)" :key="key">
            {{ key }} · {{ item.count }} · {{ item.avg_rating }}
          </li>
        </ul>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <h2 class="font-semibold">{{ t('admin.routingQuality.suggestions') }}</h2>
        <p v-if="!suggestions.length" class="mt-3 text-sm text-gray-500">
          {{ t('admin.routingQuality.empty') }}
        </p>
        <ul class="mt-3 space-y-3">
          <li v-for="suggestion in suggestions" :key="`${suggestion.target_type}-${suggestion.target_id}-${suggestion.suggestion_type}`" class="rounded border p-3">
            <p class="font-medium">{{ suggestion.severity }} · {{ suggestion.suggestion_type }}</p>
            <p class="text-sm text-gray-500">{{ suggestion.target_type }}: {{ suggestion.target_id }}</p>
            <p class="mt-1 text-sm">{{ suggestion.reason }}</p>
          </li>
        </ul>
      </article>
    </div>
  </section>
</template>
