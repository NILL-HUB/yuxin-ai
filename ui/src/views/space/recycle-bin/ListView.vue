<script setup lang="ts">
/**
 * 回收站 — 视觉对齐画布原型 recycle-bin.html
 *
 * 数据源：真实接口 /space/recycle-bin（列表、恢复、跨设备恢复、清理、分页）。
 * 视觉结构沿用已确认的模拟数据版本，仅将数据层替换为接口。
 */
import { onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  cleanupExpiredUserRecycleBin,
  listUserRecycleBin,
  restoreUserRecycleBinItem,
} from '@/services/user-recycle-bin'
import type { RecycleBinItem } from '@/models/recycle-bin'
import { getErrorCode, getErrorMessage, getErrorResponseData } from '@/utils/error'

const { t } = useI18n()

const loading = ref(false)
const restoringId = ref<number | null>(null)
const cleaning = ref(false)
const items = ref<RecycleBinItem[]>([])
const totalRecord = ref(0)
const searchWord = ref('')
const resourceTypeFilter = ref('')
const deletedByTypeFilter = ref('')
const statusFilter = ref('pending')
const currentPage = ref(1)
const pageSize = ref(20)

type DeviceInfo = { ip: string; name: string }

// 资源类型 → 图标名（仅使用已全局注册的 Arco 图标）
const TYPE_ICON: Record<string, string> = {
  knowledge_base: 'icon-storage',
  knowledge_document: 'icon-file',
  os_file: 'icon-file',
  schedule_task: 'icon-schedule',
  external_data_source: 'icon-cloud',
  conversation: 'icon-message',
  memory: 'icon-mind-mapping',
}

const getTypeLabel = (type: string) => {
  const key = `userRecycleBin.resourceTypes.${type}`
  const label = t(key)
  return label === key ? type : label
}

const getTypeIcon = (type: string) => TYPE_ICON[type] || 'icon-file'

const getSourceLabel = (source: string) => {
  const key = `userRecycleBin.deletedByTypes.${source}`
  const label = t(key)
  return label === key ? source : label
}

const formatDate = (value: number | null | undefined) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleDateString('zh-CN', { hour12: false })
}

const isExpired = (record: RecycleBinItem) =>
  record.status === 'pending' &&
  !!record.expire_at &&
  record.expire_at * 1000 - Date.now() <= 0

// 状态文案：待销毁显示剩余天数，否则显示状态
const getStatusText = (record: RecycleBinItem) => {
  if (isExpired(record)) return t('userRecycleBin.destroyNow')
  if (record.status === 'pending' && record.expire_at) {
    const remainDays = Math.ceil((record.expire_at * 1000 - Date.now()) / 86400000)
    if (remainDays <= 0) return t('userRecycleBin.destroyNow')
    return t('userRecycleBin.destroyInDays', { days: remainDays })
  }
  const key = `userRecycleBin.statuses.${record.status}`
  const label = t(key)
  return label === key ? record.status : label
}

// 状态 → 徽标样式
const statusChipClass = (record: RecycleBinItem) => {
  if (isExpired(record) || record.status === 'expired') return 'status-chip-neutral'
  if (record.status === 'pending') return 'status-chip-accent'
  return 'status-chip-soft'
}

