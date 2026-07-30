<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  type AdminAppRecord,
  batchDeleteAdminApps,
  batchOfflineAdminApps,
  createAdminApp,
  deleteAdminApp,
  listAdminApps,
  updateAdminAppBasicInfo,
  updateAdminAppMetadata,
} from '@/services/admin-apps'
import type { AgentMetadata } from '@/models/app'
import AgentMetadataEditor from '@/components/admin/AgentMetadataEditor.vue'
import { useAdminStore } from '@/stores/admin'
import { getErrorMessage } from '@/utils/error'

const router = useRouter()
const adminStore = useAdminStore()
const { t } = useI18n()

const loading = ref(false)
const saving = ref(false)
const creating = ref(false)
const batchLoading = ref(false)
const apps = ref<AdminAppRecord[]>([])
const total = ref(0)
const filters = ref({
  current_page: 1,
  page_size: 20,
  search: '',
  status: '',
})
const keyword = ref('')
const selectedIds = ref<Set<string>>(new Set())
const allSelected = computed(
  () => apps.value.length > 0 && apps.value.every((a) => selectedIds.value.has(a.id)),
)
const selectedCount = computed(() => selectedIds.value.size)

// AgentMetadata 默认值（与后端 api/internal/entity/agent_entity.py 的 DEFAULT_AGENT_METADATA 对齐）
// 用于在打开编辑弹窗时补齐字段，避免 PATCH 时把未编辑字段覆盖为默认值。
const DEFAULT_AGENT_METADATA: AgentMetadata = {
  primary_pool: 'general',
  secondary_pools: [],
  capabilities: [],
  task_types: [],
  input_modalities: ['text'],
  output_modalities: ['text'],
  risk_level: 'safe',
  model_tier: 'standard',
  model_id: '',
  key_policy: 'default',
  cost_level: 'medium',
  routing_priority: 50,
  allowed_tool_categories: [],
  quality_score: 0.5,
  success_rate: 0.0,
  latency_p95: 0,
  max_context_tokens: 0,
  enabled: true,
}

const modalVisible = ref(false)
const createModalVisible = ref(false)
const editingApp = ref<AdminAppRecord | null>(null)
const form = ref({ name: '', description: '', icon: '' })
const createForm = ref({ name: '', description: '', icon: '' })

// 池治理字段编辑弹窗
const metadataModalVisible = ref(false)
const metadataSaving = ref(false)
const editingMetadataApp = ref<AdminAppRecord | null>(null)
const metadataForm = ref<AgentMetadata>({ ...DEFAULT_AGENT_METADATA })

const canUpdate = computed(() => adminStore.hasPermission('app:update'))
const canCreate = computed(() => adminStore.hasPermission('app:create'))
const canDelete = computed(() => adminStore.hasPermission('app:delete'))
const hasActiveFilters = computed(() => Boolean(filters.value.search))
const emptyDescription = computed(() => {
  return hasActiveFilters.value
    ? t('admin.apps.emptyFiltered')
    : t('admin.apps.empty')
})

/**
 * 拉取后台应用分页列表。
 */
const loadApps = async () => {
  loading.value = true
  try {
    const result = await listAdminApps({
      current_page: filters.value.current_page,
      page_size: filters.value.page_size,
      search: filters.value.search.trim(),
      status: filters.value.status,
    })
    apps.value = result.list || []
    total.value = result.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.apps.loadFailed')))
  } finally {
    loading.value = false
  }
}

/**
 * 关键字搜索：回到第一页并刷新。
 */
const handleSearch = async (value: string) => {
  keyword.value = value
  filters.value.search = value
  filters.value.current_page = 1
  await loadApps()
}

/**
 * 状态筛选变化后刷新列表，并回到第一页。
 */
const handleStatusChange = async (value: string) => {
  filters.value.status = value
  filters.value.current_page = 1
  await loadApps()
}

const onPageChange = (page: number) => {
  filters.value.current_page = page
  selectedIds.value = new Set()
  void loadApps()
}

const onPageSizeChange = (size: number) => {
  filters.value.page_size = size
  filters.value.current_page = 1
  selectedIds.value = new Set()
  void loadApps()
}

/**
 * 跳转到应用编辑页查看详情。
 */
