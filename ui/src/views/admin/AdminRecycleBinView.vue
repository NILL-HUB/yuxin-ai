<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { listRecycleBin, restoreRecycleBinItem } from '@/services/admin-recycle-bin'
import type { RecycleBinItem } from '@/models/recycle-bin'
import { getErrorMessage } from '@/utils/error'
import { useAdminStore } from '@/stores/admin'

const { t } = useI18n()
const adminStore = useAdminStore()

const loading = ref(false)
const restoringId = ref<number | null>(null)
const items = ref<RecycleBinItem[]>([])
const totalRecord = ref(0)
const searchWord = ref('')
const resourceTypeFilter = ref('')
const deletedByTypeFilter = ref('admin')
const currentPage = ref(1)
const pageSize = ref(20)

const canRestore = computed(() => adminStore.hasPermission('recycle_bin:write'))

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
  Boolean(deletedByTypeFilter.value),
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
 * 状态列展示：待销毁(pending) 改为相对时间"X天后销毁"，
 * 其余状态沿用固定标签。
 */
const getStatusLabel = (record: RecycleBinItem) => {
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
  if (record.status === 'pending' && record.expire_at) {
    return record.expire_at * 1000 - Date.now() <= 0 ? 'red' : STATUS_COLORS.pending
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
      status: 'pending',
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

const handleSearch = () => {
  currentPage.value = 1
  void loadList()
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

onMounted(() => {
  void loadList()
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
              v-if="canRestore && record.status === 'pending'"
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
  </section>
</template>
