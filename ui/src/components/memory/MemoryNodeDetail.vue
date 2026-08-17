<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import moment from 'moment'
import type { MemoryDetail } from '@/models/memory-graph'

const props = defineProps<{
  detail: MemoryDetail | null
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'edit'): void
  (e: 'soft-delete'): void
  (e: 'hard-delete'): void
  (e: 'decay'): void
  (e: 'select-related', nodeId: string): void
}>()

const { t } = useI18n()

const hasDetail = computed(() => props.detail && props.detail.memory_id)

const typeLabel = (type?: string) => {
  if (!type) return '-'
  const key = `memory.memoryType.${type}`
  const translated = t(key)
  return translated === key ? type : translated
}

const formatTime = (value?: string) => {
  if (!value) return '-'
  const date = moment(value)
  return date.isValid() ? date.format('YYYY-MM-DD HH:mm') : value
}

const confidenceStars = (value?: number) => {
  if (value === undefined || value === null) return '-'
  const n = Math.max(1, Math.min(5, Math.round(Number(value) || 0)))
  return '★'.repeat(n) + '☆'.repeat(5 - n)
}

const handleEdit = () => emit('edit')
const handleSoftDelete = () => emit('soft-delete')
const handleHardDelete = () => emit('hard-delete')
const handleDecay = () => emit('decay')
const handleSelectRelated = (nodeId: string) => emit('select-related', nodeId)
</script>

<template>
  <div class="flex h-full flex-col">
    <a-spin :loading="loading" class="block flex-1">
      <div v-if="!hasDetail" class="flex h-full flex-col items-center justify-center py-16 text-gray-400">
        <icon-bookmark class="mb-3 text-5xl" />
        <p>{{ t('memory.graph.selectNodeHint') }}</p>
      </div>
      <div v-else class="space-y-4 p-4">
        <!-- 记忆内容 -->
        <div>
          <div class="mb-1 text-xs font-medium text-gray-400">{{ t('memory.graph.contentLabel') }}</div>
          <div class="rounded-lg bg-gray-50 p-3 text-sm text-gray-800">
            {{ detail!.content }}
          </div>
        </div>

        <!-- 元信息 -->
        <div class="grid grid-cols-2 gap-3 text-sm">
          <div>
            <span class="text-gray-400">{{ t('memory.graph.typeLabel') }}</span>
            <span class="ml-2 text-gray-700">{{ typeLabel(detail!.memory_type) }}</span>
          </div>
          <div>
            <span class="text-gray-400">{{ t('memory.graph.confidenceLabel') }}</span>
            <span class="ml-2 text-amber-500">{{ confidenceStars(detail!.confidence) }}</span>
          </div>
          <div>
            <span class="text-gray-400">{{ t('memory.graph.createdLabel') }}</span>
            <span class="ml-2 text-gray-700">{{ formatTime(detail!.created_at) }}</span>
          </div>
          <div>
            <span class="text-gray-400">{{ t('memory.graph.lastAccessedLabel') }}</span>
            <span class="ml-2 text-gray-700">{{ formatTime(detail!.last_accessed_at) }}</span>
          </div>
        </div>

        <!-- 关联节点 -->
        <div v-if="detail!.related && detail!.related.length > 0">
          <div class="mb-2 text-xs font-medium text-gray-400">{{ t('memory.graph.relatedLabel') }}</div>
          <div class="space-y-1">
            <div
              v-for="(rel, idx) in detail!.related"
              :key="idx"
              class="cursor-pointer rounded border border-gray-100 bg-white p-2 text-sm hover:border-blue-300 hover:bg-blue-50"
              @click="handleSelectRelated(rel.node_id)"
            >
              <div class="flex items-center justify-between">
                <span class="truncate text-gray-700">{{ rel.node_id }}</span>
                <span class="ml-2 flex-shrink-0 text-xs text-gray-400">
                  {{ rel.relation }} · w={{ rel.weight?.toFixed(2) ?? '-' }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="flex flex-wrap gap-2 border-t pt-3">
          <a-button size="small" @click="handleEdit">
            <template #icon><icon-edit /></template>
            {{ t('memory.graph.editBtn') }}
          </a-button>
          <a-button size="small" @click="handleDecay">
            <template #icon><icon-minus-circle /></template>
            {{ t('memory.graph.decayBtn') }}
          </a-button>
          <a-popconfirm :content="t('memory.graph.hardDeleteConfirm')" @ok="handleHardDelete">
            <a-button size="small" status="danger">
              <template #icon><icon-delete /></template>
              {{ t('memory.graph.hardDeleteBtn') }}
            </a-button>
          </a-popconfirm>
          <a-button size="small" status="warning" @click="handleSoftDelete">
            <template #icon><icon-delete /></template>
            {{ t('memory.graph.softDeleteBtn') }}
          </a-button>
        </div>
      </div>
    </a-spin>
  </div>
</template>
