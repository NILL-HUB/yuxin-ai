<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useDebugWorkflowApp } from '@/hooks/use-app'

// 1.组件类型定义
type NodeExecState = {
  node_id: string
  node_type: string
  title: string
  status: 'running' | 'succeeded' | 'failed'
  inputs?: Record<string, unknown>
  outputs?: Record<string, unknown>
  elapsed_time?: number
  error?: string
}

type WorkflowExecState = {
  status: 'idle' | 'running' | 'succeeded' | 'failed'
  inputs?: Record<string, unknown>
  node_count?: number
  nodes: NodeExecState[]
  total_elapsed?: number
  error?: string
  outputs?: Record<string, unknown>
}

// 2.组件 props 与 emits
const props = defineProps({
  app_id: { type: String, required: true },
  visible: { type: Boolean, required: true, default: false },
})
const emits = defineEmits(['update:visible'])
const { t } = useI18n()

// 3.hook 与响应式状态
const { loading, handleDebugWorkflowApp } = useDebugWorkflowApp()
const workflowState = ref<WorkflowExecState>({
  status: 'idle',
  nodes: [],
})
const inputsText = ref('{}')
const expandedNodeIds = ref<Set<string>>(new Set())

type BadgeStatus = 'success' | 'processing' | 'warning' | 'normal' | 'danger'

// 4.状态徽标颜色映射
const statusColorMap: Record<string, string> = {
  idle: 'gray',
  running: 'blue',
  succeeded: 'green',
  failed: 'red',
}

const nodeStatusColorMap: Record<string, string> = {
  running: 'blue',
  succeeded: 'green',
  failed: 'red',
}

// 5.计算属性
const totalElapsedDisplay = computed(() => {
  const val = workflowState.value.total_elapsed
  if (val === undefined || val === null) return '-'
  return `${val.toFixed(3)}s`
})

const nodeCountDisplay = computed(() => {
  if (workflowState.value.node_count !== undefined) {
    return String(workflowState.value.node_count)
  }
  return String(workflowState.value.nodes.length)
})

const outputsJson = computed(() => {
  const outputs = workflowState.value.outputs
  if (!outputs || Object.keys(outputs).length === 0) return ''
  return JSON.stringify(outputs, null, 2)
})

const hasOutputs = computed(() => {
  const outputs = workflowState.value.outputs
  return outputs !== undefined && outputs !== null && Object.keys(outputs).length > 0
})

// 6.事件 reducer：处理 GraphEngine 的 5 种事件
const reduceEvent = (event_response: { event: string; data: Record<string, unknown> }) => {
  const { event, data } = event_response
  const payload = data || {}

  switch (event) {
    case 'workflow_started': {
      workflowState.value = {
        status: 'running',
        inputs: payload.inputs as Record<string, unknown> | undefined,
        node_count: payload.node_count as number | undefined,
        nodes: [],
        total_elapsed: undefined,
        error: undefined,
        outputs: undefined,
      }
      expandedNodeIds.value = new Set()
      break
    }
    case 'node_started': {
      const node: NodeExecState = {
        node_id: payload.node_id as string,
        node_type: payload.node_type as string,
        title: payload.title as string,
        status: 'running',
        inputs: payload.inputs as Record<string, unknown> | undefined,
      }
      workflowState.value.nodes.push(node)
      break
    }
    case 'node_finished': {
      const idx = workflowState.value.nodes.findIndex(
        (n) => n.node_id === payload.node_id,
      )
      if (idx >= 0) {
        workflowState.value.nodes[idx] = {
          ...workflowState.value.nodes[idx],
          status: 'succeeded',
          outputs: payload.outputs as Record<string, unknown> | undefined,
          elapsed_time: payload.elapsed_time as number | undefined,
          error: '',
        }
      }
      break
    }
    case 'node_failed': {
      const idx = workflowState.value.nodes.findIndex(
        (n) => n.node_id === payload.node_id,
      )
      if (idx >= 0) {
        workflowState.value.nodes[idx] = {
          ...workflowState.value.nodes[idx],
          status: 'failed',
          outputs: payload.outputs as Record<string, unknown> | undefined,
          elapsed_time: payload.elapsed_time as number | undefined,
          error: payload.error as string | undefined,
        }
      }
      break
    }
    case 'workflow_finished': {
      workflowState.value = {
        ...workflowState.value,
        status: payload.status === 'succeeded' ? 'succeeded' : 'failed',
        error: payload.error as string | undefined,
        outputs: payload.outputs as Record<string, unknown> | undefined,
        total_elapsed:
          (payload.total_elapsed ?? computeTotalElapsed(workflowState.value.nodes)) as number | undefined,
      }
      break
    }
    default:
      // 未知事件忽略
      break
  }
}