const loadList = async () => {
  loading.value = true
  try {
    const result = await listUserRecycleBin({
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

// 跨设备恢复（非本地删除）弹窗状态
const mismatchTarget = ref<RecycleBinItem | null>(null)
const recordedDevice = ref<DeviceInfo | null>(null)
const currentDevice = ref<DeviceInfo | null>(null)
const mismatchMode = ref<'original' | 'custom'>('original')
const customPath = ref('')

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

const cleanModalVisible = ref(false)
const openCleanModal = () => {
  cleanModalVisible.value = true
}

const handleCleanExpired = async () => {
  cleaning.value = true
  try {
    const count = await cleanupExpiredUserRecycleBin()
    cleanModalVisible.value = false
    if (count > 0) {
      Message.success(t('userRecycleBin.cleanExpiredSuccess', { count }))
    } else {
      Message.info(t('userRecycleBin.cleanExpiredEmpty'))
    }
    await loadList()
  } catch (error) {
    Message.error(getErrorMessage(error, t('userRecycleBin.cleanExpiredFailed')))
  } finally {
    cleaning.value = false
  }
}

onMounted(() => {
  void loadList()
})
</script>

<template>
  <!-- 页面根：文档流滚动（内容对齐画布原型内容区） -->
  <div class="recycle-mock min-h-full w-full overflow-y-auto">
    <div class="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 lg:px-10 lg:py-10">
      <!-- 页头 -->
      <header>
        <!-- 标题 + 操作：同排两端，按钮不被挤压 -->
        <div class="flex items-center justify-between gap-4">
          <h1 class="recycle-title text-3xl font-semibold sm:text-4xl">回收站</h1>
          <button
            type="button"
            class="cleanup-mock inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-[var(--aicss-radius)] px-4 py-2.5 text-sm font-medium transition hover:-translate-y-0.5"
            :disabled="cleaning"
            @click="openCleanModal"
          >
            <icon-delete class="h-4 w-4" />
            {{ t('userRecycleBin.cleanExpiredBtn') }}
          </button>
        </div>
        <!-- 长描述独占一行，不参与横向挤压 -->
        <p class="mt-2 max-w-3xl text-sm leading-relaxed text-muted">
          {{ t('userRecycleBin.description') }}
        </p>
      </header>

      <!-- 提示条 -->
      <div role="status" class="mt-6 flex items-start gap-3 rounded-[var(--aicss-radius)] bg-surface-2 px-4 py-3.5 text-sm text-text-2">
        <icon-info-circle class="mt-0.5 h-4 w-4 shrink-0 text-brand" />
        <p>{{ t('userRecycleBin.cannotEmpty') }}</p>
      </div>

      <!-- 筛选工具栏 -->
      <div class="mt-6 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div class="relative w-full lg:w-72">
          <icon-search class="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <input
            v-model="searchWord"
            type="search"
            placeholder="搜索删除的内容"
            aria-label="搜索删除的内容"
            class="mock-input w-full rounded-[var(--aicss-radius)] border border-border-c bg-surface py-2.5 pl-10 pr-4 text-sm text-text placeholder:text-muted transition hover:border-[var(--aicss-border-strong)] focus:border-brand focus:outline-hidden focus:ring-2 focus:ring-[var(--aicss-accent-soft)]"
            @keyup.enter="handleSearch"
          />
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <div class="relative">
            <select
              v-model="deletedByTypeFilter"
              aria-label="删除来源筛选"
              class="mock-input appearance-none rounded-[var(--aicss-radius)] border border-border-c bg-surface py-2.5 pl-3.5 pr-9 text-sm text-text transition hover:border-[var(--aicss-border-strong)] focus:border-brand focus:outline-hidden focus:ring-2 focus:ring-[var(--aicss-accent-soft)]"
              @change="handleSearch"
            >
              <option value="">全部来源</option>
              <option value="user">用户删除</option>
              <option value="agent">Agent 删除</option>
            </select>
            <icon-down class="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          </div>
          <div class="relative">
            <select
              v-model="resourceTypeFilter"
              aria-label="资源类型筛选"
              class="mock-input appearance-none rounded-[var(--aicss-radius)] border border-border-c bg-surface py-2.5 pl-3.5 pr-9 text-sm text-text transition hover:border-[var(--aicss-border-strong)] focus:border-brand focus:outline-hidden focus:ring-2 focus:ring-[var(--aicss-accent-soft)]"
              @change="handleSearch"
            >
              <option value="">全部类型</option>
              <option value="knowledge_base">知识库</option>
              <option value="knowledge_document">知识库文档</option>
              <option value="os_file">本地文件</option>
              <option value="schedule_task">定时任务</option>
              <option value="external_data_source">外部数据源</option>
              <option value="conversation">会话</option>
              <option value="memory">记忆</option>
            </select>
            <icon-down class="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          </div>
          <div class="relative">
            <select
              v-model="statusFilter"
              aria-label="状态筛选"
              class="mock-input appearance-none rounded-[var(--aicss-radius)] border border-border-c bg-surface py-2.5 pl-3.5 pr-9 text-sm text-text transition hover:border-[var(--aicss-border-strong)] focus:border-brand focus:outline-hidden focus:ring-2 focus:ring-[var(--aicss-accent-soft)]"
              @change="handleSearch"
            >
              <option value="">全部状态</option>
              <option value="pending">待销毁</option>
              <option value="expired">已过期</option>
              <option value="restored">已恢复</option>
            </select>
            <icon-down class="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          </div>
        </div>
      </div>

      <!-- 删除项列表 -->
      <section
        aria-label="已删除内容列表"
        class="mt-6 overflow-hidden rounded-[var(--aicss-radius-lg)] border border-border-c bg-surface shadow-[var(--aicss-shadow-card)]"
      >
        <!-- 加载骨架 -->
        <div v-if="loading" class="divide-y divide-border-c">
          <div v-for="i in 4" :key="`skeleton-${i}`" class="flex items-center gap-4 px-5 py-4">
            <div class="h-10 w-10 shrink-0 animate-pulse rounded-[var(--aicss-radius)] bg-surface-2"></div>
            <div class="flex-1 space-y-2">
              <div class="h-3.5 w-1/3 animate-pulse rounded bg-surface-2"></div>
              <div class="h-3 w-1/2 animate-pulse rounded bg-surface-2"></div>
            </div>
            <div class="h-8 w-20 animate-pulse rounded-[var(--aicss-radius)] bg-surface-2"></div>
          </div>
        </div>
        <!-- 空状态 -->
        <div
          v-else-if="items.length === 0"
          class="border-2 border-dashed border-border-c bg-surface px-6 py-14 text-center"
          aria-label="回收站空状态"
        >
          <div class="mx-auto flex h-14 w-14 items-center justify-center rounded-[var(--aicss-radius-lg)] bg-surface-2 text-brand">
            <icon-delete class="h-7 w-7" />
          </div>
          <h2 class="recycle-title mt-5 text-xl font-semibold">回收站空空如也</h2>
          <p class="mx-auto mt-2 max-w-md text-sm text-muted">删除的内容会在这里保留一段时间</p>
        </div>
        <!-- 列表 -->
        <ul v-else class="divide-y divide-border-c">
          <li
            v-for="record in items"
            :key="record.id"
            class="flex flex-col gap-3 px-4 py-4 transition-colors hover:bg-surface-2 sm:flex-row sm:items-center sm:gap-4 sm:px-5"
          >
            <!-- 类型图标块 -->
            <div class="mock-type-icon flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--aicss-radius)]">
              <component :is="getTypeIcon(record.resource_type)" class="h-5 w-5" />
            </div>

            <!-- 名称 + 元信息 -->
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-medium text-text">{{ record.resource_name }}</p>
              <div class="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1.5">
                <span class="mock-chip-type rounded-[var(--aicss-radius)] px-2.5 py-0.5 text-xs font-medium">{{ getTypeLabel(record.resource_type) }}</span>
                <span class="mock-chip-source rounded-[var(--aicss-radius)] px-2.5 py-0.5 text-xs">{{ getSourceLabel(record.deleted_by_type) }}</span>
                <time class="text-xs text-muted">删除于 {{ formatDate(record.deleted_at) }}</time>
                <!-- 跨设备文件：展示删除设备 -->
                <span
                  v-if="record.resource_type === 'os_file' && record.device_info"
                  class="inline-flex items-center gap-1 text-xs text-muted"
                >
                  <icon-computer class="h-3.5 w-3.5" />
                  {{ deviceLabel(record.device_info) }}
                </span>
              </div>
            </div>

            <!-- 状态 + 操作 -->
            <div class="flex shrink-0 flex-wrap items-center gap-2 sm:ml-auto">
              <span
                class="rounded-[var(--aicss-radius)] px-3 py-1 text-xs font-medium"
                :class="statusChipClass(record)"
              >
                {{ getStatusText(record) }}
              </span>
              <button
                v-if="record.status === 'pending' && !isExpired(record)"
                type="button"
                class="restore-mock inline-flex items-center gap-1.5 rounded-[var(--aicss-radius)] px-3.5 py-2 text-xs font-medium text-white transition hover:-translate-y-0.5 hover:brightness-110"
                :disabled="restoringId === record.id"
                @click="openRestoreModal(record)"
              >
                <icon-sync class="h-3.5 w-3.5" />
                恢复
              </button>
            </div>
          </li>
        </ul>
      </section>

      <!-- 分页 -->
      <footer class="mt-5 flex flex-wrap items-center justify-between gap-3 pb-2">
        <span class="text-xs text-muted">共 {{ totalRecord }} 条</span>
        <a-pagination
          v-if="totalRecord > pageSize"
          :current="currentPage"
          :page-size="pageSize"
          :total="totalRecord"
          size="small"
          show-total
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
          <p class="text-sm text-muted">{{ t('userRecycleBin.restoreConfirm') }}</p>
          <div v-if="restoreTarget" class="flex items-center gap-3 rounded-[var(--aicss-radius)] bg-surface-2 px-3 py-2.5">
            <div class="mock-type-icon flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--aicss-radius)]">
              <component :is="getTypeIcon(restoreTarget.resource_type)" class="h-4 w-4" />
            </div>
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-medium text-text">{{ restoreTarget.resource_name }}</p>
              <p class="text-xs text-muted">
                {{ getTypeLabel(restoreTarget.resource_type) }} · {{ getSourceLabel(restoreTarget.deleted_by_type) }}
              </p>
            </div>
          </div>
          <div
            v-if="restoreTarget?.resource_type === 'os_file'"
            class="flex items-center gap-2 rounded-[var(--aicss-radius)] bg-surface-2 px-3 py-2 text-sm"
          >
            <icon-computer class="shrink-0 text-muted" />
            <span class="text-text-2">{{ deviceLabel(restoreTarget.device_info) }}</span>
          </div>
        </div>
      </a-modal>

      <!-- 非本地删除恢复确认弹窗（跨设备恢复） -->
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
          <p class="text-sm text-muted">{{ t('userRecycleBin.deviceMismatchDesc') }}</p>
          <div class="rounded-[var(--aicss-radius)] bg-surface-2 px-3 py-2.5 text-sm">
            <div class="flex items-center gap-1">
              <icon-exclamation-circle-fill class="text-brand" />
              <span class="font-medium text-text">{{ t('userRecycleBin.deviceMismatchWarning') }}</span>
            </div>
            <div class="mt-1 text-text-2">
              <span>{{ t('userRecycleBin.deviceRecorded') }}: </span>
              <span class="font-medium text-text">{{ deviceLabel(recordedDevice) }}</span>
            </div>
            <div class="text-text-2">
              <span>{{ t('userRecycleBin.deviceCurrent') }}: </span>
              <span class="font-medium text-text">{{ deviceLabel(currentDevice) }}</span>
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

      <!-- 清理已销毁记录确认弹窗 -->
      <a-modal
        :visible="cleanModalVisible"
        :title="t('userRecycleBin.cleanExpiredBtn')"
        :confirm-loading="cleaning"
        :ok-text="t('userRecycleBin.cleanExpiredBtn')"
        :cancel-text="t('common.actions.cancel')"
        @ok="handleCleanExpired"
        @cancel="cleanModalVisible = false"
      >
        <p class="text-sm text-muted">{{ t('userRecycleBin.cleanExpiredConfirm') }}</p>
      </a-modal>
    </div>
  </div>
</template>

<style scoped>
.recycle-mock {
  background: var(--aicss-bg);
}

/* 标题：衬线体（对应原型 font-serif 大标题） */
.recycle-title {
  font-family: var(--aicss-font-serif, Georgia, 'Songti SC', serif);
  letter-spacing: -0.02em;
  color: var(--aicss-text);
}

/* 输入控件统一样式 */
.mock-input {
  color: var(--aicss-text);
  background: var(--aicss-surface);
}

/* 类型图标块：柔和粉底 */
.mock-type-icon {
  background: var(--aicss-surface-2);
  color: var(--aicss-brand-text, var(--aicss-accent-text));
}

/* 类型标签：粉调 */
.mock-chip-type {
  background: var(--aicss-surface-2);
  color: var(--aicss-text-2);
}

/* 来源标签：中性 */
.mock-chip-source {
  background: var(--aicss-bg-subtle);
  color: var(--aicss-muted);
}

/* 状态徽标 */
.status-chip-accent {
  background: var(--aicss-accent-soft);
  color: var(--aicss-brand-text, var(--aicss-accent-text));
}
.status-chip-soft {
  background: var(--aicss-surface-2);
  color: var(--aicss-text-2);
}
.status-chip-neutral {
  background: var(--aicss-bg-subtle);
  color: var(--aicss-muted);
}

/* 清空已销毁：次级粉胶囊按钮 */
.cleanup-mock {
  background: var(--aicss-surface-2);
  border: 1px solid var(--aicss-border);
  color: var(--aicss-accent-text);
}
.cleanup-mock:hover {
  background: var(--aicss-surface-3);
  border-color: var(--aicss-border-strong);
}

/* 恢复按钮：主粉胶囊 */
.restore-mock {
  background: var(--aicss-accent);
}
.restore-mock:hover {
  background: var(--aicss-accent-text);
}
</style>
