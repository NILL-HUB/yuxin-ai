<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getPartitions } from '@/services/knowledge-base'

const props = defineProps<{ knowledgeBaseId: string }>()
const emit = defineEmits<{ (e: 'select', partitionId: string): void }>()
const { t } = useI18n()

type PartitionNode = {
  id: string
  name: string
  partition_key: string
  parent_id: string
  sort_order: number
}

const treeData = ref<PartitionNode[]>([])
const selectedKey = ref('')

// 两级分区：一级平铺为根，子分区缩进在其父节点之后
const displayList = computed<Array<PartitionNode & { depth: number }>>(() => {
  const nodes = treeData.value
  const ordered: Array<PartitionNode & { depth: number }> = []
  const seen = new Set<string>()
  for (const n of nodes) {
    if (!n.parent_id) {
      ordered.push({ ...n, depth: 0 })
      seen.add(n.id)
      for (const c of nodes) {
        if (c.parent_id === n.id) {
          ordered.push({ ...c, depth: 1 })
          seen.add(c.id)
        }
      }
    }
  }
  for (const c of nodes) {
    if (c.parent_id && !seen.has(c.id)) {
      ordered.push({ ...c, depth: 1 })
    }
  }
  return ordered
})

onMounted(async () => {
  const resp = await getPartitions(props.knowledgeBaseId)
  treeData.value = resp.data || []
})

const selectAll = () => {
  selectedKey.value = ''
  emit('select', '')
}

const selectPartition = (node: PartitionNode) => {
  selectedKey.value = node.id
  emit('select', node.id)
}
</script>

<template>
  <div class="flex flex-col gap-1 p-2">
    <p class="px-3 pt-2 pb-1 text-xs font-semibold text-muted">
      {{ t('space.datasets.detail.partitions.title') }}
    </p>
    <button
      data-test="nav-all"
      type="button"
      class="rounded-lg px-3 py-2 text-left text-sm transition"
      :class="selectedKey === '' ? 'bg-brand-soft text-brand-text' : 'text-text-2 hover:bg-surface-2'"
      @click="selectAll"
    >
      {{ t('space.datasets.detail.partitions.all') }}
    </button>
    <button
      v-for="node in displayList"
      :key="node.id"
      :data-test="`nav-partition-${node.id}`"
      type="button"
      class="rounded-lg px-3 py-2 text-left text-sm transition"
      :class="[
        selectedKey === node.id ? 'bg-brand-soft text-brand-text' : 'text-text-2 hover:bg-surface-2',
        node.depth > 0 ? 'ml-4' : '',
      ]"
      @click="selectPartition(node)"
    >
      {{ node.name }}
    </button>
  </div>
</template>