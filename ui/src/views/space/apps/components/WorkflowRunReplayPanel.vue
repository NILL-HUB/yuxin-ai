<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  useGetWorkflowNodeExecutions,
  useGetWorkflowRun,
} from '@/hooks/use-workflow-run'
import type {
  WorkflowNodeExecution,
  WorkflowNodeExecutionStatus,
  WorkflowRunStatus,
} from '@/models/workflow-run'

// 1.组件 props 与 emits
const props = defineProps({
  visible: { type: Boolean, required: true, default: false },
  workflow_id: { type: String, default: '' },
  run_id: { type: String, default: '' },
})
const emits = defineEmits(['update:visible'])
const { t } = useI18n()

// 2.hook 与响应式状态
const { loading: runLoading, run, loadRun } = useGetWorkflowRun()
const {
  loading: nodesLoading,
  nodeExecutions,
  loadNodeExecutions,
} = useGetWorkflowNodeExecutions()

const loading = computed(() => runLoading.value || nodesLoading.value)
const expandedNodeIds = ref<Set<string>>(new Set())

// 3.状态徽标颜色映射
const statusColorMap: Record<WorkflowRunStatus, string> = {
  running: 'blue',
  succeeded: 'green',
  failed: 'red',
  stopped: 'gray',
}

const nodeStatusColorMap: Record<WorkflowNodeExecutionStatus, string> = {
  running: 'blue',
  succeeded: 'green',
  failed: 'red',
  skipped: 'gray',
}

// 4.计算属性
const inputsJson = computed(() => {
  const inputs = run.value?.inputs
  if (!inputs || Object.keys(inputs).length === 0) return ''
  return formatJson(inputs)
})

const hasInputs = computed(() => {
  const inputs = run.value?.inputs
  return inputs !== undefined && inputs !== null && Object.keys(inputs).length > 0
})

const outputsJson = computed(() => {
  const outputs = run.value?.outputs
  if (!outputs || Object.keys(outputs).length === 0) return ''
  return formatJson(outputs)
})

const hasOutputs = computed(() => {
  const outputs = run.value?.outputs
  return outputs !== undefined && outputs !== null && Object.keys(outputs).length > 0
})

const hasError = computed(() => {
  return !!run.value?.error
})

