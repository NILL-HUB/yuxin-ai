<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  cleanupExpiredRecycleBin,
  getRecycleBinOverview,
  listRecycleBin,
  restoreRecycleBinItem,
  type RecycleBinOverviewData,
} from '@/services/admin-recycle-bin'
import type { RecycleBinItem } from '@/models/recycle-bin'
import { getErrorMessage } from '@/utils/error'
import { useAdminStore } from '@/stores/admin'

const { t } = useI18n()
const adminStore = useAdminStore()

const loading = ref(false)
const overviewLoading = ref(false)
const restoringId = ref<number | null>(null)
const cleaning = ref(false)
const items = ref<RecycleBinItem[]>([])
const totalRecord = ref(0)
const overview = ref<RecycleBinOverviewData>({
  total: 0,
  pending_total: 0,
  by_status: [],
  by_resource_type: [],
  by_deleted_by_type: [],
})
const searchWord = ref('')
const resourceTypeFilter = ref('')
const deletedByTypeFilter = ref('admin')
const statusFilter = ref('pending')
const currentPage = ref(1)
const pageSize = ref(20)

const canRestore = computed(() => adminStore.hasPermission('recycle_bin:write'))
const canCleanExpired = computed(() => adminStore.hasPermission('recycle_bin:write'))

const RESOURCE_TYPE_COLORS: Record<string, string> = {
  knowledge_base: 'arcoblue',
  system_prompt: 'purple',
  app: 'green',
  workflow: 'cyan',
  skill: 'magenta',
  mcp: 'orange',
  api_tool: 'orangered',
  knowledge_document: 'lime',
  upload_file: 'gold',
  os_file: 'brown',
  schedule_task: 'green',
  external_data_source: 'purple',
  conversation: 'cyan',
  memory: 'magenta',
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'gold',
  restored: 'green',
  expired: 'gray',
}

const SOURCE_COLORS: Record<string, string> = {
  admin: 'purple',
  user: 'blue',
  agent: 'orange',
}

const sourceFilterOptions = computed(() => [
  { label: t('admin.recycleBin.sourceAll'), value: '' },
  { label: t('admin.recycleBin.deletedByTypes.admin'), value: 'admin' },
  { label: t('admin.recycleBin.deletedByTypes.user'), value: 'user' },
  { label: t('admin.recycleBin.deletedByTypes.agent'), value: 'agent' },
])

const statusFilterOptions = computed(() => [
  { label: t('admin.recycleBin.statusFilter.all'), value: '' },
  { label: t('admin.recycleBin.statusFilter.pending'), value: 'pending' },
  { label: t('admin.recycleBin.statusFilter.expired'), value: 'expired' },
  { label: t('admin.recycleBin.statusFilter.restored'), value: 'restored' },
])

const resourceTypeOptions = computed(() => [
  { label: t('admin.recycleBin.filterAll'), value: '' },
  { label: t('admin.recycleBin.resourceTypes.knowledge_base'), value: 'knowledge_base' },
  { label: t('admin.recycleBin.resourceTypes.system_prompt'), value: 'system_prompt' },
  { label: t('admin.recycleBin.resourceTypes.app'), value: 'app' },
  { label: t('admin.recycleBin.resourceTypes.workflow'), value: 'workflow' },
  { label: t('admin.recycleBin.resourceTypes.skill'), value: 'skill' },
  { label: t('admin.recycleBin.resourceTypes.mcp'), value: 'mcp' },
  { label: t('admin.recycleBin.resourceTypes.api_tool'), value: 'api_tool' },
  { label: t('admin.recycleBin.resourceTypes.knowledge_document'), value: 'knowledge_document' },
  { label: t('admin.recycleBin.resourceTypes.upload_file'), value: 'upload_file' },
  { label: t('admin.recycleBin.resourceTypes.os_file'), value: 'os_file' },
  { label: t('admin.recycleBin.resourceTypes.schedule_task'), value: 'schedule_task' },
  { label: t('admin.recycleBin.resourceTypes.external_data_source'), value: 'external_data_source' },
  { label: t('admin.recycleBin.resourceTypes.conversation'), value: 'conversation' },
  { label: t('admin.recycleBin.resourceTypes.memory'), value: 'memory' },
])