const handleViewDetail = async (app: AdminAppRecord) => {
  await router.push({ name: 'admin-app-edit', params: { app_id: app.id } })
}

/**
 * 打开编辑基本信息弹窗。
 */
const openEditBasic = (app: AdminAppRecord) => {
  editingApp.value = app
  form.value = {
    name: app.name || '',
    description: app.description || '',
    icon: app.icon || '',
  }
  modalVisible.value = true
}

/**
 * 提交基本信息编辑。
 */
const submitEditBasic = async () => {
  if (!editingApp.value) return
  saving.value = true
  try {
    await updateAdminAppBasicInfo(editingApp.value.id, { ...form.value })
    Message.success(t('admin.apps.saveSuccess'))
    modalVisible.value = false
    await loadApps()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.apps.saveFailed')))
  } finally {
    saving.value = false
  }
}

/**
 * 打开池治理字段编辑弹窗。
 * 用默认值补齐 agent_metadata 缺失字段，确保提交时传完整对象，避免 PATCH 覆盖其他字段为默认值。
 */
const openEditMetadata = (app: AdminAppRecord) => {
  editingMetadataApp.value = app
  metadataForm.value = { ...DEFAULT_AGENT_METADATA, ...(app.agent_metadata || {}) }
  metadataModalVisible.value = true
}

/**
 * 提交池治理字段编辑。
 */
const submitEditMetadata = async () => {
  if (!editingMetadataApp.value) return
  metadataSaving.value = true
  try {
    await updateAdminAppMetadata(editingMetadataApp.value.id, metadataForm.value)
    Message.success(t('admin.apps.metadataSaveSuccess'))
    metadataModalVisible.value = false
    await loadApps()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.apps.metadataSaveFailed')))
  } finally {
    metadataSaving.value = false
  }
}

/**
 * 打开创建应用弹窗。
 */
const openCreateModal = () => {
  createForm.value = { name: '', description: '', icon: '' }
  createModalVisible.value = true
}

/**
 * 提交创建应用，成功后跳转到编辑器。
 */
const submitCreate = async () => {
  if (!createForm.value.name?.trim()) {
    Message.warning(t('admin.apps.nameRequired'))
    return
  }
  creating.value = true
  try {
    const app = await createAdminApp({
      name: createForm.value.name,
      description: createForm.value.description,
      icon: createForm.value.icon || 'https://placehold.co/100x100/png?text=APP',
    })
    Message.success(t('admin.apps.createSuccess'))
    createModalVisible.value = false
    await router.push({ name: 'admin-app-edit', params: { app_id: app.id } })
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.apps.createFailed')))
  } finally {
    creating.value = false
  }
}

/**
 * 删除后台应用。
 */
const handleDelete = (app: AdminAppRecord) => {
  Modal.warning({
    title: t('admin.apps.deleteTitle'),
    content: t('admin.apps.deleteContent', { name: app.name }),
    hideCancel: false,
    onOk: async () => {
      try {
        await deleteAdminApp(app.id)
        Message.success(t('admin.apps.deleteSuccess'))
      } catch (error) {
        Message.error(getErrorMessage(error, t('admin.apps.deleteFailed')))
      } finally {
        void loadApps()
      }
    },
  })
}

/**
 * 切换单个应用选择状态。
 */
const toggleSelect = (appId: string) => {
  const next = new Set(selectedIds.value)
  if (next.has(appId)) {
    next.delete(appId)
  } else {
    next.add(appId)
  }
  selectedIds.value = next
}

/**
 * 全选/取消全选当前页应用。
 */
const toggleSelectAll = () => {
  if (allSelected.value) {
    selectedIds.value = new Set()
  } else {
    selectedIds.value = new Set(apps.value.map((a) => a.id))
  }
}

const clearSelection = () => {
  selectedIds.value = new Set()
}

/**
 * 批量下架选中的应用。
 */
