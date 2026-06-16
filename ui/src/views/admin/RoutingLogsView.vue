<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import { listAdminRoutingLogs } from '@/services/admin-routing-logs'
import type {
  AdminRoutingLogListResponse,
  AdminRoutingLogRecord,
  AdminRoutingLogSummary,
} from '@/models/admin-routing-log'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()
const loading = ref(false)
const logs = ref<AdminRoutingLogRecord[]>([])
const summary = ref<AdminRoutingLogSummary>({
  total_count: 0,
  success_count: 0,
  fallback_count: 0,
  total_credits: 0,
  avg_latency_ms: 0,
  agent_pool_hit_rate: 0,
  tool_pool_hit_rate: 0,
})

const filters = ref({
  current_page: 1,
  page_size: 20,
  account_id: '',
  status: '',
  agent_id: '',
  agent_pool: '',
  tool_name: '',
  tool_pool: '',
  model_id: '',
  key_id: '',
  start_at: '',
  end_at: '',
})

const loadRoutingLogs = async () => {
  loading.value = true
  try {
    const result = await listAdminRoutingLogs(filters.value)
    const data = result as AdminRoutingLogListResponse
    logs.value = data.list
    summary.value = data.summary
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.routingLogs.loadFailed')))
  } finally {
    loading.value = false
  }
}

onMounted(loadRoutingLogs)
</script>

<template>
  <section class="space-y-6 p-6">
    <header>
      <h1 class="text-2xl font-semibold text-gray-900">
        {{ t('admin.routingLogs.title') }}
      </h1>
      <p class="mt-1 text-sm text-gray-500">
        {{ t('admin.routingLogs.description') }}
      </p>
    </header>

    <div class="grid gap-4 md:grid-cols-5">
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.routingLogs.total') }}</p>
        <strong class="text-xl">{{ summary.total_count }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.routingLogs.success') }}</p>
        <strong class="text-xl">{{ summary.success_count }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.routingLogs.fallback') }}</p>
        <strong class="text-xl">{{ summary.fallback_count }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.routingLogs.credits') }}</p>
        <strong class="text-xl">{{ summary.total_credits }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.routingLogs.avgLatency') }}</p>
        <strong class="text-xl">{{ summary.avg_latency_ms }} ms</strong>
      </article>
    </div>

    <div class="rounded-lg border bg-white p-4">
      <h2 class="mb-3 text-lg font-medium">{{ t('admin.routingLogs.filters') }}</h2>
      <div class="grid gap-3 md:grid-cols-4">
        <a-input v-model="filters.account_id" :placeholder="t('admin.routingLogs.account')" />
        <a-input v-model="filters.agent_id" :placeholder="t('admin.routingLogs.agent')" />
        <a-input v-model="filters.tool_name" :placeholder="t('admin.routingLogs.tool')" />
        <a-input v-model="filters.model_id" :placeholder="t('admin.routingLogs.model')" />
        <a-input v-model="filters.key_id" :placeholder="t('admin.routingLogs.key')" />
        <a-input v-model="filters.status" :placeholder="t('admin.routingLogs.status')" />
        <a-input v-model="filters.start_at" :placeholder="t('admin.routingLogs.startAt')" />
        <a-input v-model="filters.end_at" :placeholder="t('admin.routingLogs.endAt')" />
      </div>
      <a-button class="mt-3" :loading="loading" @click="loadRoutingLogs">
        {{ t('admin.routingLogs.search') }}
      </a-button>
    </div>

    <div class="overflow-hidden rounded-lg border bg-white">
      <table class="w-full text-left text-sm">
        <thead class="bg-gray-50 text-gray-500">
          <tr>
            <th class="p-3">{{ t('admin.routingLogs.userQuery') }}</th>
            <th class="p-3">{{ t('admin.routingLogs.classification') }}</th>
            <th class="p-3">{{ t('admin.routingLogs.model') }}</th>
            <th class="p-3">{{ t('admin.routingLogs.agentPool') }}</th>
            <th class="p-3">{{ t('admin.routingLogs.toolPool') }}</th>
            <th class="p-3">{{ t('admin.routingLogs.credits') }}</th>
            <th class="p-3">{{ t('admin.routingLogs.latency') }}</th>
            <th class="p-3">{{ t('admin.routingLogs.status') }}</th>
            <th class="p-3">{{ t('admin.routingLogs.fallbackReason') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="log in logs" :key="log.id" class="border-t">
            <td class="p-3">{{ log.user_query || '-' }}</td>
            <td class="p-3">{{ log.task_classification.complexity || '-' }}</td>
            <td class="p-3">{{ log.model_selection.model_id || '-' }}</td>
            <td class="p-3">{{ log.agent_pool_hits[0]?.pool || '-' }}</td>
            <td class="p-3">{{ log.tool_pool_hits[0]?.pool || '-' }}</td>
            <td class="p-3">{{ log.cost_summary.total_credits || 0 }}</td>
            <td class="p-3">{{ log.latency_ms }} ms</td>
            <td class="p-3">{{ log.status }}</td>
            <td class="p-3">{{ log.fallback_reason || '-' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
