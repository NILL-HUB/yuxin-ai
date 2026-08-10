<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  useDeleteKnowledgeDocument,
  useGetKnowledgeBase,
  useGetKnowledgeDocumentsWithPage,
  useUploadKnowledgeDocument,
} from '@/hooks/use-knowledge-base'
import HitTestingModal from '@/views/space/datasets/documents/components/HitTestingModal.vue'
import { formatTimestampLong } from '@/utils/time-formatter'

type DocumentRecord = Record<string, unknown>

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const hitModalVisible = ref(false)
const searchInput = ref('')
const { knowledgeBase: dataset, loadKnowledgeBase: loadDataset } = useGetKnowledgeBase()
const { loading, documents, paginator, loadDocuments } = useGetKnowledgeDocumentsWithPage()
const { handleDelete } = useDeleteKnowledgeDocument()
const { loading: uploadLoading, handleUploadDocument } = useUploadKnowledgeDocument()
const fileInputRef = ref<HTMLInputElement | null>(null)

// 触发隐藏的文件选择器
const triggerFileInput = () => {
  fileInputRef.value?.click()
}

// 文件选择后调用上传接口，成功后刷新文档列表与知识库详情
const handleFileChange = async (event: Event) => {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  // 重置 input 的 value，便于重复选择同一文件
  target.value = ''
  if (!file) return
  try {
    await handleUploadDocument(datasetId.value, file)
    // 上传成功后刷新文档列表与知识库详情
    void loadDocuments(datasetId.value, req.value)
    void loadDataset(datasetId.value)
  } catch {
    // 错误提示已由 hook 统一处理
  }
}

const datasetId = computed(() => String(route.params?.dataset_id ?? ''))
const searchWord = computed(() => String(route.query?.search_word ?? ''))
const req = computed(() => {
 return {
 current_page: Number(route.query?.current_page ??1),
 page_size: Number(route.query?.page_size ??20),
 search_word: searchWord.value,
 }
})
const hasActiveSearch = computed(() => searchWord.value.trim() !== '')
const sortedDocuments = computed(() => {
 return [...documents.value].sort((left, right) => {
 const createdAtDiff = Number(right.created_at ??0) - Number(left.created_at ??0)
 if (createdAtDiff !==0) return createdAtDiff
 return String(right.id ?? '').localeCompare(String(left.id ?? ''))
 })
})

const updateRouteQuery = async (patch: Record<string, string | number | undefined>) => {
 const nextQuery = {
 ...route.query,
 ...patch,
 } as Record<string, string | number | undefined>

 Object.keys(nextQuery).forEach((key) => {
 const value = nextQuery[key]
 if (value === '' || value === undefined) {
 delete nextQuery[key]
 }
 })

 await router.push({
 path: route.path,
 query: nextQuery,
 })
}

const getProcessingStatusLabel = (status: string) => {
  const normalizedStatus = String(status || '').toLowerCase()

  if (normalizedStatus === 'completed') return t('space.datasets.documents.statuses.completed')
  if (normalizedStatus === 'error') return t('space.datasets.documents.statuses.error')
  if (['parsing', 'splitting', 'indexing', 'processing'].includes(normalizedStatus)) {
    return t('space.datasets.documents.statuses.processing')
  }
  if (['waiting', 'pending', 'queued'].includes(normalizedStatus)) {
    return t('space.datasets.documents.statuses.pending')
  }
  return t('space.datasets.documents.statuses.processing')
}

const getProcessingStatusClass = (status: string) => {
 const normalizedStatus = String(status || '').toLowerCase()

 if (normalizedStatus === 'completed') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
 if (normalizedStatus === 'error') return 'bg-red-50 text-red-700 border-red-200'
 if (['waiting', 'pending', 'queued'].includes(normalizedStatus)) {
 return 'bg-slate-100 text-slate-600 border-slate-200'
 }
 return 'bg-amber-50 text-amber-700 border-amber-200'
}

const getAvailabilityLabel = (record: DocumentRecord) => {
  if (record.status !== 'completed') return t('space.datasets.documents.statuses.unavailable')
  return t('space.datasets.documents.statuses.available')
}

const getAvailabilityClass = (record: DocumentRecord) => {
  if (record.status !== 'completed') return 'bg-slate-100 text-slate-500 border-slate-200'
  return 'bg-sky-50 text-sky-700 border-sky-200'
}

const handleSearch = async (value: string) => {
 await updateRouteQuery({
 search_word: value.trim(),
 current_page:1,
 page_size: req.value.page_size,
 })
}

const handlePageChange = async (page: number) => {
 await updateRouteQuery({
 current_page: page,
 page_size: req.value.page_size,
 search_word: searchWord.value || undefined,
 })
}