const computeTotalElapsed = (nodes: NodeExecState[]): number => {
  return nodes.reduce((sum, n) => sum + (n.elapsed_time ?? 0), 0)
}

// 7.运行工作流
const onRun = async () => {
  // 7.1 解析输入 JSON
  let inputs: Record<string, unknown> = {}
  try {
    const parsed = JSON.parse(inputsText.value || '{}')
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      Message.error(t('appStudio.debug.workflowDebug.invalidJson'))
      return
    }
    inputs = parsed as Record<string, unknown>
  } catch {
    Message.error(t('appStudio.debug.workflowDebug.invalidJson'))
    return
  }

  // 7.2 重置状态
  workflowState.value = {
    status: 'running',
    inputs,
    nodes: [],
    total_elapsed: undefined,
    error: undefined,
    outputs: undefined,
  }
  expandedNodeIds.value = new Set()

  // 7.3 发起 SSE 调用
  await handleDebugWorkflowApp(props.app_id, inputs, reduceEvent)

  // 7.4 根据最终状态提示
  if (workflowState.value.status === 'succeeded') {
    Message.success(t('appStudio.debug.workflowDebug.runSuccess'))
  } else if (workflowState.value.status === 'failed') {
    Message.error(t('appStudio.debug.workflowDebug.runFailed'))
  }
}

// 8.节点展开/收起
const toggleNodeExpand = (node_id: string) => {
  if (expandedNodeIds.value.has(node_id)) {
    expandedNodeIds.value.delete(node_id)
  } else {
    expandedNodeIds.value.add(node_id)
  }
}

const isNodeExpanded = (node_id: string) => expandedNodeIds.value.has(node_id)

