<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import AdminOverviewCard from '@/components/admin/AdminOverviewCard.vue'
import type { AdminDashboardSummary } from '@/services/admin-dashboard'
import { getAdminDashboardSummary } from '@/services/admin-dashboard'
import { getErrorMessage } from '@/utils/error'

/**
 * 后台首页轻量骨架，负责展示工作流概览和常用管理入口。
 */
const { t } = useI18n()
const loading = ref(false)
const summary = ref<AdminDashboardSummary>({
  workflow_total: 0,
  workflow_published: 0,
  workflow_draft: 0,
})

const overviewCards = computed(() => [
  {
    key: 'workflow_total',
    title: t('admin.dashboard.total'),
    value: summary.value.workflow_total,
    description: t('admin.dashboard.totalDescription'),
  },
  {
    key: 'workflow_published',
    title: t('admin.dashboard.published'),
    value: summary.value.workflow_published,
    description: t('admin.dashboard.publishedDescription'),
  },
  {
    key: 'workflow_draft',
    title: t('admin.dashboard.draft'),
    value: summary.value.workflow_draft,
    description: t('admin.dashboard.draftDescription'),
  },
])

const quickEntries = computed(() => [
  {
    key: 'workflow',
    to: '/admin/workflows',
    title: t('admin.dashboard.quickWorkflow'),
    description: t('admin.dashboard.quickWorkflowDescription'),
  },
  {
    key: 'apps',
    to: '/admin/apps',
    title: t('admin.dashboard.quickApps'),
    description: t('admin.dashboard.quickAppsDescription'),
  },
  {
    key: 'logs',
    to: '/admin/routing-logs',
    title: t('admin.dashboard.quickLogs'),
    description: t('admin.dashboard.quickLogsDescription'),
  },
])

/**
 * 拉取后台首页的工作流聚合摘要。
 */
const loadSummary = async () => {
  loading.value = true
  try {
    summary.value = await getAdminDashboardSummary()
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
    <header class="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <p class="text-sm font-medium uppercase tracking-[0.2em] text-sky-600">
        {{ t('admin.dashboard.eyebrow') }}
      </p>
      <h1 class="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
        {{ t('admin.dashboard.title') }}
      </h1>
      <p class="mt-3 max-w-3xl text-sm leading-6 text-slate-500">
        {{ t('admin.dashboard.description') }}
      </p>
    </header>

    <section class="grid gap-4 xl:grid-cols-3">
      <AdminOverviewCard
        v-for="card in overviewCards"
        :key="card.key"
        :title="card.title"
        :value="card.value"
        :description="card.description"
        :loading="loading"
      />
    </section>

    <section class="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div class="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 class="text-xl font-semibold text-slate-900">{{ t('admin.dashboard.quickTitle') }}</h2>
          <p class="mt-1 text-sm text-slate-500">
            {{ t('admin.dashboard.quickDescription') }}
          </p>
        </div>
      </div>

      <div class="mt-6 grid gap-4 xl:grid-cols-3">
        <RouterLink
          v-for="entry in quickEntries"
          :key="entry.key"
          :to="entry.to"
          class="group rounded-2xl border border-slate-200 bg-slate-50 p-5 transition hover:-translate-y-0.5 hover:border-sky-200 hover:bg-sky-50"
        >
          <div class="flex items-start justify-between gap-4">
            <div>
              <h3 class="text-base font-semibold text-slate-900">{{ entry.title }}</h3>
              <p class="mt-2 text-sm leading-6 text-slate-500">{{ entry.description }}</p>
            </div>
            <span class="text-sm font-medium text-sky-600">
              {{ t('admin.dashboard.quickAction') }}
            </span>
          </div>
        </RouterLink>
      </div>
    </section>
  </section>
</template>
