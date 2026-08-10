<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useGetWorkflowRuns } from '@/hooks/use-workflow-run'
import type { WorkflowRun, WorkflowRunStatus, WorkflowTriggerSource } from '@/models/workflow-run'
import WorkflowRunReplayPanel from './WorkflowRunReplayPanel.vue'

// 1.定义组件所需要使用的数据
const props = defineProps({
  visible: { type: Boolean, required: true },
  workflow_id: { type: String, default: '' },
})
const emits = defineEmits(['update:visible'])
const { t } = useI18n()
const { loading, runs, paginator, loadRuns } = useGetWorkflowRuns()

// 2.回放面板状态
const replayVisible = ref(false)
const replayRunId = ref('')

type BadgeStatus = 'success' | 'processing' | 'warning' | 'normal' | 'danger'

// 3.状态徽标颜色映射
const statusColorMap: Record<WorkflowRunStatus, string> = {
  running: 'blue',
  succeeded: 'green',
  failed: 'red',
  stopped: 'gray',
}

// 4.触发源标签映射
const triggerLabelKey: Record<WorkflowTriggerSource, string> = {
  debug: 'appStudio.debug.executionHistory.trigger.debug',
  app: 'appStudio.debug.executionHistory.trigger.app',
  schedule: 'appStudio.debug.executionHistory.trigger.schedule',
  api: 'appStudio.debug.executionHistory.trigger.api',
}

// 5.格式化耗时（秒）
const formatElapsed = (val: number | undefined | null): string => {
  if (val === undefined || val === null) return '-'
  return `${Number(val).toFixed(3)}s`
}

// 6.格式化创建时间（ISO 字符串）
const formatCreatedAt = (val: string | null | undefined): string => {
  if (!val) return '-'
  const date = new Date(val)
  if (Number.isNaN(date.getTime())) return val
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

// 7.定义滚动分页函数
const handleScroll = async (event: UIEvent) => {
  const { scrollTop, scrollHeight, clientHeight } = event.target as HTMLElement
  if (scrollTop + clientHeight >= scrollHeight - 10) {
    if (loading.value) return
    if (!props.workflow_id) return
    await loadRuns(props.workflow_id, {}, false)
  }
}

// 8.点击查看回放
const onViewReplay = (run: WorkflowRun) => {
  replayRunId.value = run.id
  replayVisible.value = true
}

// 9.监听visible属性
watch(
  () => props.visible,
  async (newValue) => {
    if (newValue) {
      if (props.workflow_id) {
        await loadRuns(props.workflow_id, {}, true)
      }
    } else {
      runs.value.splice(0, runs.value.length)
    }
  },
)
</script>

<template>
  <!-- 执行历史抽屉组件 -->
  <a-drawer
    :visible="props.visible"
    :title="t('appStudio.debug.executionHistory.title')"
    :width="520"
    :footer="false"
    :drawer-style="{ backgroundColor: '#f9fafb' }"
    @cancel="() => emits('update:visible', false)"
  >
    <a-spin
      :loading="loading && runs.length === 0"
      class="block h-full w-full scrollbar-w-none overflow-scroll"
      @scroll="handleScroll"
    >
      <!-- 空数据状态 -->
      <a-empty
        v-if="!loading && runs.length === 0"
        :description="t('appStudio.debug.executionHistory.empty')"
        class="my-10"
      />
      <!-- 执行记录列表 -->
      <a-card
        v-for="run in runs"
        :key="run.id"
        hoverable
        class="rounded-lg mb-4 cursor-pointer group"
      >
        <div class="flex flex-col gap-2">
          <!-- 顶部：状态徽标 + 触发源标签 + 创建时间 -->
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <!-- 状态徽标 -->
              <a-badge
                v-if="run.status === 'running'"
                status="processing"
                :text="t(`appStudio.debug.executionHistory.status.${run.status}`)"
              />
              <a-badge
                v-else
                :status="(statusColorMap[run.status] || 'gray') as BadgeStatus"
                :text="t(`appStudio.debug.executionHistory.status.${run.status}`)"
              />
              <!-- 触发源标签 -->
              <a-tag
                size="small"
                class="text-gray-700 rounded-lg !border !border-gray-100"
              >
                {{ t(triggerLabelKey[run.trigger_source]) }}
              </a-tag>
            </div>
            <div class="text-xs text-gray-500">
              {{ t('appStudio.debug.executionHistory.createdAt') }}:
              {{ formatCreatedAt(run.created_at) }}
            </div>
          </div>
          <!-- 中间：运行 ID -->
          <div class="text-xs text-gray-400 break-all">
            ID: {{ run.id }}
          </div>
          <!-- 底部：指标 + 查看回放按钮 -->
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-4 text-xs text-gray-600">
              <span>
                {{ t('appStudio.debug.executionHistory.totalElapsed') }}:
                <span class="font-medium text-gray-800">{{ formatElapsed(run.elapsed_time) }}</span>
              </span>
              <span>
                {{ t('appStudio.debug.executionHistory.totalSteps') }}:
                <span class="font-medium text-gray-800">{{ run.total_steps }}</span>
              </span>
            </div>
            <a-button
              size="small"
              type="text"
              class="rounded-lg !text-blue-700"
              @click.stop="onViewReplay(run)"
            >
              {{ t('appStudio.debug.executionHistory.viewReplay') }}
            </a-button>
          </div>
        </div>
      </a-card>
      <!-- 数据加载状态 -->
      <div v-if="paginator.total_page >= 2" class="flex items-center justify-center">
        <a-space v-if="loading" class="my-4">
          <a-spin />
          <div class="text-gray-400">{{ t('appStudio.debug.executionHistory.loadingMore') }}</div>
        </a-space>
        <div
          v-else-if="paginator.current_page > paginator.total_page"
          class="text-gray-400 my-4"
        >
          {{ t('appStudio.debug.executionHistory.loadedAll') }}
        </div>
      </div>
    </a-spin>
    <!-- 执行回放面板 -->
    <WorkflowRunReplayPanel
      v-model:visible="replayVisible"
      :workflow_id="props.workflow_id"
      :run_id="replayRunId"
    />
  </a-drawer>
</template>

<style scoped></style>
