<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useGetKnowledgeDocumentsWithPage } from '@/hooks/use-knowledge-base'

const props = defineProps<{ knowledgeBaseId: string; partitionId: string }>()
const emit = defineEmits<{ (e: 'open', documentId: string): void }>()
const { t } = useI18n()

const viewMode = ref<'grid' | 'table'>('grid')
const searchWord = ref('')
const { loading, documents, paginator, loadDocuments } = useGetKnowledgeDocumentsWithPage()

const mediaIcon = (mediaType?: string) => {
  const map: Record<string, string> = {
    document: 'icon-file',
    image: 'icon-image',
    video: 'icon-video',
    audio: 'icon-audio',
  }
  return map[String(mediaType || 'document')] || 'icon-file'
}

const statusText = (status?: string) => {
  const key = `space.datasets.documents.statuses.${String(status || 'pending')}`
  return t(key)
}

watch(
  () => [props.knowledgeBaseId, props.partitionId, searchWord.value] as const,
  ([kb]) => {
    if (!kb) return
    void loadDocuments(kb, {
      current_page: 1,
      page_size: 50,
      search_word: searchWord.value.trim(),
      partition_id: props.partitionId || undefined,
    })
  },
  { immediate: true },
)

const paginationConfig = computed(() => ({
  total: paginator.value.total_record,
  current: paginator.value.current_page,
  pageSize: paginator.value.page_size,
  showTotal: true,
  showPageSize: true,
  pageSizeOptions: [20, 50],
}))
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <div class="flex items-center justify-between gap-3 pb-3">
      <a-input
        v-model="searchWord"
        :placeholder="t('space.datasets.detail.material.searchPlaceholder')"
        allow-clear
        class="!w-[220px]"
      />
      <a-radio-group v-model="viewMode" type="button" size="mini">
        <a-radio value="grid">{{ t('space.datasets.detail.material.gridView') }}</a-radio>
        <a-radio value="table">{{ t('space.datasets.detail.material.tableView') }}</a-radio>
      </a-radio-group>
    </div>

    <div v-if="viewMode === 'grid'" v-loading="loading" class="min-h-0 flex-1 overflow-y-auto">
      <a-grid :cols="4" :col-gap="16" :row-gap="16">
        <a-grid-item v-for="doc in documents" :key="doc.id">
          <div
            class="cursor-pointer rounded-xl border border-border-c bg-surface p-3 transition hover:border-brand"
            @click="emit('open', String(doc.id))"
          >
            <div class="flex items-center justify-between">
              <a-avatar shape="square" :size="40" class="rounded-lg bg-brand-soft">
                <template #trigger-icon>
                  <icon-font :type="mediaIcon(doc.media_type)" />
                </template>
              </a-avatar>
              <a-tag
                class="rounded-full text-xs"
                :class="doc.status === 'completed' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'"
              >
                {{ statusText(doc.status) }}
              </a-tag>
            </div>
            <p class="mt-2 line-clamp-1 break-all text-sm font-medium text-text">{{ doc.name }}</p>
            <p class="mt-1 text-xs text-muted">
              {{ doc.character_count }} · {{ new Date(Number(doc.created_at) * 1000).toLocaleDateString() }}
            </p>
          </div>
        </a-grid-item>
      </a-grid>
      <a-empty v-if="!loading && documents.length === 0" class="py-16">
        <template #description>{{ t('space.datasets.detail.material.empty') }}</template>
      </a-empty>
    </div>

    <a-table
      v-else
      row-key="id"
      :loading="loading"
      :data="documents"
      :pagination="paginationConfig"
      @row-click="(row: Record<string, unknown>) => emit('open', String(row.id))"
    >
      <template #columns>
        <a-table-column :title="t('space.datasets.documents.columns.document')" data-index="name" />
        <a-table-column :title="t('space.datasets.documents.columns.characterCount')" data-index="character_count" />
        <a-table-column :title="t('space.datasets.documents.columns.processingStatus')" data-index="status" />
        <a-table-column :title="t('space.datasets.documents.columns.uploadedAt')" data-index="created_at" />
      </template>
    </a-table>
  </div>
</template>