const handlePageSizeChange = async (pageSize: number) => {
 await updateRouteQuery({
 current_page:1,
 page_size: pageSize,
 search_word: searchWord.value || undefined,
 })
}

const getDisplayIndex = (rowIndex: number) => {
 return (req.value.current_page -1) * req.value.page_size + rowIndex +1
}

watch(
 searchWord,
 (value) => {
 searchInput.value = value
 },
 { immediate: true },
)

watch(
 datasetId,
 (value) => {
 if (!value) return
 void loadDataset(value)
 },
 { immediate: true },
)

watch(
 () => [datasetId.value, req.value.current_page, req.value.page_size, req.value.search_word] as const,
 ([value]) => {
 if (!value) return
 void loadDocuments(value, req.value)
 },
 { immediate: true },
)
</script>

<template>
 <div class="scrollbar-w-none h-full min-h-0 overflow-y-auto bg-slate-50 px-6 py-6 pb-10">
 <div
 class="flex min-h-full flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
 >
 <div class="border-b border-slate-200 px-5 py-4">
 <div class="flex flex-col gap-2">
 <div class="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
 <div class="flex min-w-0 items-start gap-3">
 <router-link :to="{ name: 'my-knowledge' }">
 <a-button size="mini" type="text" class="mt-1 !text-slate-600">
 <template #icon>
 <icon-left />
 </template>
 </a-button>
 </router-link>
 <a-avatar :size="52" shape="square" class="rounded-xl" :image-url="dataset.icon" />
 <div class="min-w-0 flex-1 space-y-2">
 <a-skeleton-line v-if="!dataset?.name" :widths="[160]" />
 <div v-else class="line-clamp-1 text-xl font-semibold tracking-tight text-slate-900">
 {{ dataset.name }}
 </div>
 <div class="flex flex-wrap items-center gap-2">
 <a-tag class="!m-0 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-slate-600">
 {{ dataset.character_count ||0 }} {{ t('space.datasets.documents.columns.characterCount') }}
 </a-tag>
 <a-tag class="!m-0 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-slate-600">
 {{ dataset.document_count ||0 }} {{ t('space.datasets.documents.columns.documentCount') }}
 </a-tag>
 </div>
 </div>
 </div>
 <div class="flex flex-col gap-2 lg:items-end">
 <div class="flex flex-wrap items-center justify-end gap-3">
 <a-button
 type="primary"
 class="rounded-xl px-4"
 :loading="uploadLoading"
 @click="triggerFileInput"
 >
 <template #icon>
 <icon-upload />
 </template>
 {{ t('space.datasets.documents.addFile') }}
 </a-button>
 <a-button class="rounded-xl border-slate-200 bg-white px-4 !text-slate-700" @click="hitModalVisible = true">
 {{ t('space.datasets.documents.recallTest') }}
 </a-button>
 </div>
 <div
 class="relative h-8 w-[220px] max-w-full self-end rounded-xl border border-slate-300 bg-white transition focus-within:border-sky-400 focus-within:shadow-sm hover:border-slate-400"
 >
  <input
  v-model="searchInput"
  type="text"
 :placeholder="t('space.datasets.documents.searchPlaceholder')"
  class="h-full w-full border-0 bg-transparent pl-3 pr-9 text-sm text-slate-700 outline-none placeholder:text-slate-400"
  @keydown.enter="handleSearch(searchInput)"
  />
  <button
  type="button"
  class="absolute right-1.5 top-1/2 inline-flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-full text-slate-500 transition hover:bg-slate-100 hover:text-sky-600"
  @click="handleSearch(searchInput)"
  >
 <svg
 class="h-4 w-4"
 viewBox="0 0 20 20"
 fill="none"
 xmlns="http://www.w3.org/2000/svg"
 aria-hidden="true"
 >
 <path
 d="M8.75 3.75a5 5 0 1 0 0 10a5 5 0 0 0 0-10Zm0-1.5a6.5 6.5 0 1 1 0 13a6.5 6.5 0 0 1 0-13Zm4.56 11.12a.75.75 0 0 1 1.06 0l2.41 2.41a.75.75 0 1 1-1.06 1.06l-2.41-2.41a.75.75 0 0 1 0-1.06Z"
 fill="currentColor"
  />
  </svg>
  </button>
 </div>
 </div>
 </div>
 </div>
 </div>

 <div class="min-h-0 flex-1 pb-4">
 <a-table
 row-key="id"
 hoverable
 :pagination="{
 total: paginator.total_record,
 current: paginator.current_page,
 defaultCurrent:1,
 pageSize: paginator.page_size,
 defaultPageSize:20,
 showTotal: true,
 showPageSize: true,
 pageSizeOptions: [10,20,50,100],
 }"
 :loading="loading"
 :data="sortedDocuments"
 :bordered="{ wrapper: false }"
 @page-change="handlePageChange"
 @page-size-change="handlePageSizeChange"
 >
 <template #columns>
 <a-table-column
 :title="t('space.datasets.documents.columns.index')"
 data-index="position"
 align="center"
 :width="80"
 header-cell-class="!bg-slate-100 text-slate-700"
 cell-class="bg-transparent text-slate-700"
 >
 <template #cell="{ rowIndex }">
 <div class="font-mono text-sm font-semibold text-slate-500">
 {{ getDisplayIndex(rowIndex) }}
 </div>
 </template>
 </a-table-column>
 <a-table-column
 :title="t('space.datasets.documents.columns.document')"
 data-index="name"
 align="center"
 :width="320"
 header-cell-class="!bg-slate-100 text-slate-700"
 cell-class="bg-transparent text-slate-700"
 >
  <template #cell="{ record }">
 <div class="mx-auto min-w-0 max-w-[240px] text-center">
  <router-link
  :to="{
  name: 'space-datasets-documents-segments-list',
 params: {
 dataset_id: datasetId,
 document_id: record.id as string,
 },
 }"
 class="block truncate font-medium text-slate-800 transition hover:text-sky-700"
  >
  {{ record.name }}
  </router-link>
 </div>
 </template>
 </a-table-column>
 <a-table-column
 :title="t('space.datasets.documents.columns.characterCount')"
 data-index="character_count"
 align="center"
 :width="110"
 header-cell-class="!bg-slate-100 text-slate-700"
 cell-class="bg-transparent text-slate-700"
 >
 <template #cell="{ record }">
 {{ (record.character_count /1000).toFixed(1) }}k
 </template>
 </a-table-column>
 <a-table-column
 :title="t('space.datasets.documents.columns.processingStatus')"
 data-index="status"
 align="center"
 :width="140"
 header-cell-class="!bg-slate-100 text-slate-700"
 cell-class="bg-transparent text-slate-700"
 >
 <template #cell="{ record }">
 <a-tooltip v-if="record.status === 'error' && record.error" :content="record.error">
 <div
 class="mx-auto inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold"
 :class="getProcessingStatusClass(record.status)"
 >
 {{ getProcessingStatusLabel(record.status) }}
 </div>
 </a-tooltip>
 <div
 v-else
 class="mx-auto inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold"
 :class="getProcessingStatusClass(record.status)"
 >
 {{ getProcessingStatusLabel(record.status) }}
 </div>
 </template>
 </a-table-column>
 <a-table-column
 :title="t('space.datasets.documents.columns.enabledStatus')"
 data-index="enabled"
 align="center"
 :width="130"
 header-cell-class="!bg-slate-100 text-slate-700"
 cell-class="bg-transparent text-slate-700"
 >
 <template #cell="{ record }">
 <div
 class="mx-auto inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold"
 :class="getAvailabilityClass(record)"
 >
 {{ getAvailabilityLabel(record) }}
 </div>
 </template>
 </a-table-column>
 <a-table-column
 :title="t('space.datasets.documents.columns.uploadedAt')"
 data-index="created_at"
 align="center"
 :width="180"
 header-cell-class="!bg-slate-100 text-slate-700"
 cell-class="bg-transparent text-slate-700"
 >
 <template #cell="{ record }">
 <div class="text-center text-sm text-slate-600">
 {{ formatTimestampLong(record.created_at) }}
 </div>
 </template>
 </a-table-column>
 <a-table-column
 :title="t('space.datasets.documents.columns.actions')"
 data-index="operator"
 align="center"
 :width="120"
 header-cell-class="!bg-slate-100 text-slate-700"
 cell-class="bg-transparent text-slate-700"
 >
 <template #cell="{ record }">
 <div class="flex items-center justify-center">
 <a-button
 type="text"
 size="mini"
 class="!text-red-600 hover:!text-red-700"
 @click="
 () =>
 handleDelete(datasetId, record.id, () => {
 void loadDocuments(datasetId, req)
 void loadDataset(datasetId)
 })
 "
 >
 {{ t('common.actions.delete') }}
 </a-button>
 </div>
 </template>
 </a-table-column>
 </template>

 <template #empty>
 <a-empty
   :description="
     hasActiveSearch
       ? t('space.datasets.documents.empty.matched')
       : t('space.datasets.documents.empty.none')
   "
 />
 </template>
 </a-table>
 </div>
 </div>

 <hit-testing-modal v-model:visible="hitModalVisible" :dataset_id="datasetId" />
 <!-- 隐藏的文件选择器，由上传按钮触发 -->
 <input
 ref="fileInputRef"
 type="file"
 accept=".txt,.md,.markdown,.pdf,.docx,.doc,.csv"
 class="hidden"
 @change="handleFileChange"
 />
 </div>
</template>

<style scoped>
:deep(.arco-table-pagination) {
 padding: 16px 20px 20px;
}
</style>
