<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { apiPrefix } from '@/config'
import {
  activateStorageBackend,
  deleteStorageFiles,
  getStorageOverview,
  listStorageMigrationFiles,
  runStorageMigration,
  updateStorageConfig,
} from '@/services/admin-storage'
import type {
  StorageConfigItem,
  StorageMigrationFile,
} from '@/models/admin-storage'
import { getErrorMessage } from '@/utils/error'
import { useAdminStore } from '@/stores/admin'

const { t } = useI18n()
const adminStore = useAdminStore()

const BACKENDS = ['local', 'cos', 'oss']

// ==================== 概览 ====================
const loading = ref(false)
const activeBackend = ref('local')
const configs = ref<StorageConfigItem[]>([])
const stats = ref<Record<string, { count: number; size: number }>>({})

const canUpdate = computed(() => adminStore.hasPermission('storage:update'))

const getBackendLabel = (backend: string) => {
  const key = `admin.storage.backendTypes.${backend}`
  const label = t(key)
  return label === key ? backend : label
}

const formatSize = (size: number) => {
  if (!size) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = size
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i += 1
  }
  return `${value >= 100 || i === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[i]}`
}

const formatTime = (value: number | null | undefined) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const getConfigDisplay = (config: StorageConfigItem) => {
  const keys = Object.keys(config.configs || {})
  return keys.length ? keys.join(', ') : t('admin.storage.noConfig')
}

const loadOverview = async () => {
  loading.value = true
  try {
    const result = await getStorageOverview()
    activeBackend.value = result.data.active_backend || 'local'
    configs.value = result.data.backend_items || []
    stats.value = result.data.stats || {}
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.storage.loadFailed')))
  } finally {
    loading.value = false
  }
}

// ==================== 激活切换 ====================
const activateTarget = ref<string | null>(null)
const activating = ref(false)

const confirmActivate = (backend: string) => {
  activateTarget.value = backend
}

const handleActivate = async () => {
  const backend = activateTarget.value
  if (!backend) return
  activating.value = true
  try {
    await activateStorageBackend(backend)
    Message.success(t('admin.storage.activateSuccess'))
    activateTarget.value = null
    await Promise.all([loadOverview(), loadMigrationFiles()])
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.storage.activateFailed')))
  } finally {
    activating.value = false
  }
}

// ==================== 配置编辑 ====================
const configModalVisible = ref(false)
const configEditingBackend = ref('')
const configText = ref('')
const savingConfig = ref(false)

const openConfigModal = (backend: string) => {
  configEditingBackend.value = backend
  const target = configs.value.find((c) => c.backend === backend)
  configText.value = JSON.stringify(target?.configs || {}, null, 2)
  configModalVisible.value = true
}

const saveConfig = async () => {
  savingConfig.value = true
  try {
    let parsed: Record<string, unknown> = {}
    try {
      parsed = configText.value.trim() ? JSON.parse(configText.value) : {}
    } catch {
      Message.error('JSON 格式不正确')
      return
    }
    await updateStorageConfig(configEditingBackend.value, parsed)
    Message.success(t('admin.storage.configSaved'))
    configModalVisible.value = false
    await loadOverview()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.storage.configSaveFailed')))
  } finally {
    savingConfig.value = false
  }
}

// ==================== 迁移 ====================
const migrationLoading = ref(false)
const migrationRunning = ref(false)
const sourceBackend = ref('')
const targetBackend = ref('')
const migrationSearch = ref('')
const migrationExtension = ref('')
const migrationFiles = ref<StorageMigrationFile[]>([])
const migrationTotal = ref(0)
const migrationPage = ref(1)
const migrationPageSize = ref(20)
const extensionOptions = ref<string[]>([])
const selectedKeys = ref<string[]>([])
const deleteSource = ref(false)
const migrationConfirm = ref<null | { mode: 'selected' | 'all'; count: number }>(null)
const migrationSummary = ref<{ total: number; distinct_content: number; duplicate_records: number }>({
  total: 0,
  distinct_content: 0,
  duplicate_records: 0,
})
const deleteTarget = ref<StorageMigrationFile | null>(null)
const deletingFiles = ref(false)

