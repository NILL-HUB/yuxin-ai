<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useAdminStore } from '@/stores/admin'
import type { AdminDashboardSummary } from '@/services/admin-dashboard'
import { getAdminDashboardSummary } from '@/services/admin-dashboard'
import { getErrorMessage } from '@/utils/error'
import { formatTimestampShort } from '@/utils/time-formatter'

const { t } = useI18n()
const adminStore = useAdminStore()

const loading = ref(false)
const loadedAt = ref(0)
const summary = ref<AdminDashboardSummary>({
  workflows: { total: 0, published: 0, draft: 0 },
  apps: { total: 0, published: 0 },
  users: { total: 0, active: 0 },
  models: { total: 0, active: 0 },
  agentPool: { total: 0, enabled: 0, healthy: 0 },
  mcp: { total: 0, published: 0 },
  tools: { total: 0 },
  skills: { total: 0, enabled: 0 },
  storage: { active_backend: '', files: 0, size: 0 },
  routing: {
    total_count: 0,
    success_count: 0,
    fallback_count: 0,
    total_credits: 0,
    avg_latency_ms: 0,
    agent_pool_hit_rate: 0,
    tool_pool_hit_rate: 0,
  },
  recentRoutingLogs: [],
  audits: [],
  recycleBin: 0,
  costs: { total_credits: 0, total_requests: 0, avg_cost_per_request: 0 },
})

const adminPermissions = computed(() => adminStore.admin.permissions)

const formatNumber = (value: number) => Number(value || 0).toLocaleString()

const formatSize = (size: number) => {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = size
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  const rounded = index === 0 ? Math.round(value) : Math.round(value * 10) / 10
  return `${rounded} ${units[index]}`
}

const auditActionLabel = (action: string) => {
  const labels: Record<string, string> = {
    create: t('admin.auditLogs.actionCreate'),
    update: t('admin.auditLogs.actionUpdate'),
    disable: t('admin.auditLogs.actionDisable'),
    enable: t('admin.auditLogs.actionEnable'),
    delete: t('admin.auditLogs.actionDelete'),
    reset_password: t('admin.auditLogs.actionResetPassword'),
    revoke_sessions: t('admin.auditLogs.actionRevokeSessions'),
    assign: t('admin.auditLogs.actionAssign'),
    revoke: t('admin.auditLogs.actionRevoke'),
  }
  return labels[action] || action
}

const routingStatusColor = (status: string) => {
  if (status === 'success') return 'green'
  if (status === 'fallback') return 'orange'
  return 'red'
}

const domainCards = computed(() => {
  const permissions = adminPermissions.value
  const cards = [
    {
      key: 'workflows',
      permission: 'workflow:read',
      title: t('admin.dashboard.workflows'),
      value: summary.value.workflows.total,
      details: [
        { label: t('admin.dashboard.published'), value: summary.value.workflows.published },
        { label: t('admin.dashboard.draft'), value: summary.value.workflows.draft },
      ],
    },
    {
      key: 'apps',
      permission: 'app:read',
      title: t('admin.dashboard.apps'),
      value: summary.value.apps.total,
      details: [{ label: t('admin.dashboard.published'), value: summary.value.apps.published }],
    },
    {
      key: 'users',
      permission: 'user:read',
      title: t('admin.dashboard.users'),
      value: summary.value.users.total,
      details: [{ label: t('admin.dashboard.active'), value: summary.value.users.active }],
    },
    {
      key: 'models',
      permission: 'model_pool:read',
      title: t('admin.dashboard.models'),
      value: summary.value.models.total,
      details: [{ label: t('admin.dashboard.active'), value: summary.value.models.active }],
    },
    {
      key: 'agentPool',
      permission: 'agent_pool:read',
      title: t('admin.dashboard.agentPool'),
      value: summary.value.agentPool.total,
      details: [
        { label: t('admin.dashboard.enabled'), value: summary.value.agentPool.enabled },
        { label: t('admin.dashboard.healthy'), value: summary.value.agentPool.healthy },
      ],
    },
    {
      key: 'mcp',
      permission: 'mcp:read',
      title: t('admin.dashboard.mcp'),
      value: summary.value.mcp.total,
      details: [{ label: t('admin.dashboard.published'), value: summary.value.mcp.published }],
    },
    {
      key: 'tools',
      permission: 'tool:read',
      title: t('admin.dashboard.tools'),
      value: summary.value.tools.total,
      details: [],
    },
    {
      key: 'skills',
      permission: 'skill:read',
      title: t('admin.dashboard.skills'),
      value: summary.value.skills.total,
      details: [{ label: t('admin.dashboard.enabled'), value: summary.value.skills.enabled }],
    },
  ]
  return cards.filter((card) => permissions.includes(card.permission))
})

