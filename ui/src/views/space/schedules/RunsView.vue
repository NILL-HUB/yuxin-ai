<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import { formatTimestampLong } from '@/utils/time-formatter'
import {
  listScheduleTaskRuns,
  listScheduleTasks,
  type ScheduleTaskItem,
  type ScheduleTaskRunItem,
} from '@/services/schedule-task'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const isAdminContext = computed(() => route.path.startsWith('/admin') || route.meta.realm === 'admin')
const taskId = computed(() => String(route.params.task_id || ''))

// 任务信息：优先从跳转 query 读取，缺失时兜底从列表接口匹配
const taskName = ref(String(route.query.name || ''))
const cronExpression = ref(String(route.query.cron || ''))
const cronHumanized = ref(String(route.query.cron_humanized || ''))

const loading = ref(false)
const runs = ref<ScheduleTaskRunItem[]>([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const reportVisible = ref(false)
const currentRun = ref<ScheduleTaskRunItem | null>(null)

const successCount = computed(() => runs.value.filter((r) => r.status === 'success').length)
const failedCount = computed(() => runs.value.filter((r) => r.status === 'failed').length)
const runningCount = computed(() => runs.value.filter((r) => r.status === 'running').length)

const statusColor = (status: string) => {
  if (status === 'success') return 'green'
  if (status === 'failed') return 'red'
  if (status === 'running') return 'arcoblue'
  return 'gray'
}

const statusText = (status: string) => {
  if (status === 'success') return t('space.schedules.lastRunStatus.success')
  if (status === 'failed') return t('space.schedules.lastRunStatus.failed')
  if (status === 'running') return t('space.schedules.lastRunStatus.running')
  return status
}

const triggerText = (source: string) =>
  source === 'manual' ? t('space.schedules.triggerManual') : t('space.schedules.triggerSchedule')

const durationText = (run: ScheduleTaskRunItem) => {
  if (run.duration_seconds === 0 && run.status === 'running') return '-'
  if (run.duration_seconds < 60) return `${run.duration_seconds}秒`
  const minutes = Math.floor(run.duration_seconds / 60)
  const seconds = run.duration_seconds % 60
  return `${minutes}分${seconds}秒`
}

const loadTaskMeta = async () => {
  if (taskName.value && cronExpression.value) return
  try {
    const res = await listScheduleTasks(1, 100, isAdminContext.value)
    const task = res.data.items.find((item: ScheduleTaskItem) => item.id === taskId.value)
    if (task) {
      taskName.value = task.name
      cronExpression.value = task.cron_expression
      cronHumanized.value = task.cron_humanized || ''
    }
  } catch (error: unknown) {
    console.error('load task meta failed', error)
  }
}

const loadRuns = async () => {
  loading.value = true
  try {
    const res = await listScheduleTaskRuns(taskId.value, page.value, pageSize.value, isAdminContext.value)
    runs.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('space.schedules.runsLoadFailed')))
  } finally {
    loading.value = false
  }
}

const openReport = (run: ScheduleTaskRunItem) => {
  currentRun.value = run
  reportVisible.value = true
}

const goBack = () => {
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push(isAdminContext.value ? { name: 'admin-schedules' } : { name: 'user-schedules' })
  }
}

onMounted(() => {
  loadTaskMeta()
  loadRuns()
})
</script>

