<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import moment from 'moment'
import type { MemoryCluster } from '@/models/memory-graph'

const props = defineProps<{
  clusters: MemoryCluster[]
  loading?: boolean
  selectedType?: string
}>()

const emit = defineEmits<{
  (e: 'select-cluster', type: string): void
}>()

const { t } = useI18n()

// 6 个 memory_type 元信息
const CLUSTER_META: Array<{ value: string; color: string }> = [
  { value: 'profile', color: 'arcoblue' },
  { value: 'preference', color: 'green' },
  { value: 'relationship', color: 'purple' },
  { value: 'event', color: 'orange' },
  { value: 'project', color: 'cyan' },
  { value: 'secret', color: 'red' },
]

const typeLabel = (type: string) => {
  const key = `memory.memoryType.${type}`
  const translated = t(key)
  return translated === key ? type : translated
}

const typeDesc = (type: string) => {
  const key = `memory.memoryTypeDesc.${type}`
  const translated = t(key)
  return translated === key ? '' : translated
}

// 将后端返回的 clusters 列表转为 Map 便于查找
const clusterMap = computed(() => {
  const map: Record<string, MemoryCluster> = {}
  for (const c of props.clusters) {
    map[c.memory_type] = c
  }
  return map
})

// 合并元信息和实际数据，保证 6 个区块都展示
const displayClusters = computed(() => {
  return CLUSTER_META.map((meta) => {
    const data = clusterMap.value[meta.value]
    return {
      value: meta.value,
      color: meta.color,
      count: data?.node_count ?? 0,
      lastUpdated: data?.last_updated_at ?? '',
    }
  })
})

const totalCount = computed(() =>
  displayClusters.value.reduce((sum, c) => sum + c.count, 0),
)

const formatTime = (value: string) => {
  if (!value) return '-'
  const date = moment(value)
  return date.isValid() ? date.format('YYYY-MM-DD HH:mm') : value
}

const handleClick = (type: string) => {
  emit('select-cluster', type)
}
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center justify-between">
      <span class="text-sm text-gray-500">
        {{ t('memory.graph.totalNodes', { count: totalCount }) }}
      </span>
    </div>
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <div
        v-for="cluster in displayClusters"
        :key="cluster.value"
        class="cursor-pointer rounded-lg border bg-white p-4 transition hover:shadow-md"
        :class="{
          'border-blue-400 ring-2 ring-blue-100': selectedType === cluster.value,
          'opacity-60': cluster.count === 0,
        }"
        :data-memory-type="cluster.value"
        :data-node-count="cluster.count"
        @click="handleClick(cluster.value)"
      >
        <div class="mb-2 flex items-center gap-2">
          <a-tag :color="cluster.color" size="small">
            {{ typeLabel(cluster.value) }}
          </a-tag>
        </div>
        <div class="text-2xl font-semibold text-gray-800">{{ cluster.count }}</div>
        <div class="mt-1 truncate text-xs text-gray-400" :title="typeDesc(cluster.value)">
          {{ typeDesc(cluster.value) }}
        </div>
        <div class="mt-2 text-xs text-gray-300">
          {{ t('memory.graph.lastUpdated') }}：{{ formatTime(cluster.lastUpdated) }}
        </div>
      </div>
    </div>
  </div>
</template>