const quickEntries = computed(() => {
  const permissions = adminPermissions.value
  return [
    {
      key: 'workflows',
      to: '/admin/workflows',
      permission: 'workflow:read',
      title: t('admin.dashboard.quickWorkflow'),
      description: t('admin.dashboard.quickWorkflowDescription'),
    },
    {
      key: 'apps',
      to: '/admin/apps',
      permission: 'app:read',
      title: t('admin.dashboard.quickApps'),
      description: t('admin.dashboard.quickAppsDescription'),
    },
    {
      key: 'users',
      to: '/admin/users',
      permission: 'user:read',
      title: t('admin.dashboard.quickUsers'),
      description: t('admin.dashboard.quickUsersDescription'),
    },
    {
      key: 'agentPool',
      to: '/admin/agent-pool',
      permission: 'agent_pool:read',
      title: t('admin.dashboard.quickAgentPool'),
      description: t('admin.dashboard.quickAgentPoolDescription'),
    },
    {
      key: 'models',
      to: '/admin/models',
      permission: 'model_pool:read',
      title: t('admin.dashboard.quickModels'),
      description: t('admin.dashboard.quickModelsDescription'),
    },
    {
      key: 'logs',
      to: '/admin/routing-logs',
      permission: 'routing_log:read',
      title: t('admin.dashboard.quickLogs'),
      description: t('admin.dashboard.quickLogsDescription'),
    },
    {
      key: 'audit',
      to: '/admin/audit-logs',
      permission: 'audit_log:read',
      title: t('admin.dashboard.quickAudit'),
      description: t('admin.dashboard.quickAuditDescription'),
    },
    {
      key: 'storage',
      to: '/admin/storage',
      permission: 'storage:read',
      title: t('admin.dashboard.quickStorage'),
      description: t('admin.dashboard.quickStorageDescription'),
    },
    {
      key: 'cost',
      to: '/admin/cost-stats',
      permission: 'cost_stats:read',
      title: t('admin.dashboard.quickCost'),
      description: t('admin.dashboard.quickCostDescription'),
    },
    {
      key: 'recycle',
      to: '/admin/recycle-bin',
      permission: 'recycle_bin:read',
      title: t('admin.dashboard.quickRecycle'),
      description: t('admin.dashboard.quickRecycleDescription'),
    },
  ].filter((entry) => permissions.includes(entry.permission))
})

const loadSummary = async () => {
  loading.value = true
  try {
    summary.value = await getAdminDashboardSummary(adminPermissions.value)
    loadedAt.value = Date.now()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.dashboard.loadFailed')))
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadSummary()
})
</script>

