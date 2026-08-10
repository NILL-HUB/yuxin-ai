<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { useI18n } from 'vue-i18n'
import type { ClusterSubgraph, MemoryNode } from '@/models/memory-graph'

const props = defineProps<{
  subgraph: ClusterSubgraph | null
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'select-node', nodeId: string): void
}>()

const { t } = useI18n()

const chartContainer = ref<HTMLDivElement | null>(null)
let chartInstance: echarts.ECharts | null = null

// memory_type 对应的颜色
const TYPE_COLORS: Record<string, string> = {
  profile: '#409EFF',
  preference: '#67C23A',
  relationship: '#9C27B0',
  event: '#E6A23C',
  project: '#00BCD4',
  secret: '#F56C6C',
}

const typeLabel = (type: string) => {
  const key = `memory.memoryType.${type}`
  const translated = t(key)
  return translated === key ? type : translated
}

// 截断内容显示
const truncateContent = (content: string, maxLen: number = 30) => {
  if (!content) return ''
  return content.length > maxLen ? content.slice(0, maxLen) + '…' : content
}

// 构建 ECharts 图谱配置
const buildChartOption = () => {
  if (!props.subgraph || !props.subgraph.nodes) {
    return { series: [{ type: 'graph', data: [], links: [] }] }
  }

  const nodes = props.subgraph.nodes.map((node: MemoryNode) => ({
    id: node.id,
    name: truncateContent(node.content),
    symbolSize: Math.max(20, Math.min(60, 20 + (node.weight || 0) * 40)),
    itemStyle: {
      color: TYPE_COLORS[node.memory_type] || '#909399',
    },
    label: {
      show: true,
      position: 'bottom',
      fontSize: 10,
      color: '#666',
      width: 80,
      overflow: 'truncate',
    },
    rawData: node,
  }))

  const links = (props.subgraph.edges || []).map((edge) => ({
    source: edge.source,
    target: edge.target,
    value: edge.type,
    lineStyle: {
      width: Math.max(1, (edge.weight || 0) * 3),
      opacity: 0.6,
    },
  }))

  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: Record<string, unknown>) => {
        if (params.dataType === 'node') {
          const rawData = (params.data as { rawData?: MemoryNode } | undefined)?.rawData
          if (rawData) {
            const node = rawData as MemoryNode
            return `<div style="max-width:300px">
              <div style="font-weight:600;margin-bottom:4px">${typeLabel(node.memory_type)}</div>
              <div style="color:#666">${node.content}</div>
              <div style="color:#999;font-size:12px;margin-top:4px">
                weight: ${node.weight?.toFixed(2) ?? '-'} | tier: ${node.tier ?? '-'}
              </div>
            </div>`
          }
        }
        if (params.dataType === 'edge') {
          return String((params.data as { value?: unknown } | undefined)?.value ?? '')
        }
        return ''
      },
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        label: {
          show: true,
        },
        force: {
          repulsion: 200,
          edgeLength: [80, 200],
          gravity: 0.1,
        },
        data: nodes,
        links: links,
        emphasis: {
          focus: 'adjacency',
          lineStyle: {
            width: 4,
          },
        },
      },
    ],
  }
}

const initChart = () => {
  if (!chartContainer.value) return
  chartInstance = echarts.init(chartContainer.value)
  chartInstance.setOption(buildChartOption())
  chartInstance.on('click', (params: Record<string, unknown>) => {
    const data = params.data as { id?: string } | undefined
    if (params.dataType === 'node' && data?.id) {
      emit('select-node', data.id)
    }
  })
}

const updateChart = () => {
  if (!chartInstance) {
    initChart()
    return
  }
  chartInstance.setOption(buildChartOption(), true)
}

const handleResize = () => {
  chartInstance?.resize()
}

watch(
  () => props.subgraph,
  () => {
    nextTick(() => updateChart())
  },
  { deep: true },
)

watch(
  () => props.loading,
  () => {
    nextTick(() => updateChart())
  },
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})

// 初始化
nextTick(() => {
  initChart()
  window.addEventListener('resize', handleResize)
})

// 暴露 resize 方法供父组件调用
defineExpose({
  resize: handleResize,
})
</script>

<template>
  <div class="relative h-[500px] w-full rounded-lg border bg-white">
    <div
      v-if="loading"
      class="absolute inset-0 z-10 flex items-center justify-center bg-white/70"
    >
      <a-spin :loading="true" />
    </div>
    <div
      v-if="!loading && (!subgraph || !subgraph.nodes || subgraph.nodes.length === 0)"
      class="absolute inset-0 flex flex-col items-center justify-center text-gray-400"
    >
      <icon-bookmark class="mb-3 text-5xl" />
      <p>{{ t('memory.graph.emptySubgraph') }}</p>
    </div>
    <div
      v-if="subgraph?.truncated"
      class="absolute right-3 top-3 z-10 rounded bg-amber-50 px-2 py-1 text-xs text-amber-600"
    >
      {{ t('memory.graph.truncated') }}
    </div>
    <div ref="chartContainer" class="h-full w-full"></div>
  </div>
</template>
