<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import type {
  AdminDatasetSegmentPageData,
  AdminDatasetSegmentRecord,
  GetAdminDatasetSegmentsRequest,
} from '@/models/admin-dataset-document'
import { listAdminDatasetSegments } from '@/services/admin-dataset-segments'
import { getErrorMessage } from '@/utils/error'

/**
 * 后台片段页使用的数据分页结构。
 */
type DatasetSegmentPaginator = AdminDatasetSegmentPageData['paginator']

const route = useRoute()
const { t } = useI18n()

const loading = ref(false)
const segments = ref<AdminDatasetSegmentRecord[]>([])
const paginator = ref<DatasetSegmentPaginator>({
  total_record: 0,
  total_page: 0,
  current_page: 1,
  page_size: 20,
})

const datasetId = computed(() => String(route.params.dataset_id ?? ''))
const documentId = computed(() => String(route.params.document_id ?? ''))

/**
 * 从当前路由查询参数构造后台片段列表请求参数。
 */
const buildRequestParams = (): GetAdminDatasetSegmentsRequest => {
  return {
    current_page: Number(route.query.current_page ?? 1),
    page_size: Number(route.query.page_size ?? 20),
    search_word: String(route.query.search_word ?? ''),
  }
}

/**
 * 拉取后台知识库片段列表，并同步页面展示数据。
 */
const loadSegments = async () => {
  if (!datasetId.value || !documentId.value) return

  loading.value = true
  try {
    const result = await listAdminDatasetSegments(datasetId.value, documentId.value, buildRequestParams())
    segments.value = result.list
    paginator.value = result.paginator
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.datasetSegments.loadFailed')))
  } finally {
    loading.value = false
  }
}

/**
 * 将片段统计数字格式化为便于阅读的字符串。
 */
const formatCount = (value: number) => {
  return value.toLocaleString()
}

/**
 * 将 Unix 时间戳格式化为本地时间展示。
 */
const formatTimestamp = (timestamp: number | null) => {
  return timestamp ? new Date(timestamp * 1000).toLocaleString() : '-'
}

onMounted(() => {
  void loadSegments()
})
</script>

<template>
  <section class="space-y-6">
    <header>
      <h1 class="text-2xl font-semibold text-slate-900">{{ t('admin.datasetSegments.title') }}</h1>
      <p class="mt-1 text-sm text-slate-500">
        {{ t('admin.datasetSegments.description', { datasetId, documentId }) }}
      </p>
    </header>

    <section
      class="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500"
    >
      <span>{{ t('admin.datasetSegments.documentLabel', { documentId }) }}</span>
      <span>{{ t('admin.datasetSegments.total', { count: paginator.total_record }) }}</span>
    </section>

    <section
      v-if="loading"
      class="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center text-sm text-slate-500"
    >
      {{ t('admin.datasetSegments.loading') }}
    </section>

    <section
      v-else-if="segments.length === 0"
      class="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center"
    >
      <h2 class="text-lg font-medium text-slate-900">{{ t('admin.datasetSegments.emptyTitle') }}</h2>
      <p class="mt-2 text-sm text-slate-500">{{ t('admin.datasetSegments.empty') }}</p>
    </section>

    <section v-else class="grid gap-4">
      <article
        v-for="segment in segments"
        :key="segment.id"
        class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-100"
      >
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <span
                class="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600"
              >
                #{{ segment.position }}
              </span>
              <span class="truncate text-xs text-slate-400">{{ segment.id }}</span>
            </div>
          </div>
          <span
            class="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600"
          >
            {{ segment.status || '-' }}
          </span>
        </div>

        <p class="mt-4 whitespace-pre-wrap break-all text-sm leading-6 text-slate-700">
          {{ segment.content }}
        </p>

        <dl class="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <div>
            <dt class="text-slate-400">{{ t('admin.datasetSegments.columns.characterCount') }}</dt>
            <dd class="mt-1 text-slate-700">{{ formatCount(segment.character_count) }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">{{ t('admin.datasetSegments.columns.hitCount') }}</dt>
            <dd class="mt-1 text-slate-700">{{ formatCount(segment.hit_count) }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">{{ t('admin.datasetSegments.columns.enabled') }}</dt>
            <dd class="mt-1 text-slate-700">
              {{ segment.enabled ? t('common.yes') : t('common.no') }}
            </dd>
          </div>
          <div>
            <dt class="text-slate-400">{{ t('admin.datasetSegments.columns.updatedAt') }}</dt>
            <dd class="mt-1 text-slate-700">{{ formatTimestamp(segment.updated_at) }}</dd>
          </div>
        </dl>
      </article>
    </section>
  </section>
</template>