const formatJson = (obj: unknown): string => {
  if (obj === undefined || obj === null) return ''
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

const formatElapsed = (val?: number): string => {
  if (val === undefined || val === null) return '-'
  return `${val.toFixed(3)}s`
}

// 9.弹窗关闭时重置状态
const onVisibleChange = (val: boolean) => {
  emits('update:visible', val)
  if (!val) {
    workflowState.value = { status: 'idle', nodes: [] }
    expandedNodeIds.value = new Set()
  }
}

// 10.弹窗打开时重置初始状态
watch(
  () => props.visible,
  (val) => {
    if (val) {
      workflowState.value = { status: 'idle', nodes: [] }
      expandedNodeIds.value = new Set()
      if (!inputsText.value) inputsText.value = '{}'
    }
  },
)
</script>

<template>
  <a-modal
    :width="760"
    :visible="props.visible"
    @update:visible="onVisibleChange"
    hide-title
    :footer="false"
    modal-class="rounded-xl"
    :mask-closable="false"
  >
    <!-- 顶部标题 -->
    <div class="flex items-center justify-between border-b pb-3">
      <div class="text-lg font-bold text-gray-700">
        {{ t('appStudio.debug.workflowDebug.title') }}
      </div>
      <a-button
        type="text"
        class="!text-gray-700"
        size="small"
        @click="onVisibleChange(false)"
      >
        <template #icon>
          <icon-close />
        </template>
      </a-button>
    </div>

    <!-- 输入区 -->
    <div class="pt-4">
      <div class="mb-2 text-sm text-gray-600">
        {{ t('appStudio.debug.workflowDebug.inputs') }}
      </div>
      <a-textarea
        v-model:model-value="inputsText"
        :placeholder="t('appStudio.debug.workflowDebug.inputsPlaceholder')"
        :auto-size="{ minRows: 3, maxRows: 6 }"
        class="font-mono"
      />
      <div class="mt-2 flex justify-end">
        <a-button
          type="primary"
          :loading="loading"
          :disabled="workflowState.status === 'running'"
          @click="onRun"
        >
          <template #icon>
            <icon-play-arrow />
          </template>
          {{ t('appStudio.debug.workflowDebug.run') }}
        </a-button>
      </div>
    </div>

    <!-- 状态徽标 + 总耗时 + 节点数 -->
    <div class="mt-4 flex items-center gap-4 border-t pt-4">
      <a-badge
        :status="(statusColorMap[workflowState.status] || 'gray') as BadgeStatus"
        :text="t(`appStudio.debug.workflowDebug.${workflowState.status}`)"
      />
      <div class="text-sm text-gray-600">
        {{ t('appStudio.debug.workflowDebug.totalElapsed') }}:
        <span class="font-medium text-gray-800">{{ totalElapsedDisplay }}</span>
      </div>
      <div class="text-sm text-gray-600">
        {{ t('appStudio.debug.workflowDebug.nodeCount') }}:
        <span class="font-medium text-gray-800">{{ nodeCountDisplay }}</span>
      </div>
    </div>

    <!-- 节点执行时间线 -->
    <div class="mt-4 max-h-[320px] overflow-y-auto pr-1">
      <div
        v-if="workflowState.nodes.length === 0"
        class="py-6 text-center text-sm text-gray-400"
      >
        {{ t('appStudio.debug.workflowDebug.idle') }}
      </div>
      <div v-else class="flex flex-col gap-2">
        <div
          v-for="node in workflowState.nodes"
          :key="node.node_id"
          class="rounded-lg border border-gray-200 bg-white"
        >
          <!-- 节点头部 -->
          <div
            class="flex cursor-pointer items-center justify-between px-3 py-2 hover:bg-gray-50"
            @click="toggleNodeExpand(node.node_id)"
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
              <a-tag size="small" color="arcoblue">
                {{ node.node_type }}
              </a-tag>
              <span class="text-sm font-medium text-gray-800">
                {{ node.title }}
              </span>
            </div>
            <div class="flex items-center gap-3">
              <a-badge
                :status="(nodeStatusColorMap[node.status] || 'gray') as BadgeStatus"
                :text="t(`appStudio.debug.workflowDebug.${node.status}`)"
              />
              <span class="text-xs text-gray-500">
                {{ t('appStudio.debug.workflowDebug.elapsed') }}:
                {{ formatElapsed(node.elapsed_time) }}
              </span>
              <icon-down v-if="!isNodeExpanded(node.node_id)" />
              <icon-up v-else />
            </div>
          </div>
          <!-- 节点详情 -->
          <div
            v-if="isNodeExpanded(node.node_id)"
            class="border-t border-gray-100 px-3 py-2"
          >
            <div v-if="node.error" class="mb-2 rounded bg-red-50 p-2">
              <div class="text-xs font-medium text-red-700">
                {{ t('appStudio.debug.workflowDebug.error') }}
              </div>
              <div class="mt-1 break-all text-xs text-red-600">
                {{ node.error }}
              </div>
            </div>
            <div class="mb-2">
              <div class="text-xs font-medium text-gray-600">
                {{ t('appStudio.debug.workflowDebug.inputs') }}
              </div>
              <pre
                class="mt-1 max-h-[160px] overflow-auto rounded bg-gray-50 p-2 text-xs text-gray-700"
              >{{ formatJson(node.inputs) }}</pre>
            </div>
            <div>
              <div class="text-xs font-medium text-gray-600">
                {{ t('appStudio.debug.workflowDebug.outputs') }}
              </div>
              <pre
                v-if="node.outputs && Object.keys(node.outputs).length > 0"
                class="mt-1 max-h-[160px] overflow-auto rounded bg-gray-50 p-2 text-xs text-gray-700"
              >{{ formatJson(node.outputs) }}</pre>
              <div v-else class="mt-1 text-xs text-gray-400">
                {{ t('appStudio.debug.workflowDebug.noOutputs') }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 最终输出结果 -->
    <div class="mt-4 border-t pt-4">
      <div class="mb-2 text-sm font-medium text-gray-700">
        {{ t('appStudio.debug.workflowDebug.outputs') }}
      </div>
      <pre
        v-if="hasOutputs"
        class="max-h-[200px] overflow-auto rounded bg-gray-50 p-3 text-xs text-gray-800"
      >{{ outputsJson }}</pre>
      <div v-else class="py-3 text-center text-xs text-gray-400">
        {{ t('appStudio.debug.workflowDebug.noOutputs') }}
      </div>
    </div>
  </a-modal>
</template>

<style scoped></style>