// 5.工具函数
const formatJson = (obj: any): string => {
  if (obj === undefined || obj === null) return ''
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

const formatElapsed = (val: number | undefined | null): string => {
  if (val === undefined || val === null) return '-'
  return `${Number(val).toFixed(3)}s`
}

const formatCreatedAt = (val: string | null | undefined): string => {
  if (!val) return '-'
  const date = new Date(val)
  if (Number.isNaN(date.getTime())) return val
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

// 6.节点展开/收起
const toggleNodeExpand = (node: WorkflowNodeExecution) => {
  if (expandedNodeIds.value.has(node.id)) {
    expandedNodeIds.value.delete(node.id)
  } else {
    expandedNodeIds.value.add(node.id)
  }
}

const isNodeExpanded = (node: WorkflowNodeExecution) => expandedNodeIds.value.has(node.id)

// 7.关闭时重置状态
const onVisibleChange = (val: boolean) => {
  emits('update:visible', val)
  if (!val) {
    run.value = null
    nodeExecutions.value = []
    expandedNodeIds.value = new Set()
  }
}

// 8.监听visible属性，打开时加载数据
watch(
  () => props.visible,
  async (val) => {
    if (val) {
      expandedNodeIds.value = new Set()
      if (props.workflow_id && props.run_id) {
        await Promise.all([
          loadRun(props.workflow_id, props.run_id),
          loadNodeExecutions(props.workflow_id, props.run_id),
        ])
      }
    }
  },
)
</script>

<template>
  <a-drawer
    :visible="props.visible"
    :title="t('appStudio.debug.executionHistory.runDetail')"
    :width="600"
    :footer="false"
    :drawer-style="{ backgroundColor: '#f9fafb' }"
    @cancel="onVisibleChange(false)"
  >
    <a-spin :loading="loading" class="block h-full w-full scrollbar-w-none overflow-scroll">
      <!-- 顶部 Run 概览 -->
      <div class="flex flex-col gap-3">
        <div class="flex items-center flex-wrap gap-4">
          <!-- 状态徽标 -->
          <a-badge
            v-if="run"
            :status="statusColorMap[run.status] || 'gray'"
            :text="t(`appStudio.debug.executionHistory.status.${run.status}`)"
          />
          <span class="text-sm text-gray-600">
            {{ t('appStudio.debug.executionHistory.totalElapsed') }}:
            <span class="font-medium text-gray-800">{{ formatElapsed(run?.elapsed_time) }}</span>
          </span>
          <span class="text-sm text-gray-600">
            {{ t('appStudio.debug.executionHistory.totalSteps') }}:
            <span class="font-medium text-gray-800">{{ run?.total_steps ?? 0 }}</span>
          </span>
          <span class="text-sm text-gray-600">
            {{ t('appStudio.debug.executionHistory.totalTokens') }}:
            <span class="font-medium text-gray-800">{{ run?.total_tokens ?? 0 }}</span>
          </span>
        </div>
        <div class="text-xs text-gray-500">
          {{ t('appStudio.debug.executionHistory.createdAt') }}:
          {{ formatCreatedAt(run?.created_at) }}
        </div>
        <!-- 运行错误 -->
        <div v-if="hasError" class="rounded bg-red-50 p-3">
          <div class="text-xs font-medium text-red-700">
            {{ t('appStudio.debug.executionHistory.error') }}
          </div>
          <div class="mt-1 break-all text-xs text-red-600">
            {{ run?.error }}
          </div>
        </div>
        <!-- 输入展示 -->
        <div>
          <div class="mb-1 text-sm font-medium text-gray-700">
            {{ t('appStudio.debug.executionHistory.inputs') }}
          </div>
          <pre
            v-if="hasInputs"
            class="max-h-[160px] overflow-auto rounded bg-gray-50 p-2 text-xs text-gray-700"
          >{{ inputsJson }}</pre>
          <div v-else class="text-xs text-gray-400">-</div>
        </div>
      </div>

      <!-- 中间分隔符 -->
      <a-divider />

      <!-- 节点执行时间线 -->
      <div class="text-sm font-medium text-gray-700 mb-2">
        {{ t('appStudio.debug.executionHistory.nodeExecution') }}
      </div>
      <div v-if="nodeExecutions.length === 0" class="py-6 text-center text-sm text-gray-400">
        {{ t('appStudio.debug.executionHistory.noNodeExecutions') }}
      </div>
      <div v-else class="flex flex-col gap-2">
        <div
          v-for="node in nodeExecutions"
          :key="node.id"
          class="rounded-lg border border-gray-200 bg-white"
        >
          <!-- 节点头部 -->
          <div
            class="flex cursor-pointer items-center justify-between px-3 py-2 hover:bg-gray-50"
            @click="toggleNodeExpand(node)"
          >
            <div class="flex items-center gap-2">
              <icon-loading
                v-if="node.status === 'running'"
                class="text-blue-500"
              />
              <icon-check-circle
                v-else-if="node.status === 'succeeded'"
                class="text-green-500"
              />
              <icon-close-circle
                v-else-if="node.status === 'failed'"
                class="text-red-500"
              />
              <icon-minus-circle
                v-else
                class="text-gray-400"
              />
              <a-tag size="small" color="arcoblue">
                {{ node.node_type }}
              </a-tag>
              <span class="text-sm font-medium text-gray-800">
                {{ node.title }}
              </span>
            </div>
            <div class="flex items-center gap-3">
              <a-badge
                :status="nodeStatusColorMap[node.status] || 'gray'"
                :text="t(`appStudio.debug.executionHistory.status.${node.status}`)"
              />
              <span class="text-xs text-gray-500">
                {{ t('appStudio.debug.executionHistory.elapsed') }}:
                {{ formatElapsed(node.elapsed_time) }}
              </span>
              <icon-down v-if="!isNodeExpanded(node)" />
              <icon-up v-else />
            </div>
          </div>
          <!-- 节点详情 -->
          <div
            v-if="isNodeExpanded(node)"
            class="border-t border-gray-100 px-3 py-2"
          >
            <div v-if="node.error" class="mb-2 rounded bg-red-50 p-2">
              <div class="text-xs font-medium text-red-700">
                {{ t('appStudio.debug.executionHistory.error') }}
              </div>
              <div class="mt-1 break-all text-xs text-red-600">
                {{ node.error }}
              </div>
            </div>
            <div class="mb-2">
              <div class="text-xs font-medium text-gray-600">
                {{ t('appStudio.debug.executionHistory.inputs') }}
              </div>
              <pre
                v-if="node.inputs && Object.keys(node.inputs).length > 0"
                class="mt-1 max-h-[160px] overflow-auto rounded bg-gray-50 p-2 text-xs text-gray-700"
              >{{ formatJson(node.inputs) }}</pre>
              <div v-else class="mt-1 text-xs text-gray-400">-</div>
            </div>
            <div>
              <div class="text-xs font-medium text-gray-600">
                {{ t('appStudio.debug.executionHistory.outputs') }}
              </div>
              <pre
                v-if="node.outputs && Object.keys(node.outputs).length > 0"
                class="mt-1 max-h-[160px] overflow-auto rounded bg-gray-50 p-2 text-xs text-gray-700"
              >{{ formatJson(node.outputs) }}</pre>
              <div v-else class="mt-1 text-xs text-gray-400">-</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部最终输出结果 -->
      <div class="mt-4 border-t pt-4">
        <div class="mb-2 text-sm font-medium text-gray-700">
          {{ t('appStudio.debug.executionHistory.outputs') }}
        </div>
        <pre
          v-if="hasOutputs"
          class="max-h-[200px] overflow-auto rounded bg-gray-50 p-3 text-xs text-gray-800"
        >{{ outputsJson }}</pre>
        <div v-else class="py-3 text-center text-xs text-gray-400">-</div>
      </div>
    </a-spin>
  </a-drawer>
</template>

<style scoped></style>