<template>
  <section class="space-y-8">
    <header class="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <p class="text-sm font-medium uppercase tracking-[0.2em] text-sky-600">
          {{ t('admin.dashboard.eyebrow') }}
        </p>
        <h1 class="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
          {{ t('admin.dashboard.title') }}
        </h1>
        <p class="mt-3 max-w-3xl text-sm leading-6 text-slate-500">
          {{ t('admin.dashboard.description') }}
        </p>
      </div>
      <a-button type="outline" :loading="loading" @click="loadSummary">
        {{ t('admin.dashboard.refresh') }}
      </a-button>
    </header>

    <section>
      <div class="flex items-end justify-between gap-4">
        <div>
          <h2 class="text-xl font-semibold text-slate-900">
            {{ t('admin.dashboard.resourceTitle') }}
          </h2>
          <p class="mt-1 text-sm text-slate-500">{{ t('admin.dashboard.resourceDescription') }}</p>
        </div>
        <p v-if="loadedAt" class="shrink-0 text-xs text-slate-400">
          {{ t('admin.dashboard.updatedAt', { time: new Date(loadedAt).toLocaleTimeString() }) }}
        </p>
      </div>

      <div class="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <article
          v-for="card in domainCards"
          :key="card.key"
          class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm"
        >
          <p class="text-sm font-medium text-slate-500">{{ card.title }}</p>
          <div class="mt-3 min-h-[2.75rem]">
            <div
              v-if="loading"
              class="h-11 w-20 animate-pulse rounded-lg bg-slate-100"
              aria-hidden="true"
            />
            <strong v-else class="block text-3xl font-semibold tracking-tight text-slate-900">
              {{ formatNumber(card.value) }}
            </strong>
          </div>
          <div v-if="card.details.length" class="mt-3 flex flex-wrap gap-x-4 gap-y-1">
            <span v-for="detail in card.details" :key="detail.label" class="text-sm text-slate-500">
              {{ detail.label }}
              <strong class="font-semibold text-slate-700">{{ formatNumber(detail.value) }}</strong>
            </span>
          </div>
        </article>
      </div>
    </section>

    <section class="grid gap-4 xl:grid-cols-3">
      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h2 class="text-lg font-semibold text-slate-900">
              {{ t('admin.dashboard.routingTitle') }}
            </h2>
            <p class="mt-1 text-sm text-slate-500">{{ t('admin.dashboard.routingDescription') }}</p>
          </div>
          <router-link
            v-if="adminPermissions.includes('routing_log:read')"
            to="/admin/routing-logs"
            class="shrink-0 text-sm font-medium text-sky-600 hover:underline"
          >
            {{ t('admin.dashboard.quickAction') }}
          </router-link>
        </div>
        <div class="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div>
            <p class="text-xs text-slate-500">{{ t('admin.dashboard.totalRequests') }}</p>
            <strong class="mt-1 block text-xl text-slate-900">{{
              formatNumber(summary.routing.total_count)
            }}</strong>
          </div>
          <div>
            <p class="text-xs text-slate-500">{{ t('admin.dashboard.successRequests') }}</p>
            <strong class="mt-1 block text-xl text-green-600">{{
              formatNumber(summary.routing.success_count)
            }}</strong>
          </div>
          <div>
            <p class="text-xs text-slate-500">{{ t('admin.dashboard.fallbackRequests') }}</p>
            <strong class="mt-1 block text-xl text-amber-600">{{
              formatNumber(summary.routing.fallback_count)
            }}</strong>
          </div>
          <div>
            <p class="text-xs text-slate-500">{{ t('admin.dashboard.avgLatency') }}</p>
            <strong class="mt-1 block text-xl text-slate-900"
              >{{ formatNumber(summary.routing.avg_latency_ms) }} ms</strong
            >
          </div>
          <div>
            <p class="text-xs text-slate-500">{{ t('admin.dashboard.totalCredits') }}</p>
            <strong class="mt-1 block text-xl text-slate-900">{{
              formatNumber(summary.routing.total_credits)
            }}</strong>
          </div>
        </div>
      </article>

      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h2 class="text-lg font-semibold text-slate-900">
              {{ t('admin.dashboard.storageTitle') }}
            </h2>
            <p class="mt-1 text-sm text-slate-500">{{ t('admin.dashboard.storageDescription') }}</p>
          </div>
          <router-link
            v-if="adminPermissions.includes('storage:read')"
            to="/admin/storage"
            class="shrink-0 text-sm font-medium text-sky-600 hover:underline"
          >
            {{ t('admin.dashboard.quickAction') }}
          </router-link>
        </div>
        <dl class="mt-4 space-y-3 text-sm">
          <div class="flex items-center justify-between border-b border-slate-100 pb-2">
            <dt class="text-slate-500">{{ t('admin.dashboard.activeBackend') }}</dt>
            <dd class="font-medium text-slate-800">{{ summary.storage.active_backend || '-' }}</dd>
          </div>
          <div class="flex items-center justify-between border-b border-slate-100 pb-2">
            <dt class="text-slate-500">{{ t('admin.dashboard.storedFiles') }}</dt>
            <dd class="font-medium text-slate-800">{{ formatNumber(summary.storage.files) }}</dd>
          </div>
          <div class="flex items-center justify-between">
            <dt class="text-slate-500">{{ t('admin.dashboard.storedSize') }}</dt>
            <dd class="font-medium text-slate-800">{{ formatSize(summary.storage.size) }}</dd>
          </div>
        </dl>
      </article>

      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h2 class="text-lg font-semibold text-slate-900">
              {{ t('admin.dashboard.operationsTitle') }}
            </h2>
            <p class="mt-1 text-sm text-slate-500">
              {{ t('admin.dashboard.operationsDescription') }}
            </p>
          </div>
          <router-link
            v-if="adminPermissions.includes('recycle_bin:read')"
            to="/admin/recycle-bin"
            class="shrink-0 text-sm font-medium text-sky-600 hover:underline"
          >
            {{ t('admin.dashboard.quickAction') }}
          </router-link>
        </div>
        <div class="mt-4 grid grid-cols-2 gap-3">
          <div>
            <p class="text-xs text-slate-500">{{ t('admin.dashboard.pendingRecycle') }}</p>
            <strong class="mt-1 block text-xl text-rose-600">{{
              formatNumber(summary.recycleBin)
            }}</strong>
          </div>
          <div>
            <p class="text-xs text-slate-500">{{ t('admin.dashboard.costCredits') }}</p>
            <strong class="mt-1 block text-xl text-slate-900">{{
              formatNumber(summary.costs.total_credits)
            }}</strong>
          </div>
          <div>
            <p class="text-xs text-slate-500">{{ t('admin.dashboard.costRequests') }}</p>
            <strong class="mt-1 block text-xl text-slate-900">{{
              formatNumber(summary.costs.total_requests)
            }}</strong>
          </div>
          <div>
            <p class="text-xs text-slate-500">{{ t('admin.dashboard.costAvg') }}</p>
            <strong class="mt-1 block text-xl text-slate-900">{{
              summary.costs.avg_cost_per_request
            }}</strong>
          </div>
        </div>
      </article>
    </section>

    <section class="grid gap-4 xl:grid-cols-2">
      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h2 class="text-lg font-semibold text-slate-900">
              {{ t('admin.dashboard.recentAuditTitle') }}
            </h2>
            <p class="mt-1 text-sm text-slate-500">{{ t('admin.dashboard.recentDescription') }}</p>
          </div>
          <router-link
            v-if="adminPermissions.includes('audit_log:read')"
            to="/admin/audit-logs"
            class="shrink-0 text-sm font-medium text-sky-600 hover:underline"
          >
            {{ t('admin.dashboard.quickAction') }}
          </router-link>
        </div>
        <ul v-if="summary.audits.length" class="mt-4">
          <li
            v-for="log in summary.audits"
            :key="log.id"
            class="flex items-start justify-between gap-3 border-b border-slate-100 py-3 last:border-0"
          >
            <div class="min-w-0">
              <p class="truncate text-sm font-medium text-slate-800">
                {{ auditActionLabel(log.action) }} · {{ log.resource_type || '-' }}
              </p>
              <p class="mt-1 truncate text-xs text-slate-400">
                {{ log.admin_user_name || log.account_name || '-' }} ·
                {{ formatTimestampShort(log.created_at) }}
              </p>
            </div>
            <a-tag size="small" color="arcoblue">{{ log.resource_type || '-' }}</a-tag>
          </li>
        </ul>
        <p v-else class="py-8 text-center text-sm text-slate-400">
          {{ t('admin.dashboard.empty') }}
        </p>
      </article>

      <article class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h2 class="text-lg font-semibold text-slate-900">
              {{ t('admin.dashboard.recentRoutingTitle') }}
            </h2>
            <p class="mt-1 text-sm text-slate-500">{{ t('admin.dashboard.recentDescription') }}</p>
          </div>
          <router-link
            v-if="adminPermissions.includes('routing_log:read')"
            to="/admin/routing-logs"
            class="shrink-0 text-sm font-medium text-sky-600 hover:underline"
          >
            {{ t('admin.dashboard.quickAction') }}
          </router-link>
        </div>
        <ul v-if="summary.recentRoutingLogs.length" class="mt-4">
          <li
            v-for="log in summary.recentRoutingLogs"
            :key="log.id"
            class="flex items-start justify-between gap-3 border-b border-slate-100 py-3 last:border-0"
          >
            <div class="min-w-0">
              <p class="truncate text-sm font-medium text-slate-800">
                {{ log.user_query || log.id }}
              </p>
              <p class="mt-1 truncate text-xs text-slate-400">
                {{ log.routing_decision?.execution_mode || '-' }} ·
                {{ formatTimestampShort(log.created_at) }}
              </p>
            </div>
            <a-tag size="small" :color="routingStatusColor(log.status)">{{ log.status }}</a-tag>
          </li>
        </ul>
        <p v-else class="py-8 text-center text-sm text-slate-400">
          {{ t('admin.dashboard.empty') }}
        </p>
      </article>
    </section>

    <section>
      <div>
        <h2 class="text-xl font-semibold text-slate-900">{{ t('admin.dashboard.quickTitle') }}</h2>
        <p class="mt-1 text-sm text-slate-500">{{ t('admin.dashboard.quickDescription') }}</p>
      </div>

      <div class="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <RouterLink
          v-for="entry in quickEntries"
          :key="entry.key"
          :to="entry.to"
          class="group flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-sky-200 hover:bg-sky-50"
        >
          <div class="min-w-0">
            <h3 class="truncate text-sm font-semibold text-slate-900">{{ entry.title }}</h3>
            <p class="mt-1 truncate text-xs leading-5 text-slate-500">{{ entry.description }}</p>
          </div>
          <svg
            class="shrink-0 text-sky-600 transition group-hover:translate-x-0.5"
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </RouterLink>
      </div>
    </section>
  </section>
</template>

<style scoped>
/* AICSS 化仪表盘卡片：更克制的边框与阴影，主色收敛到品牌蓝 */
.admin-layout :deep(article) {
  border-color: var(--aicss-border) !important;
  background: var(--aicss-surface) !important;
  box-shadow: var(--aicss-shadow-card) !important;
}

.admin-layout :deep(article:hover) {
  border-color: var(--aicss-border-strong) !important;
}

.admin-layout :deep(h1),
.admin-layout :deep(h2),
.admin-layout :deep(h3) {
  color: var(--aicss-text) !important;
}

.admin-layout :deep(p) {
  color: var(--aicss-muted) !important;
}

.admin-layout :deep(.text-slate-900),
.admin-layout :deep(.text-slate-800),
.admin-layout :deep(.text-slate-700),
.admin-layout :deep(.text-slate-500),
.admin-layout :deep(.text-slate-400) {
  color: var(--aicss-text-2) !important;
}

.admin-layout :deep(.text-sky-600),
.admin-layout :deep(.text-green-600),
.admin-layout :deep(.text-amber-600),
.admin-layout :deep(.text-rose-600) {
  color: var(--aicss-accent-text) !important;
}
</style>