// 文件查看 / 迁移筛选互斥：
// viewBackend 为查看模式（all/local/cos/oss，默认 all 查看全部存储）；
// 关键字搜索与文件类型筛选在查看/迁移两种模式下均生效；
// 选择源/目标存储后 viewBackend 清空为 ''，进入迁移筛选模式。
const viewBackend = ref<'all' | 'local' | 'cos' | 'oss' | ''>('all')

const backendOptions = computed(() =>
  BACKENDS.map((backend) => ({ label: getBackendLabel(backend), value: backend })),
)

const viewBackendOptions = computed(() => [
  { label: t('admin.storage.viewAll'), value: 'all' },
  ...backendOptions.value,
])

// 迁移筛选模式：viewBackend 被清空（源/目标存储条件触发）即进入迁移模式
const inMigrationMode = computed(() => viewBackend.value === '')

// 是否处于"有筛选条件"状态（决定空态文案：无筛选时提示无文件，有筛选时提示无匹配）
const hasActiveFilter = computed(() => {
  const backendActive = inMigrationMode.value
    ? Boolean(sourceBackend.value)
    : viewBackend.value !== 'all'
  return (
    backendActive ||
    Boolean(migrationSearch.value.trim()) ||
    Boolean(migrationExtension.value)
  )
})

const canMigrate = computed(() =>
  inMigrationMode.value && Boolean(sourceBackend.value) && Boolean(targetBackend.value),
)

const activeSourceOptions = computed(() =>
  backendOptions.value.filter((opt) => opt.value !== targetBackend.value),
)

const activeTargetOptions = computed(() =>
  backendOptions.value.filter((opt) => opt.value !== sourceBackend.value),
)

const selectedFilesCount = computed(() => selectedKeys.value.length)

const formatFileSize = (size: number) => formatSize(size)

const loadMigrationFiles = async () => {
  migrationLoading.value = true
  const migrationMode = inMigrationMode.value
  try {
    const result = await listStorageMigrationFiles({
      source_backend: migrationMode ? (sourceBackend.value || 'all') : viewBackend.value,
      page: migrationPage.value,
      page_size: migrationPageSize.value,
      extension: migrationExtension.value || undefined,
      search_word: migrationSearch.value.trim() || undefined,
    })
    migrationFiles.value = result.data.items || []
    migrationTotal.value = result.data.total_record ?? result.data.total ?? 0
    migrationSummary.value = result.data.summary || migrationSummary.value
    extensionOptions.value = result.data.extensions || []
    selectedKeys.value = selectedKeys.value.filter((id) =>
      (result.data.items || []).some((item) => item.id === id),
    )
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.storage.loadFailed')))
  } finally {
    migrationLoading.value = false
  }
}

const loadFilteredFiles = () => {
  migrationPage.value = 1
  selectedKeys.value = []
  void loadMigrationFiles()
}

// 查看模式：选择存储类型（含"全部存储"）仅按存储类型查看；
// 退出迁移模式时清空源/目标存储条件，保留关键字/文件类型等查看筛选
const selectViewBackend = (backend: 'all' | 'local' | 'cos' | 'oss') => {
  sourceBackend.value = ''
  targetBackend.value = ''
  viewBackend.value = backend
  loadFilteredFiles()
}

const handleViewBackendChange = (
  value: string | number | boolean | Record<string, any> | (string | number | boolean | Record<string, any>)[],
) => {
  if (typeof value === 'string' && (value === 'all' || BACKENDS.includes(value))) {
    selectViewBackend(value as 'all' | 'local' | 'cos' | 'oss')
  }
}

// 迁移模式由"源存储/目标存储"条件触发（清空查看筛选进入迁移筛选模式）；
// 关键字/文件类型筛选在两种模式下均生效，不会触发模式切换；
// 迁移模式中源/目标条件清空后回到默认的"查看全部"模式
const onMigrationFilterChange = () => {
  const hasMigration = Boolean(sourceBackend.value || targetBackend.value)
  if (hasMigration) {
    viewBackend.value = ''
  } else if (viewBackend.value === '') {
    viewBackend.value = 'all'
  }
  loadFilteredFiles()
}