const hasActiveFilters = computed(() =>
  Boolean(searchWord.value.trim()) ||
  Boolean(resourceTypeFilter.value) ||
  Boolean(deletedByTypeFilter.value) ||
  Boolean(statusFilter.value),
)
const emptyDescription = computed(() =>
  hasActiveFilters.value
    ? t('admin.recycleBin.emptyFiltered')
    : t('admin.recycleBin.empty'),
)

const getTypeLabel = (type: string) => {
  const key = `admin.recycleBin.resourceTypes.${type}`
  const label = t(key)
  return label === key ? type : label
}

const getSourceLabel = (source: string) => {
  const key = `admin.recycleBin.deletedByTypes.${source}`
  const label = t(key)
  return label === key ? source : label
}

/**
 * 是否已到留存期（剩余天数为 0 及以下）。已到期待销毁，不可恢复。
 */
const isExpired = (record: RecycleBinItem) =>
  record.status === 'pending' &&
  !!record.expire_at &&
  record.expire_at * 1000 - Date.now() <= 0

const getStatusLabel = (record: RecycleBinItem) => {
  if (isExpired(record)) return t('admin.recycleBin.destroyNow')
  if (record.status === 'pending' && record.expire_at) {
    const remainDays = Math.ceil((record.expire_at * 1000 - Date.now()) / 86400000)
    if (remainDays <= 0) return t('admin.recycleBin.destroyNow')
    return t('admin.recycleBin.destroyInDays', { days: remainDays })
  }
  const key = `admin.recycleBin.statuses.${record.status}`
  const label = t(key)
  return label === key ? record.status : label
}

const getStatusColor = (record: RecycleBinItem) => {
  if (isExpired(record)) return 'red'
  if (record.status === 'pending' && record.expire_at) {
    return STATUS_COLORS.pending
  }
  return STATUS_COLORS[record.status] || 'gray'
}

const getDeletedByName = (record: RecycleBinItem) => {
  if (record.deleted_by_name) return record.deleted_by_name
  if (!record.deleted_by) return '-'
  return t('admin.recycleBin.unknownUser')
}

const formatTime = (value: number | null | undefined) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const loadList = async () => {
  loading.value = true
  try {
    const result = await listRecycleBin({
      page: currentPage.value,
      page_size: pageSize.value,
      resource_type: resourceTypeFilter.value || undefined,
      deleted_by_type: deletedByTypeFilter.value || undefined,
      status: statusFilter.value || undefined,
      search_word: searchWord.value.trim(),
    })
    items.value = result.items || []
    totalRecord.value = result.total_record ?? result.total ?? 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.recycleBin.loadFailed')))
  } finally {
    loading.value = false
  }
}

const loadOverview = async () => {
  overviewLoading.value = true
  try {
    overview.value = await getRecycleBinOverview({
      resource_type: resourceTypeFilter.value || undefined,
      deleted_by_type: deletedByTypeFilter.value || undefined,
      status: statusFilter.value || undefined,
      search_word: searchWord.value.trim(),
    })
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.recycleBin.overviewLoadFailed')))
  } finally {
    overviewLoading.value = false
  }
}

const reloadAll = async () => {
  await Promise.all([loadList(), loadOverview()])
}

const handleSearch = () => {
  currentPage.value = 1
  void reloadAll()
}

const handlePageChange = (page: number) => {
  currentPage.value = page
  void loadList()
}

const handlePageSizeChange = (size: number) => {
  pageSize.value = size
  currentPage.value = 1
  void loadList()
}

const statusBarColor = (status: string) => {
  const colors: Record<string, string> = {
    pending: 'bg-amber-400',
    restored: 'bg-emerald-500',
    expired: 'bg-slate-300',
  }
  return colors[status] || 'bg-slate-300'
}

