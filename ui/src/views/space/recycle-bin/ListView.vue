<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { listUserRecycleBin, restoreUserRecycleBinItem } from '@/services/user-recycle-bin'
import type { RecycleBinItem } from '@/models/recycle-bin'
import { getErrorCode, getErrorMessage, getErrorResponseData } from '@/utils/error'

const { t } = useI18n()

type DeviceInfo = { ip: string; name: string }

const loading = ref(false)
const restoringId = ref<number | null>(null)
const items = ref<RecycleBinItem[]>([])
const totalRecord = ref(0)
const searchWord = ref('')
const resourceTypeFilter = ref('')
const deletedByTypeFilter = ref('')
const currentPage = ref(1)
const pageSize = ref(20)

// 跨设备恢复（非本机删除）弹窗状态
const mismatchTarget = ref<RecycleBinItem | null>(null)
const recordedDevice = ref<DeviceInfo | null>(null)
const currentDevice = ref<DeviceInfo | null>(null)
const mismatchMode = ref<'original' | 'custom'>('original')
const customPath = ref('')

// 用户端回收站可能出现：知识库 / 知识库文档 / 本机文件 / 定时任务 / 外部数据源 / 会话 / 个人记忆
//（app/workflow/skill/mcp/api_tool 等仅 admin 端管理，用户 JWT 已被后端拦截）
const RESOURCE_TYPE_COLORS: Record<string, string> = {
  knowledge_base: 'arcoblue',
  knowledge_document: 'lime',
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
  user: 'blue',
  agent: 'orange',
}

const sourceFilterOptions = computed(() => [
  { label: t('userRecycleBin.sourceAll'), value: '' },
  { label: t('userRecycleBin.deletedByTypes.user'), value: 'user' },
  { label: t('userRecycleBin.deletedByTypes.agent'), value: 'agent' },
])

const resourceTypeOptions = computed(() => [
  { label: t('userRecycleBin.sourceAll'), value: '' },
  { label: t('userRecycleBin.resourceTypes.knowledge_base'), value: 'knowledge_base' },
  { label: t('userRecycleBin.resourceTypes.knowledge_document'), value: 'knowledge_document' },
  { label: t('userRecycleBin.resourceTypes.os_file'), value: 'os_file' },
  { label: t('userRecycleBin.resourceTypes.schedule_task'), value: 'schedule_task' },
  { label: t('userRecycleBin.resourceTypes.external_data_source'), value: 'external_data_source' },
  { label: t('userRecycleBin.resourceTypes.conversation'), value: 'conversation' },
  { label: t('userRecycleBin.resourceTypes.memory'), value: 'memory' },
])

const hasActiveFilters = computed(() =>
  Boolean(searchWord.value.trim()) ||
  Boolean(resourceTypeFilter.value) ||
  Boolean(deletedByTypeFilter.value),
)
const emptyDescription = computed(() =>
  hasActiveFilters.value
    ? t('userRecycleBin.emptyFiltered')
    : t('userRecycleBin.empty'),
)

const getTypeLabel = (type: string) => {
  const key = `userRecycleBin.resourceTypes.${type}`
  const label = t(key)
  return label === key ? type : label
}

const getSourceLabel = (source: string) => {
  const key = `userRecycleBin.deletedByTypes.${source}`
  const label = t(key)
  return label === key ? source : label
}

const getStatusLabel = (record: RecycleBinItem) => {
  if (record.status === 'pending' && record.expire_at) {
    const remainDays = Math.ceil((record.expire_at * 1000 - Date.now()) / 86400000)
    if (remainDays <= 0) return t('userRecycleBin.destroyNow')
    return t('userRecycleBin.destroyInDays', { days: remainDays })
  }
  const key = `userRecycleBin.statuses.${record.status}`
  const label = t(key)
  return label === key ? record.status : label
}

const getStatusColor = (record: RecycleBinItem) => {
  if (record.status === 'pending' && record.expire_at) {
    return record.expire_at * 1000 - Date.now() <= 0 ? 'red' : STATUS_COLORS.pending
  }
  return STATUS_COLORS[record.status] || 'gray'
}