const handleSourceChange = () => {
  onMigrationFilterChange()
}

const handleTargetChange = () => {
  onMigrationFilterChange()
}

const handleMigrationSearch = () => {
  onMigrationFilterChange()
}

const handleMigrationPageChange = (page: number) => {
  migrationPage.value = page
  void loadMigrationFiles()
}

const handleMigrationPageSizeChange = (size: number) => {
  migrationPageSize.value = size
  migrationPage.value = 1
  void loadMigrationFiles()
}

const confirmMigrateSelected = () => {
  if (!canMigrate.value) {
    Message.warning(t('admin.storage.migrateSourceTargetRequired'))
    return
  }
  if (!selectedKeys.value.length) {
    Message.warning(t('admin.storage.migrateNoSelection'))
    return
  }
  if (sourceBackend.value === targetBackend.value) {
    Message.warning(t('admin.storage.migrateSameBackend'))
    return
  }
  migrationConfirm.value = { mode: 'selected', count: selectedKeys.value.length }
}

const confirmMigrateAll = () => {
  if (!canMigrate.value) {
    Message.warning(t('admin.storage.migrateSourceTargetRequired'))
    return
  }
  if (sourceBackend.value === targetBackend.value) {
    Message.warning(t('admin.storage.migrateSameBackend'))
    return
  }
  if (!migrationTotal.value) {
    Message.warning(t('admin.storage.migrateNoSelection'))
    return
  }
  migrationConfirm.value = { mode: 'all', count: migrationTotal.value }
}

const handleMigrate = async () => {
  const confirm = migrationConfirm.value
  if (!confirm) return
  migrationRunning.value = true
  try {
    const result = await runStorageMigration({
      source_backend: sourceBackend.value,
      target_backend: targetBackend.value,
      file_ids: confirm.mode === 'selected' ? selectedKeys.value : undefined,
      extension: migrationExtension.value || undefined,
      search_word: migrationSearch.value.trim() || undefined,
      delete_source: deleteSource.value,
    })
    const data = result.data
    Message.success(t('admin.storage.migrateRunSuccess', { succeeded: data.succeeded, failed: data.failed }))
    if (data.failed > 0 && data.failures?.length) {
      const first = data.failures[0]
      Message.error(`${first.name}: ${first.reason}`)
    }
    migrationConfirm.value = null
    selectedKeys.value = []
    await Promise.all([loadOverview(), loadMigrationFiles()])
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.storage.migrateRunFailed')))
  } finally {
    migrationRunning.value = false
  }
}

const resolveFileUrl = (url: string | null) => {
  if (!url) return ''
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  const origin = apiPrefix.replace(/\/api\/?$/, '')
  return `${origin}${url.startsWith('/') ? url : `/${url}`}`
}

// ==================== 文件预览（kkFileView） ====================
const previewTarget = ref<StorageMigrationFile | null>(null)
const previewIframeKey = ref(0)
const previewLoaded = ref(false)

const openPreview = (file: StorageMigrationFile) => {
  previewTarget.value = file
  previewIframeKey.value = Date.now()
  previewLoaded.value = false
}

const closePreview = () => {
  previewTarget.value = null
  previewIframeKey.value = 0
}

const downloadFile = (file: StorageMigrationFile) => {
  const url = resolveFileUrl(file.url)
  if (!url) return
  window.open(url, '_blank', 'noopener')
}

const confirmDeleteFile = (file: StorageMigrationFile) => {
  deleteTarget.value = file
}

const handleDeleteFile = async () => {
  const file = deleteTarget.value
  if (!file) return
  deletingFiles.value = true
  try {
    const result = await deleteStorageFiles({ file_ids: [file.id] })
    const data = result.data
    if (data.succeeded > 0) {
      Message.success(t('admin.storage.deleteSuccess'))
    }
    if (data.failures?.length) {
      Message.error(`${data.failures[0].name}: ${data.failures[0].reason}`)
    }
    if (data.in_use?.length) {
      Message.warning(t('admin.storage.deleteInUse'))
    }
    deleteTarget.value = null
    await Promise.all([loadOverview(), loadMigrationFiles()])
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.storage.deleteFailed')))
  } finally {
    deletingFiles.value = false
  }
}