const handleBatchOffline = () => {
  if (selectedCount.value === 0) {
    Message.info(t('admin.apps.batch.noSelection'))
    return
  }
  Modal.warning({
    title: t('admin.apps.batch.offlineTitle'),
    content: t('admin.apps.batch.offlineContent', { count: selectedCount.value }),
    hideCancel: false,
    onOk: async () => {
      batchLoading.value = true
      try {
        const result = await batchOfflineAdminApps(Array.from(selectedIds.value))
        const okCount = result.succeeded.length
        const failCount = result.failed.length
        if (failCount === 0) {
          Message.success(t('admin.apps.batch.offlineSuccess', { count: okCount }))
        } else {
          Message.warning(
            t('admin.apps.batch.partialSuccess', { ok: okCount, fail: failCount }),
          )
        }
        clearSelection()
        await loadApps()
      } catch (error) {
        Message.error(getErrorMessage(error, t('admin.apps.batch.offlineFailed')))
      } finally {
        batchLoading.value = false
      }
    },
  })
}

/**
 * 批量删除选中的应用。
 */
const handleBatchDelete = () => {
  if (selectedCount.value === 0) {
    Message.info(t('admin.apps.batch.noSelection'))
    return
  }
  Modal.warning({
    title: t('admin.apps.batch.deleteTitle'),
    content: t('admin.apps.batch.deleteContent', { count: selectedCount.value }),
    hideCancel: false,
    onOk: async () => {
      batchLoading.value = true
      try {
        const result = await batchDeleteAdminApps(Array.from(selectedIds.value))
        const okCount = result.succeeded.length
        const failCount = result.failed.length
        if (failCount === 0) {
          Message.success(t('admin.apps.batch.deleteSuccess', { count: okCount }))
        } else {
          Message.warning(
            t('admin.apps.batch.partialSuccess', { ok: okCount, fail: failCount }),
          )
        }
        clearSelection()
        await loadApps()
      } catch (error) {
        Message.error(getErrorMessage(error, t('admin.apps.batch.deleteFailed')))
      } finally {
        batchLoading.value = false
      }
    },
  })
}

const formatTimestamp = (timestamp?: number) => {
  return timestamp ? new Date(timestamp * 1000).toLocaleString() : '-'
}

const statusLabel = (status?: string) => {
  if (!status) return '-'
  const key = `admin.apps.statusLabels.${status}`
  const label = t(key)
  return label === key ? status : label
}

const statusColor = (status?: string) => {
  return (
    ({ draft: 'gray', published: 'green', offline: 'red' } as Record<string, string>)[
      status || ''
    ] || 'gray'
  )
}

const riskColor = (risk?: string) =>
  ({ safe: 'green', low: 'green', medium: 'orange', high: 'red' } as Record<string, string>)[
    risk || ''
  ] || 'gray'

const isImageUrl = (icon?: string) => {
  return Boolean(icon && (icon.startsWith('http') || icon.startsWith('/')))
}

onMounted(() => {
  void loadApps()
})
</script>