const typeBarColor = (type: string) => {
  const colors: Record<string, string> = {
    knowledge_base: 'bg-sky-500',
    system_prompt: 'bg-purple-500',
    app: 'bg-emerald-500',
    workflow: 'bg-cyan-500',
    skill: 'bg-fuchsia-500',
    mcp: 'bg-orange-500',
    api_tool: 'bg-orange-400',
    knowledge_document: 'bg-lime-500',
    upload_file: 'bg-amber-400',
    os_file: 'bg-stone-500',
    schedule_task: 'bg-teal-500',
    external_data_source: 'bg-indigo-500',
    conversation: 'bg-cyan-400',
    memory: 'bg-pink-500',
  }
  return colors[type] || 'bg-slate-300'
}

const statusDistribution = computed(() => {
  const rows = overview.value.by_status || []
  const max = Math.max(1, ...rows.map((row) => row.count))
  return rows.map((row) => ({
    ...row,
    percentage: Math.round((row.count / max) * 100),
    color: statusBarColor(row.name),
    label: t(`admin.recycleBin.statuses.${row.name}`) !== `admin.recycleBin.statuses.${row.name}` ? t(`admin.recycleBin.statuses.${row.name}`) : row.name,
  }))
})

const typeDistribution = computed(() => {
  const rows = (overview.value.by_resource_type || []).slice(0, 8)
  const max = Math.max(1, ...rows.map((row) => row.count))
  return rows.map((row) => ({
    ...row,
    percentage: Math.round((row.count / max) * 100),
    color: typeBarColor(row.name),
    label: getTypeLabel(row.name),
  }))
})

const sourceDistribution = computed(() => {
  const rows = overview.value.by_deleted_by_type || []
  const max = Math.max(1, ...rows.map((row) => row.count))
  return rows.map((row) => ({
    ...row,
    percentage: Math.round((row.count / max) * 100),
    label: getSourceLabel(row.name),
  }))
})

const kpiCards = computed(() => [
  {
    key: 'pending',
    label: t('admin.recycleBin.pendingTotal'),
    hint: t('admin.recycleBin.pendingTotalHint'),
    value: overview.value.pending_total,
    color: 'text-amber-600',
    icon: 'bg-amber-50',
  },
  {
    key: 'total',
    label: t('admin.recycleBin.totalCount'),
    hint: t('admin.recycleBin.totalCountHint'),
    value: overview.value.total,
    color: 'text-slate-900',
    icon: 'bg-sky-50',
  },
])

const handleRestore = async (item: RecycleBinItem) => {
  restoringId.value = item.id
  try {
    await restoreRecycleBinItem(item.id)
    Message.success(t('admin.recycleBin.restoreSuccess'))
    restoreTarget.value = null
    await loadList()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.recycleBin.restoreFailed')))
  } finally {
    restoringId.value = null
  }
}

const restoreTarget = ref<RecycleBinItem | null>(null)

const openRestoreModal = (item: RecycleBinItem) => {
  restoreTarget.value = item
}

const cleanModalVisible = ref(false)
const openCleanModal = () => {
  cleanModalVisible.value = true
}

const handleCleanExpired = async () => {
  cleaning.value = true
  try {
    const count = await cleanupExpiredRecycleBin()
    cleanModalVisible.value = false
    if (count > 0) {
      Message.success(t('admin.recycleBin.cleanExpiredSuccess', { count }))
    } else {
      Message.info(t('admin.recycleBin.cleanExpiredEmpty'))
    }
    await reloadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.recycleBin.cleanExpiredFailed')))
  } finally {
    cleaning.value = false
  }
}

onMounted(() => {
  void reloadAll()
})
</script>