onMounted(() => {
  // 默认进入"查看全部存储文件"模式：迁移筛选置空
  void getStorageOverview().then((result) => {
    activeBackend.value = result.data.active_backend || 'local'
    configs.value = result.data.backend_items || []
    stats.value = result.data.stats || {}
    viewBackend.value = 'all'
    sourceBackend.value = ''
    targetBackend.value = ''
    void loadMigrationFiles()
  }).catch((error) => {
    Message.error(getErrorMessage(error, t('admin.storage.loadFailed')))
  })
})
</script>

<template>
  <section class="space-y-6">
    <header>
      <h1 class="text-2xl font-semibold text-slate-900">{{ t('admin.storage.title') }}</h1>
      <p class="mt-1 text-sm text-slate-500">{{ t('admin.storage.description') }}</p>
    </header>

    <!-- 当前激活存储提示 -->
    <a-alert type="info" show-icon>
      <template #title>
        {{ t('admin.storage.activeBackend') }}：
        <strong>{{ getBackendLabel(activeBackend) }}</strong>
        <span class="ml-2 text-sm font-normal text-slate-500">{{ t('admin.storage.activeBackendDesc') }}</span>
      </template>
    </a-alert>

    <!-- 存储后端配置列表 -->
    <a-spin :loading="loading" class="block">
      <section class="grid gap-4 lg:grid-cols-3">
        <article
          v-for="backend in BACKENDS"
          :key="backend"
          class="rounded-xl border bg-white p-5"
          :class="backend === activeBackend ? 'border-blue-300 ring-1 ring-blue-200' : 'border-slate-200'"
        >
          <div class="flex items-start justify-between gap-2">
            <div>
              <h3 class="font-semibold text-slate-900">{{ getBackendLabel(backend) }}</h3>
              <p class="mt-1 text-xs text-slate-400">{{ backend }}</p>
            </div>
            <a-tag :color="backend === activeBackend ? 'blue' : 'gray'" size="small">
              {{ backend === activeBackend ? t('admin.storage.active') : t('admin.storage.inactive') }}
            </a-tag>
          </div>

          <dl class="mt-4 space-y-2 text-sm">
            <div class="flex justify-between">
              <dt class="text-slate-500">{{ t('admin.storage.configColumns.configs') }}</dt>
              <dd class="max-w-[180px] truncate text-slate-700">
                {{ getConfigDisplay({ backend, configs: (configs.find((c) => c.backend === backend)?.configs || {}) } as StorageConfigItem) }}
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-500">{{ t('admin.storage.configColumns.files') }}</dt>
              <dd class="text-slate-700">{{ stats[backend]?.count ?? 0 }}</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-500">{{ t('admin.storage.configColumns.size') }}</dt>
              <dd class="text-slate-700">{{ formatSize(stats[backend]?.size ?? 0) }}</dd>
            </div>
          </dl>

          <div class="mt-5 flex gap-2">
            <a-button
              v-if="canUpdate && backend !== activeBackend"
              type="primary"
              size="small"
              class="flex-1"
              @click="confirmActivate(backend)"
            >
              {{ t('admin.storage.activateBtn') }}
            </a-button>
            <a-button
              v-if="canUpdate"
              size="small"
              class="flex-1"
              @click="openConfigModal(backend)"
            >
              {{ t('admin.storage.configTitle', { backend: getBackendLabel(backend) }) }}
            </a-button>
          </div>
        </article>
      </section>
    </a-spin>

    <!-- 文件迁移 -->
    <section class="rounded-xl border border-slate-200 bg-white p-5">
      <header class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-lg font-semibold text-slate-900">{{ t('admin.storage.migrateTitle') }}</h2>
          <p class="mt-1 text-sm text-slate-500">{{ t('admin.storage.migrateDescription') }}</p>
        </div>
        <a-alert v-if="migrationRunning" type="warning" :title="t('admin.storage.migrationActive')" class="max-w-xs" />
      </header>

      <!-- 文件查看 / 迁移筛选互斥：默认查看全部存储，可切换存储类型查看 -->
      <div class="mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2.5">
        <span class="shrink-0 text-sm font-medium text-slate-600">{{ t('admin.storage.viewLabel') }}</span>
        <a-select
          :model-value="viewBackend"
          :options="viewBackendOptions"
          :placeholder="t('admin.storage.viewPlaceholder')"
          class="w-44"
          size="small"
          @change="handleViewBackendChange"
        />
        <span class="text-xs text-slate-400">{{ t('admin.storage.viewHint') }}</span>
      </div>

      <!-- 迁移条件 -->
      <div class="mt-4 grid gap-3 md:grid-cols-4">
        <a-form-item :label="t('admin.storage.migrateSource')" class="mb-0">
          <a-select
            v-model="sourceBackend"
            :options="activeSourceOptions"
            :placeholder="t('admin.storage.migrateSourcePlaceholder')"
            @change="handleSourceChange"
          />
        </a-form-item>
        <a-form-item :label="t('admin.storage.migrateTarget')" class="mb-0">
          <a-select
            v-model="targetBackend"
            :options="activeTargetOptions"
            :placeholder="t('admin.storage.migrateTargetPlaceholder')"
            @change="handleTargetChange"
          />
        </a-form-item>
        <a-form-item label="" class="mb-0">
          <a-select
            v-model="migrationExtension"
            :options="extensionOptions.map((ext) => ({ label: ext || 'N/A', value: ext }))"
            :placeholder="t('admin.storage.migrateExtensionAll')"
            allow-clear
            @change="handleMigrationSearch"
          />
        </a-form-item>
        <a-form-item label="" class="mb-0">
          <a-input
            v-model="migrationSearch"
            :placeholder="t('admin.storage.migratePlaceholder')"
            allow-clear
            @press-enter="handleMigrationSearch"
            @clear="handleMigrationSearch"
          />
        </a-form-item>
      </div>

      <!-- 文件去重统计 -->
      <div v-if="migrationSummary.total" class="mt-4 flex flex-wrap gap-3">
        <a-tag color="blue">{{ t('admin.storage.totalFiles', { count: migrationSummary.total }) }}</a-tag>
        <a-tag color="green">{{ t('admin.storage.distinctFiles', { count: migrationSummary.distinct_content }) }}</a-tag>
        <a-tag color="orange">{{ t('admin.storage.duplicateFiles', { count: migrationSummary.duplicate_records }) }}</a-tag>
      </div>

      <!-- 迁移文件列表 -->
      <div class="mt-4 overflow-hidden rounded-lg border border-slate-200">
        <a-table
          :data="migrationFiles"
          :loading="migrationLoading"
          :pagination="false"
          row-key="id"
          :row-selection="canUpdate ? { type: 'checkbox', selectedRowKeys: selectedKeys, showCheckedAll: true } : undefined"
          :scroll="{ x: 900 }"
          @selection-change="(keys: Array<string | number>) => (selectedKeys = keys.map(String))"
        >
          <template #columns>
            <a-table-column :title="t('admin.storage.migrateColName')" data-index="name" :width="260">
              <template #cell="{ record }">
                <div class="max-w-[260px] truncate font-medium text-gray-800">{{ record.name }}</div>
              </template>
            </a-table-column>
            <a-table-column :title="t('admin.storage.migrateColSource')" data-index="source_label" :width="220">
              <template #cell="{ record }">
                <a-tooltip :content="record.source_label">
                  <span class="block max-w-[210px] truncate text-xs text-gray-500">{{ record.source_label }}</span>
                </a-tooltip>
              </template>
            </a-table-column>
            <a-table-column :title="t('admin.storage.migrateColSize')" data-index="size" :width="110">
              <template #cell="{ record }">
                <span class="text-xs text-gray-500">{{ formatFileSize(record.size) }}</span>
              </template>
            </a-table-column>
            <a-table-column :title="t('admin.storage.migrateColType')" data-index="extension" :width="100">
              <template #cell="{ record }">
                <a-tag size="small" color="cyan">{{ record.extension || '-' }}</a-tag>
              </template>
            </a-table-column>
            <a-table-column :title="t('admin.storage.migrateColBackend')" data-index="storage_backend" :width="120">
              <template #cell="{ record }">
                <a-tag size="small" color="orange">
                  {{ getBackendLabel(record.resolved_backend || record.storage_backend || 'local') }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column :title="t('admin.storage.migrateColTime')" data-index="created_at" :width="170">
              <template #cell="{ record }">
                <span class="text-xs text-gray-500">{{ formatTime(record.created_at) }}</span>
              </template>
            </a-table-column>
            <a-table-column :title="t('admin.storage.migrateColStatus')" data-index="is_valid" :width="150">
              <template #cell="{ record }">
                <a-tag v-if="record.in_use" size="small" color="purple">{{ t('admin.storage.statusInUse') }}</a-tag>
                <a-tag v-if="record.is_latest" size="small" color="green">{{ t('admin.storage.statusLatest') }}</a-tag>
                <a-tag v-if="!record.is_valid" size="small" color="red">{{ t('admin.storage.statusMissing') }}</a-tag>
                <a-tag v-if="record.duplicate_count > 1" size="small" color="orange">
                  {{ t('admin.storage.duplicateGroup', { count: record.duplicate_count }) }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column :title="t('admin.storage.migrateColActions')" :width="120" fixed="right">
              <template #cell="{ record }">
                <a-button v-if="record.kkfileview_url" size="mini" type="text" @click="openPreview(record)">
                  {{ t('admin.storage.preview') }}
                </a-button>
                <a-button v-if="record.url" size="mini" type="text" @click="downloadFile(record)">
                  {{ t('admin.storage.download') }}
                </a-button>
                <a-button
                  v-if="canUpdate"
                  size="mini"
                  type="text"
                  status="danger"
                  @click="confirmDeleteFile(record)"
                >
                  {{ t('common.actions.delete') }}
                </a-button>
                <span v-if="!record.url && !record.kkfileview_url" class="text-xs text-gray-300">-</span>
              </template>
            </a-table-column>
          </template>
          <template #empty>
            <div class="py-12 text-center">
              <p class="text-lg font-medium text-slate-900">
                {{ hasActiveFilter ? t('admin.storage.migrateEmptyFiltered') : t('admin.storage.migrateEmpty') }}
              </p>
            </div>
          </template>
        </a-table>
      </div>

      <footer class="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center gap-4">
          <span class="text-xs text-slate-400">{{ t('admin.storage.totalFiles', { count: migrationTotal }) }}</span>
          <a-checkbox v-if="canUpdate" v-model="deleteSource" class="text-xs text-slate-500">
            {{ t('admin.storage.migrateDeleteSource') }}
            <a-tooltip :content="t('admin.storage.migrateDeleteSourceTip')" position="top">
              <icon-question-circle class="text-slate-300" />
            </a-tooltip>
          </a-checkbox>
        </div>
        <div class="flex items-center gap-2">
          <a-button
            v-if="canUpdate"
            type="primary"
            :disabled="!selectedFilesCount"
            :loading="migrationRunning"
            @click="confirmMigrateSelected"
          >
            {{ t('admin.storage.migrateSelected', { count: selectedFilesCount }) }}
          </a-button>
          <a-button
            v-if="canUpdate"
            status="warning"
            :disabled="!migrationTotal"
            :loading="migrationRunning"
            @click="confirmMigrateAll"
          >
            {{ t('admin.storage.migrateAll') }}
          </a-button>
          <a-pagination
            v-if="migrationTotal > 0"
            :current="migrationPage"
            :page-size="migrationPageSize"
            :total="migrationTotal"
            size="small"
            show-total
            show-page-size
            :page-size-options="[10, 20, 50, 100]"
            @change="handleMigrationPageChange"
            @page-size-change="handleMigrationPageSizeChange"
          />
        </div>
      </footer>
    </section>

    <!-- 激活确认弹窗 -->
    <a-modal
      :visible="activateTarget !== null"
      :title="t('admin.storage.activateBtn')"
      :confirm-loading="activating"
      :ok-text="t('admin.storage.activateBtn')"
      :cancel-text="t('common.actions.cancel')"
      @ok="handleActivate"
      @cancel="activateTarget = null"
    >
      <p class="text-sm text-slate-500">
        {{ t('admin.storage.activateConfirm', { backend: activateTarget ? getBackendLabel(activateTarget) : '' }) }}
      </p>
    </a-modal>

    <!-- 配置编辑弹窗 -->
    <a-modal
      v-model:visible="configModalVisible"
      :title="t('admin.storage.configTitle', { backend: getBackendLabel(configEditingBackend) })"
      :ok-loading="savingConfig"
      :ok-text="t('admin.storage.configSaved')"
      :cancel-text="t('common.actions.cancel')"
      @ok="saveConfig"
    >
      <a-textarea v-model="configText" :auto-size="{ minRows: 8, maxRows: 16 }" class="font-mono text-xs" />
      <p class="mt-2 text-xs text-slate-400">{{ t('admin.storage.configPlaceholder') }}</p>
    </a-modal>

    <!-- 迁移确认弹窗 -->
    <a-modal
      :visible="migrationConfirm !== null"
      :title="t('admin.storage.migrateTitle')"
      :confirm-loading="migrationRunning"
      :ok-text="t('common.actions.confirm')"
      :cancel-text="t('common.actions.cancel')"
      @ok="handleMigrate"
      @cancel="migrationConfirm = null"
    >
      <p v-if="migrationConfirm" class="text-sm text-slate-500">
        {{
          migrationConfirm.mode === 'selected'
            ? t('admin.storage.migrateConfirmSelected', {
                count: migrationConfirm.count,
                source: getBackendLabel(sourceBackend),
                target: getBackendLabel(targetBackend),
              })
            : t('admin.storage.migrateConfirmAll', {
                count: migrationConfirm.count,
                source: getBackendLabel(sourceBackend),
                target: getBackendLabel(targetBackend),
              })
        }}
      </p>
    </a-modal>

    <!-- 文件预览弹窗（kkFileView 多格式在线预览） -->
    <a-modal
      :visible="previewTarget !== null"
      :title="previewTarget ? previewTarget.name : ''"
      width="80%"
      :footer="false"
      :closable="true"
      @cancel="closePreview"
    >
      <template v-if="previewTarget">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
          <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span class="rounded bg-gray-100 px-2 py-0.5 font-medium text-slate-700">
              {{ previewTarget.extension || '-' }}
            </span>
            <span>{{ formatFileSize(previewTarget.size) }}</span>
            <span>{{ getBackendLabel(previewTarget.resolved_backend || previewTarget.storage_backend || sourceBackend || 'local') }}</span>
            <span>{{ formatTime(previewTarget.created_at) }}</span>
          </div>
          <a-button size="small" @click="downloadFile(previewTarget)">
            <template #icon><icon-file /></template>
            {{ t('admin.storage.download') }}
          </a-button>
        </div>

        <div
          v-if="previewTarget.kkfileview_url"
          class="relative h-[70vh] overflow-hidden rounded-lg border border-slate-200 bg-slate-50"
        >
          <a-spin v-if="!previewLoaded" class="absolute inset-0 z-10 flex items-center justify-center" />
          <iframe
            :key="previewIframeKey"
            :src="previewTarget.kkfileview_url"
            class="h-full w-full"
            frameborder="0"
            @load="previewLoaded = true"
          />
        </div>
        <a-empty v-else :description="t('admin.storage.previewUnavailable')" class="py-16" />
      </template>
    </a-modal>

    <!-- 删除文件确认弹窗 -->
    <a-modal
      :visible="deleteTarget !== null"
      :title="t('admin.storage.deleteTitle')"
      :confirm-loading="deletingFiles"
      :ok-text="t('common.actions.delete')"
      :cancel-text="t('common.actions.cancel')"
      @ok="handleDeleteFile"
      @cancel="deleteTarget = null"
    >
      <p class="text-sm text-slate-500">
        {{ t('admin.storage.deleteConfirm', { name: deleteTarget?.name || '' }) }}
      </p>
      <p v-if="deleteTarget?.in_use" class="mt-2 text-xs text-red-500">
        {{ t('admin.storage.deleteInUseWarning') }}
      </p>
    </a-modal>
  </section>
</template>