const formatTime = (value: number | null | undefined) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const loadList = async () => {
  loading.value = true
  try {
    const result = await listUserRecycleBin({
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
    Message.error(getErrorMessage(error, t('userRecycleBin.loadFailed')))
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

const restoreTarget = ref<RecycleBinItem | null>(null)

const openRestoreModal = (item: RecycleBinItem) => {
  restoreTarget.value = item
}

const deviceLabel = (device: DeviceInfo | null | undefined): string => {
  if (!device) return t('userRecycleBin.deviceUnknown')
  const name = device.name || t('userRecycleBin.deviceUnknown')
  return device.ip ? `${name} (${device.ip})` : name
}

const handleRestore = async (
  item: RecycleBinItem,
  body?: { target_path?: string; confirm_device_mismatch?: boolean },
) => {
  restoringId.value = item.id
  try {
    await restoreUserRecycleBinItem(item.id, body)
    Message.success(t('userRecycleBin.restoreSuccess'))
    restoreTarget.value = null
    mismatchTarget.value = null
    await loadList()
  } catch (error) {
    if (getErrorCode(error) === 'device_mismatch') {
      // 非本机删除：弹出提示并提供「按原目录路径 / 自选路径」两种恢复方式
      const data = getErrorResponseData(error)
      recordedDevice.value = (data?.recorded_device as DeviceInfo | undefined) || null
      currentDevice.value = (data?.current_device as DeviceInfo | undefined) || null
      mismatchMode.value = 'original'
      customPath.value = ''
      mismatchTarget.value = item
      restoreTarget.value = null
    } else {
      Message.error(getErrorMessage(error, t('userRecycleBin.restoreFailed')))
    }
  } finally {
    restoringId.value = null
  }
}

const confirmMismatchRestore = () => {
  if (!mismatchTarget.value) return
  if (mismatchMode.value === 'custom') {
    const targetPath = customPath.value.trim()
    if (!targetPath) {
      Message.warning(t('userRecycleBin.customPathRequired'))
      return
    }
    void handleRestore(mismatchTarget.value, {
      confirm_device_mismatch: true,
      target_path: targetPath,
    })
    return
  }
  void handleRestore(mismatchTarget.value, { confirm_device_mismatch: true })
}

onMounted(() => {
  void loadList()
})
</script>

<template>
  <section class="space-y-5">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold text-slate-900">{{ t('userRecycleBin.title') }}</h1>
        <p class="mt-1 text-sm text-slate-500">{{ t('userRecycleBin.description') }}</p>
      </div>
      <a-alert type="info" :title="t('userRecycleBin.cannotEmpty')" class="max-w-md" />
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
          :placeholder="t('userRecycleBin.searchPlaceholder')"
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
        <a-table-column :title="t('userRecycleBin.columns.name')" data-index="resource_name" :width="220">
          <template #cell="{ record }">
            <div class="font-medium text-gray-800 truncate max-w-[220px]">
              {{ record.resource_name }}
            </div>
          </template>
        </a-table-column>
        <a-table-column :title="t('userRecycleBin.columns.type')" data-index="resource_type" :width="140">
          <template #cell="{ record }">
            <a-tag size="small" :color="RESOURCE_TYPE_COLORS[record.resource_type] || 'gray'">
              {{ getTypeLabel(record.resource_type) }}
            </a-tag>
          </template>
        </a-table-column>
        <a-table-column :title="t('userRecycleBin.columns.source')" data-index="deleted_by_type" :width="110">
          <template #cell="{ record }">
            <a-tag size="small" :color="SOURCE_COLORS[record.deleted_by_type] || 'gray'">
              {{ getSourceLabel(record.deleted_by_type) }}
            </a-tag>
          </template>
        </a-table-column>
        <a-table-column :title="t('userRecycleBin.columns.device')" data-index="device_info" :width="180">
          <template #cell="{ record }">
            <span v-if="record.resource_type === 'os_file'" class="text-xs text-gray-500">
              {{ deviceLabel(record.device_info) }}
            </span>
            <span v-else class="text-xs text-gray-300">-</span>
          </template>
        </a-table-column>
        <a-table-column :title="t('userRecycleBin.columns.deletedAt')" data-index="deleted_at" :width="170">
          <template #cell="{ record }">
            <span class="text-xs text-gray-500">{{ formatTime(record.deleted_at) }}</span>
          </template>
        </a-table-column>
        <a-table-column :title="t('userRecycleBin.columns.retention')" data-index="retention_days" :width="90">
          <template #cell="{ record }">
            <span class="text-xs text-gray-500">{{ record.retention_days }} 天</span>
          </template>
        </a-table-column>
        <a-table-column :title="t('userRecycleBin.columns.expireAt')" data-index="expire_at" :width="170">
          <template #cell="{ record }">
            <span class="text-xs text-gray-500">{{ formatTime(record.expire_at) }}</span>
          </template>
        </a-table-column>
        <a-table-column :title="t('userRecycleBin.columns.status')" data-index="status" :width="120">
          <template #cell="{ record }">
            <a-tag size="small" :color="getStatusColor(record)">
              {{ getStatusLabel(record) }}
            </a-tag>
          </template>
        </a-table-column>
        <a-table-column :title="t('userRecycleBin.columns.actions')" :width="100" fixed="right">
          <template #cell="{ record }">
            <a-button
              v-if="record.status === 'pending'"
              size="mini"
              type="outline"
              :loading="restoringId === record.id"
              @click="openRestoreModal(record)"
            >
              {{ t('userRecycleBin.restoreBtn') }}
            </a-button>
            <span v-else class="text-xs text-gray-300">-</span>
          </template>
        </a-table-column>
      </template>
      <template #empty>
        <div class="py-12 text-center">
          <p class="text-lg font-medium text-slate-900">{{ t('userRecycleBin.empty') }}</p>
          <p class="mt-2 text-sm text-slate-500">{{ emptyDescription }}</p>
        </div>
      </template>
    </a-table>

    <footer class="flex flex-wrap items-center justify-between gap-3">
      <span class="text-xs text-slate-400">
        {{ t('userRecycleBin.total', { count: totalRecord }) }}
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
      :title="t('userRecycleBin.restoreBtn')"
      :confirm-loading="restoringId !== null"
      :ok-text="t('userRecycleBin.restoreBtn')"
      :cancel-text="t('common.actions.cancel')"
      @ok="restoreTarget ? handleRestore(restoreTarget) : undefined"
      @cancel="restoreTarget = null"
    >
      <div class="space-y-3">
        <p class="text-sm text-slate-500">{{ t('userRecycleBin.restoreConfirm') }}</p>
        <div v-if="restoreTarget" class="rounded-lg bg-gray-50 px-3 py-2 text-sm">
          <span class="text-gray-500">{{ t('userRecycleBin.columns.name') }}: </span>
          <span class="font-medium text-gray-800">{{ restoreTarget.resource_name }}</span>
          <a-tag size="small" class="ml-2" :color="RESOURCE_TYPE_COLORS[restoreTarget.resource_type] || 'gray'">
            {{ getTypeLabel(restoreTarget.resource_type) }}
          </a-tag>
        </div>
        <div
          v-if="restoreTarget?.resource_type === 'os_file'"
          class="rounded-lg bg-gray-50 px-3 py-2 text-sm"
        >
          <span class="text-gray-500">{{ t('userRecycleBin.columns.device') }}: </span>
          <span class="text-gray-700">{{ deviceLabel(restoreTarget.device_info) }}</span>
        </div>
      </div>
    </a-modal>

    <!-- 非本机删除恢复确认弹窗（跨设备恢复） -->
    <a-modal
      :visible="mismatchTarget !== null"
      :title="t('userRecycleBin.deviceMismatchTitle')"
      :confirm-loading="restoringId !== null"
      :ok-text="t('userRecycleBin.deviceRestoreBtn')"
      :cancel-text="t('common.actions.cancel')"
      @ok="confirmMismatchRestore"
      @cancel="mismatchTarget = null"
    >
      <div class="space-y-3">
        <p class="text-sm text-slate-500">{{ t('userRecycleBin.deviceMismatchDesc') }}</p>
        <div class="rounded-lg bg-orange-50 px-3 py-2 text-sm">
          <div class="flex items-center gap-1">
            <icon-exclamation-circle-fill class="text-orange-500" />
            <span class="font-medium text-orange-700">{{ t('userRecycleBin.deviceMismatchWarning') }}</span>
          </div>
          <div class="mt-1 text-gray-600">
            <span>{{ t('userRecycleBin.deviceRecorded') }}: </span>
            <span class="font-medium text-gray-800">{{ deviceLabel(recordedDevice) }}</span>
          </div>
          <div class="text-gray-600">
            <span>{{ t('userRecycleBin.deviceCurrent') }}: </span>
            <span class="font-medium text-gray-800">{{ deviceLabel(currentDevice) }}</span>
          </div>
        </div>
        <a-radio-group v-model="mismatchMode" direction="vertical">
          <a-radio value="original">{{ t('userRecycleBin.deviceRestoreOriginal') }}</a-radio>
          <a-radio value="custom">
            <span class="mr-2">{{ t('userRecycleBin.deviceRestoreCustom') }}</span>
            <a-input
              v-if="mismatchMode === 'custom'"
              v-model="customPath"
              class="w-full"
              :placeholder="t('userRecycleBin.deviceCustomPathPlaceholder')"
            />
          </a-radio>
        </a-radio-group>
      </div>
    </a-modal>
  </section>
</template>