<template>
  <section class="space-y-5">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold text-slate-900">{{ t('admin.recycleBin.title') }}</h1>
        <p class="mt-1 text-sm text-slate-500">{{ t('admin.recycleBin.description') }}</p>
      </div>
      <a-alert type="info" :title="t('admin.recycleBin.cannotEmpty')" class="max-w-md" />
    </header>

    <section class="space-y-4">
      <div class="flex items-end justify-between gap-4">
        <div>
          <h2 class="text-lg font-semibold text-slate-900">{{ t('admin.recycleBin.overview') }}</h2>
          <p class="mt-1 text-sm text-slate-500">{{ t('admin.recycleBin.overviewDescription') }}</p>
        </div>
        <a-button type="outline" size="small" :loading="overviewLoading" @click="loadOverview">
          {{ t('common.actions.refresh') }}
        </a-button>
      </div>

      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <article
          v-for="card in kpiCards"
          :key="card.key"
          class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
        >
          <div class="flex items-center gap-2">
            <span class="flex h-8 w-8 items-center justify-center rounded-lg" :class="card.icon">
              <svg v-if="card.key === 'pending'" class="h-4 w-4 text-amber-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 8v4l3 3" /><circle cx="12" cy="12" r="9" />
              </svg>
              <svg v-else class="h-4 w-4 text-sky-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
              </svg>
            </span>
            <p class="text-sm font-medium text-slate-500">{{ card.label }}</p>
            <a-tooltip :content="card.hint" position="top">
              <svg class="h-3.5 w-3.5 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="9" /><path d="M12 16v-4M12 8h.01" />
              </svg>
            </a-tooltip>
          </div>
          <div v-if="overviewLoading" class="mt-3 h-8 w-20 animate-pulse rounded bg-slate-100" aria-hidden="true" />
          <strong v-else class="mt-3 block text-3xl font-semibold tracking-tight" :class="card.color">
            {{ Number(card.value).toLocaleString() }}
          </strong>
        </article>

        <article class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm md:col-span-2 xl:col-span-1">
          <h3 class="text-sm font-semibold text-slate-700">{{ t('admin.recycleBin.trendTitle') }}</h3>
          <p class="mt-0.5 text-xs text-slate-400">{{ t('admin.recycleBin.trendDescription') }}</p>
          <div v-if="!overviewLoading && statusDistribution.length" class="mt-3 space-y-2.5">
            <div v-for="row in statusDistribution" :key="row.name" class="space-y-1">
              <div class="flex items-center justify-between text-xs">
                <span class="text-slate-500">{{ row.label }}</span>
                <span class="font-medium text-slate-700">{{ row.count }}</span>
              </div>
              <div class="h-2 w-full overflow-hidden rounded-full bg-slate-100">
                <div class="h-full rounded-full transition-all" :class="row.color" :style="{ width: `${row.percentage}%` }" />
              </div>
            </div>
          </div>
          <p v-else-if="!overviewLoading" class="mt-6 text-center text-xs text-slate-400">
            {{ t('admin.recycleBin.noData') }}
          </p>
        </article>
      </div>

      <div class="grid gap-4 lg:grid-cols-2">
        <article class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <h3 class="text-sm font-semibold text-slate-700">{{ t('admin.recycleBin.distributionTypeTitle') }}</h3>
          <p class="mt-0.5 text-xs text-slate-400">{{ t('admin.recycleBin.distributionTypeDescription') }}</p>
          <div v-if="!overviewLoading && typeDistribution.length" class="mt-3 space-y-2.5">
            <div v-for="row in typeDistribution" :key="row.name" class="space-y-1">
              <div class="flex items-center justify-between text-xs">
                <span class="truncate text-slate-500">{{ row.label }}</span>
                <span class="font-medium text-slate-700">{{ row.count }}</span>
              </div>
              <div class="h-2 w-full overflow-hidden rounded-full bg-slate-100">
                <div class="h-full rounded-full transition-all" :class="row.color" :style="{ width: `${row.percentage}%` }" />
              </div>
            </div>
          </div>
          <p v-else-if="!overviewLoading" class="mt-6 text-center text-xs text-slate-400">
            {{ t('admin.recycleBin.noData') }}
          </p>
        </article>

        <article class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <h3 class="text-sm font-semibold text-slate-700">{{ t('admin.recycleBin.distributionSourceTitle') }}</h3>
          <p class="mt-0.5 text-xs text-slate-400">{{ t('admin.recycleBin.distributionSourceDescription') }}</p>
          <div v-if="!overviewLoading && sourceDistribution.length" class="mt-3 space-y-2.5">
            <div v-for="row in sourceDistribution" :key="row.name" class="space-y-1">
              <div class="flex items-center justify-between text-xs">
                <span class="text-slate-500">{{ row.label }}</span>
                <span class="font-medium text-slate-700">{{ row.count }}</span>
              </div>
              <div class="h-2 w-full overflow-hidden rounded-full bg-slate-100">
                <div class="h-full rounded-full bg-slate-400 transition-all" :style="{ width: `${row.percentage}%` }" />
              </div>
            </div>
          </div>
          <p v-else-if="!overviewLoading" class="mt-6 text-center text-xs text-slate-400">
            {{ t('admin.recycleBin.noData') }}
          </p>
        </article>
      </div>
    </section>

    <section class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <a-select
          v-model="deletedByTypeFilter"
          class="w-40"
          :options="sourceFilterOptions"
          @change="handleSearch"
        />
        <a-select
          v-model="resourceTypeFilter"
          class="w-48"
          :options="resourceTypeOptions"
          allow-clear
          @change="handleSearch"
        />
        <a-select
          v-model="statusFilter"
          class="w-36"
          :options="statusFilterOptions"
          @change="handleSearch"
        />
        <a-input
          v-model="searchWord"
          class="w-full sm:w-[240px]"
          :placeholder="t('admin.recycleBin.searchPlaceholder')"
          allow-clear
          @press-enter="handleSearch"
          @clear="handleSearch"
        />
        <a-button type="primary" :loading="loading" @click="handleSearch">
          {{ t('common.actions.search') }}
        </a-button>
        <a-button :loading="loading" @click="loadList">
          {{ t('common.actions.refresh') }}
        </a-button>
        <a-button v-if="canCleanExpired" status="danger" :loading="cleaning" @click="openCleanModal">
          {{ t('admin.recycleBin.cleanExpiredBtn') }}
        </a-button>
      </div>
    </section>

    <a-table
      :data="items"
      :loading="loading"
      :pagination="false"
      row-key="id"
      class="rounded-xl border border-slate-200 bg-white overflow-hidden"
      :scroll="{ x: 1000 }"
    >
      <template #columns>
        <a-table-column :title="t('admin.recycleBin.columns.name')" data-index="resource_name" :width="220">
          <template #cell="{ record }">
            <div class="font-medium text-gray-800 truncate max-w-[220px]">
              {{ record.resource_name }}
            </div>
          </template>
        </a-table-column>
        <a-table-column :title="t('admin.recycleBin.columns.type')" data-index="resource_type" :width="150">
          <template #cell="{ record }">
            <a-tag size="small" :color="RESOURCE_TYPE_COLORS[record.resource_type] || 'gray'">
              {{ getTypeLabel(record.resource_type) }}
            </a-tag>
          </template>
        </a-table-column>
        <a-table-column :title="t('admin.recycleBin.columns.source')" data-index="deleted_by_type" :width="110">
          <template #cell="{ record }">
            <a-tag size="small" :color="SOURCE_COLORS[record.deleted_by_type] || 'gray'">
              {{ getSourceLabel(record.deleted_by_type) }}
            </a-tag>
          </template>
        </a-table-column>
        <a-table-column :title="t('admin.recycleBin.columns.deletedBy')" data-index="deleted_by" :width="130">
          <template #cell="{ record }">
            <span class="text-xs text-gray-500">{{ getDeletedByName(record) }}</span>
          </template>
        </a-table-column>
        <a-table-column :title="t('admin.recycleBin.columns.deletedAt')" data-index="deleted_at" :width="170">
          <template #cell="{ record }">
            <span class="text-xs text-gray-500">{{ formatTime(record.deleted_at) }}</span>
          </template>
        </a-table-column>
        <a-table-column :title="t('admin.recycleBin.columns.retention')" data-index="retention_days" :width="90">
          <template #cell="{ record }">
            <span class="text-xs text-gray-500">{{ record.retention_days }} 天</span>
          </template>
        </a-table-column>
        <a-table-column :title="t('admin.recycleBin.columns.expireAt')" data-index="expire_at" :width="170">
          <template #cell="{ record }">
            <span class="text-xs text-gray-500">{{ formatTime(record.expire_at) }}</span>
          </template>
        </a-table-column>
        <a-table-column :title="t('admin.recycleBin.columns.status')" data-index="status" :width="120">
          <template #cell="{ record }">
            <a-tag size="small" :color="getStatusColor(record)">
              {{ getStatusLabel(record) }}
            </a-tag>
          </template>
        </a-table-column>
        <a-table-column :title="t('admin.recycleBin.columns.actions')" :width="100" fixed="right">
          <template #cell="{ record }">
            <a-button
              v-if="canRestore && record.status === 'pending' && !isExpired(record)"
              size="mini"
              type="outline"
              :loading="restoringId === record.id"
              @click="openRestoreModal(record)"
            >
              {{ t('admin.recycleBin.restoreBtn') }}
            </a-button>
            <span v-else class="text-xs text-gray-300">-</span>
          </template>
        </a-table-column>
      </template>
      <template #empty>
        <div class="py-12 text-center">
          <p class="text-lg font-medium text-slate-900">{{ t('admin.recycleBin.empty') }}</p>
          <p class="mt-2 text-sm text-slate-500">{{ emptyDescription }}</p>
        </div>
      </template>
    </a-table>

    <footer class="flex flex-wrap items-center justify-between gap-3">
      <span class="text-xs text-slate-400">
        {{ t('admin.recycleBin.total', { count: totalRecord }) }}
      </span>
      <a-pagination
        v-if="totalRecord > 0"
        :current="currentPage"
        :page-size="pageSize"
        :total="totalRecord"
        size="small"
        show-total
        show-page-size
        :page-size-options="[10, 20, 50, 100]"
        @change="handlePageChange"
        @page-size-change="handlePageSizeChange"
      />
    </footer>

    <!-- 恢复确认弹窗 -->
    <a-modal
      :visible="restoreTarget !== null"
      :title="t('admin.recycleBin.restoreBtn')"
      :confirm-loading="restoringId !== null"
      :ok-text="t('admin.recycleBin.restoreBtn')"
      :cancel-text="t('common.actions.cancel')"
      @ok="restoreTarget ? handleRestore(restoreTarget) : undefined"
      @cancel="restoreTarget = null"
    >
      <div class="space-y-3">
        <p class="text-sm text-slate-500">{{ t('admin.recycleBin.restoreConfirm') }}</p>
        <div v-if="restoreTarget" class="rounded-lg bg-gray-50 px-3 py-2 text-sm">
          <span class="text-gray-500">{{ t('admin.recycleBin.columns.name') }}: </span>
          <span class="font-medium text-gray-800">{{ restoreTarget.resource_name }}</span>
          <a-tag size="small" class="ml-2" :color="RESOURCE_TYPE_COLORS[restoreTarget.resource_type] || 'gray'">
            {{ getTypeLabel(restoreTarget.resource_type) }}
          </a-tag>
        </div>
      </div>
    </a-modal>

    <!-- 清理已销毁记录确认弹窗 -->
    <a-modal
      :visible="cleanModalVisible"
      :title="t('admin.recycleBin.cleanExpiredBtn')"
      :confirm-loading="cleaning"
      :ok-text="t('admin.recycleBin.cleanExpiredBtn')"
      :cancel-text="t('common.actions.cancel')"
      @ok="handleCleanExpired"
      @cancel="cleanModalVisible = false"
    >
      <p class="text-sm text-slate-500">{{ t('admin.recycleBin.cleanExpiredConfirm') }}</p>
    </a-modal>
  </section>
</template>