<template>
  <div class="schedule-runs-page mx-auto w-full max-w-4xl p-6">
    <!-- 顶栏 -->
    <div class="mb-5 flex items-center gap-3">
      <a-button class="rounded-lg" @click="goBack">{{ t('space.schedules.back') }}</a-button>
      <h1 class="truncate text-lg font-semibold text-gray-900">{{ taskName }}</h1>
      <a-tag color="arcoblue" size="small" class="flex-shrink-0">{{ cronExpression }}</a-tag>
      <span class="ml-auto flex-shrink-0 text-xs text-gray-500">
        {{ t('space.schedules.totalRuns', { count: total }) }}
      </span>
    </div>

    <!-- 统计 -->
    <div class="mb-5 grid grid-cols-3 gap-3">
      <div class="rounded-lg border border-gray-200 bg-white p-4">
        <div class="text-xs text-gray-500">{{ t('space.schedules.runsSuccess') }}</div>
        <div class="mt-1 text-2xl font-semibold text-green-600">{{ successCount }}</div>
      </div>
      <div class="rounded-lg border border-gray-200 bg-white p-4">
        <div class="text-xs text-gray-500">{{ t('space.schedules.runsFailed') }}</div>
        <div class="mt-1 text-2xl font-semibold text-red-600">{{ failedCount }}</div>
      </div>
      <div class="rounded-lg border border-gray-200 bg-white p-4">
        <div class="text-xs text-gray-500">{{ t('space.schedules.runsRunning') }}</div>
        <div class="mt-1 text-2xl font-semibold text-arcoblue-600">{{ runningCount }}</div>
      </div>
    </div>

    <!-- 执行记录列表 -->
    <a-spin :loading="loading" class="block w-full">
      <a-empty
        v-if="!loading && runs.length === 0"
        :description="t('space.schedules.runsEmpty')"
        class="rounded-lg border border-gray-200 bg-white py-16"
      />
      <div v-else class="space-y-3">
        <div
          v-for="run in runs"
          :key="run.id"
          class="rounded-lg border border-gray-200 bg-white p-4"
        >
          <div class="mb-2 flex items-center justify-between gap-2">
            <div class="flex items-center gap-2">
              <a-tag :color="statusColor(run.status)" size="small">
                {{ statusText(run.status) }}
              </a-tag>
              <a-tag size="small" color="gray">{{ triggerText(run.trigger_source) }}</a-tag>
            </div>
            <div class="flex-shrink-0 text-xs text-gray-500">
              {{ formatTimestampLong(run.started_at) }}
              <span class="mx-1">·</span>
              {{ t('space.schedules.runDuration') }} {{ durationText(run) }}
            </div>
          </div>
          <div class="mb-3 line-clamp-2 whitespace-pre-wrap break-all text-sm text-gray-700">
            {{ run.result_summary || run.error_message || t('space.schedules.noReport') }}
          </div>
          <a-button size="mini" class="rounded-lg" @click="openReport(run)">
            {{ t('space.schedules.viewReport') }}
          </a-button>
        </div>
      </div>
      <div v-if="total > pageSize" class="mt-4 flex justify-end">
        <a-pagination
          v-model:current="page"
          :total="total"
          :page-size="pageSize"
          :show-total="true"
          @change="loadRuns"
        />
      </div>
    </a-spin>

    <!-- 执行报告抽屉 -->
    <a-drawer
      :visible="reportVisible"
      :title="t('space.schedules.reportTitle')"
      :width="640"
      :footer="false"
      @cancel="reportVisible = false"
    >
      <div v-if="currentRun" class="flex flex-col gap-4">
        <div class="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm">
          <div class="mb-1 flex items-center gap-2">
            <a-tag :color="statusColor(currentRun.status)" size="small">
              {{ statusText(currentRun.status) }}
            </a-tag>
            <a-tag size="small" color="gray">{{ triggerText(currentRun.trigger_source) }}</a-tag>
          </div>
          <div class="mt-2 space-y-1 text-xs text-gray-600">
            <div>
              {{ t('space.schedules.runAt') }}：{{ formatTimestampLong(currentRun.started_at) }}
            </div>
            <div>
              {{ t('space.schedules.runFinishedAt') }}：
              {{ currentRun.finished_at ? formatTimestampLong(currentRun.finished_at) : '-' }}
            </div>
            <div>
              {{ t('space.schedules.runDuration') }}：{{ durationText(currentRun) }}
            </div>
          </div>
        </div>

        <div>
          <div class="mb-2 text-sm font-semibold text-gray-800">
            {{ t('space.schedules.reportContent') }}
          </div>
          <div
            class="max-h-[420px] overflow-auto whitespace-pre-wrap break-all rounded-lg border border-gray-200 bg-white p-4 text-sm leading-relaxed text-gray-800"
          >
            {{ currentRun.result_summary || t('space.schedules.noReport') }}
          </div>
        </div>

        <div v-if="currentRun.error_message">
          <div class="mb-2 text-sm font-semibold text-red-600">
            {{ t('space.schedules.errorDetail') }}
          </div>
          <div
            class="max-h-[200px] overflow-auto whitespace-pre-wrap break-all rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
          >
            {{ currentRun.error_message }}
          </div>
        </div>
      </div>
    </a-drawer>
  </div>
</template>
