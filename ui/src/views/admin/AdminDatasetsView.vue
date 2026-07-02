<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import type { AdminDatasetRecord, GetAdminDatasetsRequest } from '@/models/admin-dataset'
import { listAdminDatasets } from '@/services/admin-datasets'
import { getErrorMessage } from '@/utils/error'

type DatasetPaginator = {
  total_record: number
  total_page: number
  current_page: number
  page_size: number
}

/**
 * 后台知识库管理页，负责跨账号知识库列表查询与分页浏览。
 */
const { t } = useI18n()

const loading = ref(false)
const datasets = ref<AdminDatasetRecord[]>([])
const paginator = ref<DatasetPaginator>({
  total_record: 0,
  total_page: 0,
  current_page: 1,
  page_size: 20,
})
const filters = ref<GetAdminDatasetsRequest>({
  search_word: '',
  current_page: 1,
  page_size: 20,
})

const hasActiveFilters = computed(() => Boolean(filters.value.search_word.trim()))
const emptyDescription = computed(() => {
  if (loading.value) return t('admin.datasetsAdmin.loading')
  return hasActiveFilters.value
    ? t('admin.datasetsAdmin.emptyFiltered')
    : t('admin.datasetsAdmin.empty')
})

/**
 * 拉取后台知识库列表并同步分页状态。
 */
const loadDatasets = async () => {
  loading.value = true
  try {
    const result = await listAdminDatasets({ ...filters.value })
    datasets.value = result.list
    paginator.value = result.paginator
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.datasetsAdmin.loadFailed')))
  } finally {
    loading.value = false
  }
}

/**
 * 触发搜索并重置到第一页。
 */
const handleSearch = async () => {
  filters.value.current_page = 1
  await loadDatasets()
}

/**
 * 切换分页并加载目标页数据。
 */
const handlePageChange = async (page: number) => {
  filters.value.current_page = page
  await loadDatasets()
}

/**
 * 格式化时间戳，便于在列表中展示更新时间。
 */
const formatTimestamp = (timestamp: number | null) => {
  return timestamp ? new Date(timestamp * 1000).toLocaleString() : '-'
}

/**
 * 将统计数字格式化为更易读的字符串。
 */
const formatCount = (value: number) => {
  return value.toLocaleString()
}

onMounted(() => {
  void loadDatasets()
})
</script>

<template>
  <section class="space-y-6">
    <header>
      <h1 class="text-2xl font-semibold text-slate-900">{{ t('admin.datasetsAdmin.title') }}</h1>
      <p class="mt-1 text-sm text-slate-500">{{ t('admin.datasetsAdmin.description') }}</p>
    </header>

    <section class="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4">
      <a-input
        v-model="filters.search_word"
        class="max-w-xl flex-1 min-w-[260px]"
        :placeholder="t('admin.datasetsAdmin.searchPlaceholder')"
        @press-enter="handleSearch"
      />
      <a-button type="primary" :loading="loading" @click="handleSearch">
        {{ t('common.actions.search') }}
      </a-button>
      <a-button :loading="loading" @click="loadDatasets">
        {{ t('common.actions.refresh') }}
      </a-button>
    </section>

    <section v-if="datasets.length" class="grid gap-4 xl:grid-cols-2">
      <article
        v-for="dataset in datasets"
        :key="dataset.id"
        class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-100"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <h2 class="truncate text-lg font-semibold text-slate-900">{{ dataset.name }}</h2>
            <p class="mt-2 text-sm text-slate-500">
              {{ dataset.description || t('admin.datasetsAdmin.noDescription') }}
            </p>
          </div>
          <a-button
            disabled
            size="small"
            data-testid="dataset-detail-disabled"
          >
            {{ t('admin.datasetsAdmin.detail') }}
          </a-button>
        </div>

        <dl class="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <div>
            <dt class="text-slate-400">{{ t('admin.datasetsAdmin.owner') }}</dt>
            <dd class="mt-1 text-slate-700">{{ dataset.creator_name || '-' }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">{{ t('admin.datasetsAdmin.updatedAt') }}</dt>
            <dd class="mt-1 text-slate-700">{{ formatTimestamp(dataset.updated_at) }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">{{ t('admin.datasetsAdmin.documentCount') }}</dt>
            <dd class="mt-1 text-slate-700">{{ formatCount(dataset.document_count) }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">{{ t('admin.datasetsAdmin.relatedAppCount') }}</dt>
            <dd class="mt-1 text-slate-700">{{ formatCount(dataset.related_app_count) }}</dd>
          </div>
          <div class="col-span-2">
            <dt class="text-slate-400">{{ t('admin.datasetsAdmin.characterCount') }}</dt>
            <dd class="mt-1 text-slate-700">{{ formatCount(dataset.character_count) }}</dd>
          </div>
        </dl>
      </article>
    </section>

    <section
      v-else
      class="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center"
    >
      <h2 class="text-lg font-medium text-slate-900">{{ t('admin.datasetsAdmin.emptyTitle') }}</h2>
      <p class="mt-2 text-sm text-slate-500">{{ emptyDescription }}</p>
    </section>

    <footer class="flex flex-wrap items-center justify-between gap-3">
      <span class="text-xs text-slate-400">
        {{ t('admin.datasetsAdmin.total', { count: paginator.total_record }) }}
      </span>
      <a-pagination
        v-if="paginator.total_page > 1"
        :current="paginator.current_page"
        :page-size="paginator.page_size"
        :total="paginator.total_record"
        size="small"
        show-total
        @change="handlePageChange"
      />
    </footer>
  </section>
</template>