<template>
  <section class="space-y-6 p-6">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold text-gray-900">{{ t('admin.apps.title') }}</h1>
        <p class="mt-1 text-sm text-gray-500">{{ t('admin.apps.description') }}</p>
      </div>
      <a-button v-if="canCreate" type="primary" @click="openCreateModal">
        <template #icon>
          <icon-plus />
        </template>
        {{ t('admin.apps.createButton') }}
      </a-button>
    </header>

    <!-- 搜索栏 -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <a-input-search
          v-model="keyword"
          :placeholder="t('admin.apps.searchPlaceholder')"
          allow-clear
          style="max-width: 360px"
          @search="handleSearch"
        />
        <a-select
          :model-value="filters.status"
          style="width: 160px"
          @update:model-value="handleStatusChange"
        >
          <a-option value="">{{ t('admin.apps.filters.allStatuses') }}</a-option>
          <a-option value="draft">{{ t('admin.apps.filters.draft') }}</a-option>
          <a-option value="published">{{ t('admin.apps.filters.published') }}</a-option>
          <a-option value="offline">{{ t('admin.apps.filters.offline') }}</a-option>
        </a-select>
      </div>
      <span class="text-xs text-gray-400">{{ t('admin.apps.total', { count: total }) }}</span>
    </div>

    <!-- 批量操作工具条 -->
    <div
      v-if="apps.length"
      class="flex flex-wrap items-center gap-3 rounded-xl border border-gray-200 bg-white p-3"
    >
      <a-checkbox :model-value="allSelected" @change="toggleSelectAll">
        {{ t('admin.apps.batch.selectAll') }}
      </a-checkbox>
      <span class="text-xs text-gray-400">
        {{ t('admin.apps.batch.selected', { count: selectedCount }) }}
      </span>
      <div class="ml-auto flex flex-wrap gap-2">
        <a-button
          size="small"
          status="warning"
          :loading="batchLoading"
          :disabled="selectedCount === 0"
          @click="handleBatchOffline"
        >
          {{ t('admin.apps.batch.offline') }}
        </a-button>
        <a-button
          v-if="canDelete"
          size="small"
          status="danger"
          :loading="batchLoading"
          :disabled="selectedCount === 0"
          @click="handleBatchDelete"
        >
          {{ t('admin.apps.batch.delete') }}
        </a-button>
        <a-button
          v-if="selectedCount > 0"
          size="small"
          :disabled="batchLoading"
          @click="clearSelection"
        >
          {{ t('admin.apps.batch.clearSelection') }}
        </a-button>
      </div>
    </div>

    <a-spin :loading="loading" class="block">
      <section v-if="apps.length" class="grid gap-4 xl:grid-cols-2">
        <div
          v-for="app in apps"
          :key="app.id"
          class="flex items-start gap-3"
          :class="{ 'rounded-xl ring-2 ring-blue-400': selectedIds.has(app.id) }"
        >
          <a-checkbox
            :model-value="selectedIds.has(app.id)"
            class="mt-5 shrink-0"
            @change="toggleSelect(app.id)"
          />
          <article class="flex flex-1 flex-col gap-3 rounded-xl border border-gray-200 bg-white p-5">
          <div class="flex items-start justify-between gap-3">
            <div class="flex items-center gap-3">
              <span
                v-if="app.icon && isImageUrl(app.icon)"
                class="inline-flex h-10 w-10 items-center justify-center overflow-hidden rounded-lg bg-gray-50"
              >
                <img :src="app.icon" :alt="app.name" class="h-full w-full object-cover" />
              </span>
              <span
                v-else-if="app.icon"
                class="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-gray-50 text-xl"
                >{{ app.icon }}</span
              >
              <span
                v-else
                class="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-gray-50 text-xl text-gray-400"
                >🤖</span
              >
              <div>
                <h2 class="text-base font-semibold text-gray-900">{{ app.name }}</h2>
                <p class="font-mono text-xs text-gray-400">{{ app.id }}</p>
              </div>
            </div>
            <a-tag v-if="app.status" :color="statusColor(app.status)" size="small">
              {{ statusLabel(app.status) }}
            </a-tag>
          </div>

          <p class="text-sm text-gray-600">
            {{ app.description || t('admin.apps.noDescription') }}
          </p>

          <dl class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <div class="flex gap-1">
              <dt class="text-gray-400">{{ t('admin.apps.accountId') }}:</dt>
              <dd class="text-gray-700">{{ app.account_id || '-' }}</dd>
            </div>
            <div class="flex gap-1">
              <dt class="text-gray-400">{{ t('admin.apps.createdAt') }}:</dt>
              <dd class="text-gray-700">{{ formatTimestamp(app.created_at) }}</dd>
            </div>
          </dl>

          <!-- 池治理字段：只读展示 + 数据所有权提示 -->
          <div class="rounded-lg bg-gray-50 p-3">
            <div class="flex flex-wrap items-center gap-2 text-xs">
              <span class="text-gray-400">{{ t('admin.apps.poolFields.primaryPool') }}:</span>
              <a-tag size="small">{{ app.agent_metadata?.primary_pool || '-' }}</a-tag>
              <span class="text-gray-400">{{ t('admin.apps.poolFields.riskLevel') }}:</span>
              <a-tag :color="riskColor(app.agent_metadata?.risk_level)" size="small">{{
                app.agent_metadata?.risk_level || '-'
              }}</a-tag>
              <span class="text-gray-400">{{ t('admin.apps.poolFields.routingPriority') }}:</span>
              <a-tag size="small">{{ app.agent_metadata?.routing_priority ?? '-' }}</a-tag>
              <span class="text-gray-400">{{ t('admin.apps.poolFields.enabled') }}:</span>
              <a-tag
                :color="app.agent_metadata?.enabled ? 'green' : 'gray'"
                size="small"
                >{{
                  app.agent_metadata?.enabled ? t('admin.apps.enabledYes') : t('admin.apps.enabledNo')
                }}</a-tag
              >
            </div>
            <p class="mt-2 text-xs text-gray-400">
              {{ t('admin.apps.poolOwnershipHint') }}
              <router-link
                :to="{ name: 'admin-agent-pool' }"
                class="font-medium text-blue-600 hover:underline"
                >{{ t('admin.apps.goToAgentPool') }}</router-link
              >
            </p>
          </div>

          <div class="mt-auto flex justify-end gap-2">
            <a-button size="small" :data-testid="`app-view-${app.id}`" @click="handleViewDetail(app)">
              {{ t('admin.apps.viewDetail') }}
            </a-button>
            <a-button
              v-if="canUpdate"
              type="primary"
              size="small"
              :data-testid="`app-edit-${app.id}`"
              @click="openEditBasic(app)"
            >
              {{ t('admin.apps.editBasic') }}
            </a-button>
            <a-button
              v-if="canUpdate"
              size="small"
              :data-testid="`app-edit-metadata-${app.id}`"
              @click="openEditMetadata(app)"
            >
              {{ t('admin.apps.editMetadata') }}
            </a-button>
            <a-button
              v-if="canDelete"
              size="small"
              status="danger"
              :data-testid="`app-delete-${app.id}`"
              @click="handleDelete(app)"
            >
              {{ t('admin.apps.deleteButton') }}
            </a-button>
          </div>
          </article>
        </div>
      </section>

      <section
        v-else
        class="rounded-xl border border-dashed border-gray-300 bg-white px-6 py-12 text-center"
      >
        <h2 class="text-lg font-medium text-gray-900">{{ t('admin.apps.emptyTitle') }}</h2>
        <p class="mt-2 text-sm text-gray-500">{{ emptyDescription }}</p>
      </section>
    </a-spin>

    <div v-if="apps.length" class="flex justify-end">
      <a-pagination
        :total="total"
        :current="filters.current_page"
        :page-size="filters.page_size"
        show-total
        show-page-size
        :page-size-options="[10, 20, 50, 100]"
        @change="onPageChange"
        @page-size-change="onPageSizeChange"
      />
    </div>

    <!-- 编辑基本信息弹窗 -->
    <a-modal
      v-model:visible="modalVisible"
      :title="t('admin.apps.editBasicTitle')"
      :ok-loading="saving"
      :mask-closable="false"
      @ok="submitEditBasic"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item :label="t('admin.apps.appName')" field="name">
          <a-input v-model="form.name" :placeholder="t('admin.apps.namePlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('admin.apps.appDescription')" field="description">
          <a-textarea
            v-model="form.description"
            :placeholder="t('admin.apps.descriptionPlaceholder')"
            :auto-size="{ minRows: 2, maxRows: 6 }"
          />
        </a-form-item>
        <a-form-item :label="t('admin.apps.appIcon')" field="icon">
          <a-input v-model="form.icon" :placeholder="t('admin.apps.iconPlaceholder')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 创建应用弹窗（name + description + icon） -->
    <a-modal
      v-model:visible="createModalVisible"
      :title="t('admin.apps.createButton')"
      :ok-loading="creating"
      :mask-closable="false"
      @ok="submitCreate"
    >
      <a-form :model="createForm" layout="vertical">
        <a-form-item :label="t('admin.apps.appName')" field="name" required>
          <a-input v-model="createForm.name" :placeholder="t('admin.apps.namePlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('admin.apps.appDescription')" field="description">
          <a-textarea
            v-model="createForm.description"
            :placeholder="t('admin.apps.descriptionPlaceholder')"
            :auto-size="{ minRows: 2, maxRows: 6 }"
          />
        </a-form-item>
        <a-form-item :label="t('admin.apps.appIcon')" field="icon">
          <a-input v-model="createForm.icon" :placeholder="t('admin.apps.iconPlaceholder')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 编辑池治理字段弹窗（primary_pool / risk_level / model_tier / routing_priority） -->
    <a-modal
      v-model:visible="metadataModalVisible"
      :title="t('admin.apps.editMetadataTitle')"
      :ok-loading="metadataSaving"
      :mask-closable="false"
      unmount-on-close
      @ok="submitEditMetadata"
    >
      <AgentMetadataEditor v-model="metadataForm" />
    </a-modal>
  </section>
</template>
