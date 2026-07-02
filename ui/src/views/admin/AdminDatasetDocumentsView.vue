<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import type {
  AdminDatasetDocumentRecord,
  AdminDatasetDocumentPageData,
  GetAdminDatasetDocumentsRequest,
} from '@/models/admin-dataset-document'
import { listAdminDatasetDocuments } from '@/services/admin-dataset-documents'
import {
  deleteAdminDatasetDocument,
  renameAdminDatasetDocument,
  updateAdminDatasetDocumentEnabled,
} from '@/services/admin-dataset-document-actions'
import { useAdminStore } from '@/stores/admin'
import { getErrorMessage } from '@/utils/error'

/**
 * 后台文档页使用的数据分页结构。
 */
type DatasetDocumentPaginator = AdminDatasetDocumentPageData['paginator']

const route = useRoute()
const router = useRouter()
const adminStore = useAdminStore()
const { t } = useI18n()

const loading = ref(false)
const documents = ref<AdminDatasetDocumentRecord[]>([])
const actionLoadingId = ref('')
const batchLoading = ref(false)
const renameModalVisible = ref(false)
const renameSubmitting = ref(false)
const renameTarget = ref<AdminDatasetDocumentRecord | null>(null)
const renameDraftName = ref('')
const selectedDocumentIds = ref<string[]>([])
const paginator = ref<DatasetDocumentPaginator>({
  total_record: 0,
  total_page: 0,
  current_page: 1,
  page_size: 20,
})

const datasetId = computed(() => String(route.params.dataset_id ?? ''))

/**
 * 判断当前管理员是否拥有文档治理写权限。
 */
const canWrite = computed(() => adminStore.hasPermission('dataset:update'))

/**
 * 从当前路由查询参数构造后台文档列表请求参数。
 */
const buildRequestParams = (): GetAdminDatasetDocumentsRequest => {
  return {
    current_page: Number(route.query.current_page ?? 1),
    page_size: Number(route.query.page_size ?? 20),
    search_word: String(route.query.search_word ?? ''),
  }
}

/**
 * 拉取后台知识库文档列表，并同步页面展示数据。
 */
const loadDocuments = async () => {
  if (!datasetId.value) return

  loading.value = true
  try {
    const result = await listAdminDatasetDocuments(datasetId.value, buildRequestParams())
    documents.value = result.list
    paginator.value = result.paginator
    selectedDocumentIds.value = selectedDocumentIds.value.filter((id) =>
      documents.value.some((document) => document.id === id),
    )
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.datasetDocuments.loadFailed')))
  } finally {
    loading.value = false
  }
}

/**
 * 将文档统计数格式化为便于阅读的字符串。
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

/**
 * 将文档处理状态映射为后台文案。
 */
const formatDocumentStatus = (status: string) => {
  const messageKey = `admin.datasetDocuments.statuses.${status}`
  const translated = t(messageKey)
  return translated === messageKey ? status || '-' : translated
}

/**
 * 判断当前文档是否允许切换启停状态。
 */
const canToggleDocument = (document: AdminDatasetDocumentRecord) => {
  return document.status === 'completed'
}

/**
 * 判断当前文档是否允许删除。
 */
const canDeleteDocument = (document: AdminDatasetDocumentRecord) => {
  return ['completed', 'error'].includes(document.status)
}

/**
 * 判断当前文档是否处于选中状态。
 */
const isDocumentSelected = (documentId: string) => {
  return selectedDocumentIds.value.includes(documentId)
}

/**
 * 清空当前页面中的文档选中状态。
 */
const clearSelectedDocuments = () => {
  selectedDocumentIds.value = []
}

/**
 * 切换单个文档的选中状态。
 */
const toggleDocumentSelection = (documentId: string, checked: boolean) => {
  selectedDocumentIds.value = checked
    ? [...new Set([...selectedDocumentIds.value, documentId])]
    : selectedDocumentIds.value.filter((id) => id !== documentId)
}

/**
 * 处理文档勾选框的 change 事件。
 */
const handleDocumentSelectionChange = (documentId: string, event: Event) => {
  if (!canWrite.value) return

  const target = event.target as HTMLInputElement | null
  toggleDocumentSelection(documentId, Boolean(target?.checked))
}

/**
 * 获取当前选中的文档列表。
 */
const getSelectedDocuments = () => {
  return documents.value.filter((document) => selectedDocumentIds.value.includes(document.id))
}

/**
 * 串行执行选中文档的批量动作，并在成功后刷新列表。
 */
const runBatchAction = async (
  targets: AdminDatasetDocumentRecord[],
  handler: (document: AdminDatasetDocumentRecord) => Promise<void>,
  successMessageKey: string,
) => {
  if (targets.length === 0) return

  batchLoading.value = true
  try {
    for (const document of targets) {
      await handler(document)
    }
    Message.success(t(successMessageKey))
    clearSelectedDocuments()
    await loadDocuments()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.datasetDocuments.feedback.batchActionFailed')))
  } finally {
    batchLoading.value = false
  }
}

/**
 * 批量切换选中文档的启用状态。
 */
const handleBatchToggleDocuments = async (enabled: boolean) => {
  if (!datasetId.value || !canWrite.value) return

  const targets = getSelectedDocuments().filter(
    (document) => canToggleDocument(document) && document.enabled !== enabled,
  )

  await runBatchAction(
    targets,
    async (document) => {
      await updateAdminDatasetDocumentEnabled(datasetId.value, document.id, enabled)
    },
    enabled
      ? 'admin.datasetDocuments.feedback.batchEnableSuccess'
      : 'admin.datasetDocuments.feedback.batchDisableSuccess',
  )
}

/**
 * 删除当前选中的文档。
 */
const handleBatchDelete = async () => {
  if (!datasetId.value || !canWrite.value) return

  const targets = getSelectedDocuments().filter((document) => canDeleteDocument(document))

  await runBatchAction(
    targets,
    async (document) => {
      await deleteAdminDatasetDocument(datasetId.value, document.id)
    },
    'admin.datasetDocuments.feedback.batchDeleteSuccess',
  )
}

/**
 * 打开单条文档重命名弹窗，并回填当前名称。
 */
const openRenameModal = (document: AdminDatasetDocumentRecord) => {
  if (!canWrite.value) return

  renameTarget.value = document
  renameDraftName.value = document.name
  renameModalVisible.value = true
}

/**
 * 关闭文档重命名弹窗，并清理临时表单状态。
 */
const closeRenameModal = () => {
  renameModalVisible.value = false
  renameTarget.value = null
  renameDraftName.value = ''
}

/**
 * 提交文档重命名请求，并在成功后刷新列表。
 */
const handleRenameDocument = async () => {
  if (!datasetId.value || !renameTarget.value || !canWrite.value) return

  const nextName = renameDraftName.value.trim()
  if (!nextName) {
    Message.error(t('admin.datasetDocuments.renameModal.required'))
    return
  }

  renameSubmitting.value = true
  try {
    await renameAdminDatasetDocument(datasetId.value, renameTarget.value.id, nextName)
    Message.success(t('admin.datasetDocuments.feedback.renameSuccess'))
    closeRenameModal()
    await loadDocuments()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.datasetDocuments.feedback.renameFailed')))
  } finally {
    renameSubmitting.value = false
  }
}

/**
 * 切换单条文档启停状态，并在成功后刷新列表。
 */
const handleToggleDocument = async (document: AdminDatasetDocumentRecord) => {
  if (!datasetId.value || !canWrite.value || !canToggleDocument(document)) return

  actionLoadingId.value = `toggle-${document.id}`
  try {
    await updateAdminDatasetDocumentEnabled(datasetId.value, document.id, !document.enabled)
    Message.success(
      t(document.enabled ? 'admin.datasetDocuments.feedback.disableSuccess' : 'admin.datasetDocuments.feedback.enableSuccess'),
    )
    await loadDocuments()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.datasetDocuments.feedback.toggleFailed')))
  } finally {
    actionLoadingId.value = ''
  }
}

/**
 * 删除单条文档，并在成功后刷新列表。
 */
const handleDeleteDocument = async (document: AdminDatasetDocumentRecord) => {
  if (!datasetId.value || !canWrite.value || !canDeleteDocument(document)) return

  actionLoadingId.value = `delete-${document.id}`
  try {
    await deleteAdminDatasetDocument(datasetId.value, document.id)
    Message.success(t('admin.datasetDocuments.feedback.deleteSuccess'))
    await loadDocuments()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.datasetDocuments.feedback.deleteFailed')))
  } finally {
    actionLoadingId.value = ''
  }
}

/**
 * 跳转到后台文档分段页面。
 */
const goToSegments = async (documentId: string) => {
  await router.push({
    name: 'admin-dataset-segments',
    params: {
      dataset_id: datasetId.value,
      document_id: documentId,
    },
  })
}

onMounted(() => {
  void loadDocuments()
})
</script>

<template>
  <section class="space-y-6">
    <header class="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
      <div>
        <h1 class="text-2xl font-semibold text-slate-900">
          {{ t('admin.datasetDocuments.title') }}
        </h1>
        <p class="mt-1 text-sm text-slate-500">
          {{ t('admin.datasetDocuments.description', { datasetId }) }}
        </p>
      </div>

      <router-link
        v-if="canWrite"
        :to="{ name: 'admin-dataset-document-create', params: { dataset_id: datasetId } }"
      >
        <a-button type="primary">{{ t('admin.datasetDocuments.importEntry') }}</a-button>
      </router-link>
    </header>

    <section
      class="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500"
    >
      <span>{{ t('admin.datasetDocuments.datasetLabel') }} {{ datasetId }}</span>
      <span>{{ t('admin.datasetDocuments.total', { count: paginator.total_record }) }}</span>
    </section>

    <section
      v-if="loading"
      class="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center text-sm text-slate-500"
    >
      {{ t('admin.datasetDocuments.loading') }}
    </section>

    <section
      v-else-if="documents.length === 0"
      class="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center"
    >
      <h2 class="text-lg font-medium text-slate-900">{{ t('admin.datasetDocuments.emptyTitle') }}</h2>
      <p class="mt-2 text-sm text-slate-500">{{ t('admin.datasetDocuments.empty') }}</p>
    </section>

    <section
      v-if="canWrite && selectedDocumentIds.length"
      class="flex flex-wrap items-center gap-3 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3"
    >
      <span class="text-sm text-blue-700">
        {{ t('admin.datasetDocuments.batch.selected', { count: selectedDocumentIds.length }) }}
      </span>
      <a-button
        size="small"
        :disabled="batchLoading"
        data-testid="documents-batch-enable"
        @click="handleBatchToggleDocuments(true)"
      >
        {{ t('admin.datasetDocuments.batch.enable') }}
      </a-button>
      <a-button
        size="small"
        :disabled="batchLoading"
        data-testid="documents-batch-disable"
        @click="handleBatchToggleDocuments(false)"
      >
        {{ t('admin.datasetDocuments.batch.disable') }}
      </a-button>
      <a-button
        size="small"
        status="danger"
        :disabled="batchLoading"
        data-testid="documents-batch-delete"
        @click="handleBatchDelete"
      >
        {{ t('admin.datasetDocuments.batch.delete') }}
      </a-button>
    </section>

    <section v-if="!loading && documents.length > 0" class="grid gap-4">
      <article
        v-for="document in documents"
        :key="document.id"
        class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-100"
      >
        <div class="flex items-start justify-between gap-4">
          <div class="flex min-w-0 items-start gap-3">
            <input
              v-if="canWrite"
              :checked="isDocumentSelected(document.id)"
              :data-testid="`document-select-${document.id}`"
              class="mt-1 h-4 w-4 cursor-pointer rounded border-slate-300"
              type="checkbox"
              @change="handleDocumentSelectionChange(document.id, $event)"
            />
            <div class="min-w-0">
              <h2 class="truncate text-lg font-semibold text-slate-900">{{ document.name }}</h2>
              <p class="mt-1 text-xs text-slate-400">{{ document.id }}</p>
            </div>
          </div>
          <span
            class="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600"
          >
            {{ formatDocumentStatus(document.status) }}
          </span>
        </div>

        <dl class="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <div>
            <dt class="text-slate-400">{{ t('admin.datasetDocuments.columns.characterCount') }}</dt>
            <dd class="mt-1 text-slate-700">{{ formatCount(document.character_count) }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">{{ t('admin.datasetDocuments.columns.segmentCount') }}</dt>
            <dd class="mt-1 text-slate-700">{{ formatCount(document.segment_count) }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">{{ t('admin.datasetDocuments.columns.hitCount') }}</dt>
            <dd class="mt-1 text-slate-700">{{ formatCount(document.hit_count) }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">{{ t('admin.datasetDocuments.columns.updatedAt') }}</dt>
            <dd class="mt-1 text-slate-700">{{ formatTimestamp(document.updated_at) }}</dd>
          </div>
        </dl>

        <div
          v-if="document.status === 'error' && document.error"
          class="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-600"
        >
          <span class="font-medium">{{ t('admin.datasetDocuments.errorLabel') }}:</span>
          <span class="ml-1">{{ document.error }}</span>
        </div>

        <div class="mt-4 flex flex-wrap gap-2">
          <template v-if="canWrite">
          <a-button
            size="small"
            :data-testid="`document-rename-${document.id}`"
            @click="openRenameModal(document)"
          >
            {{ t('admin.datasetDocuments.actions.rename') }}
          </a-button>
          <a-button
            size="small"
            :disabled="!canToggleDocument(document) || actionLoadingId === `toggle-${document.id}`"
            :data-testid="`document-toggle-${document.id}`"
            @click="handleToggleDocument(document)"
          >
            {{
              document.enabled
                ? t('admin.datasetDocuments.actions.disable')
                : t('admin.datasetDocuments.actions.enable')
            }}
          </a-button>
          <a-button
            size="small"
            status="danger"
            :disabled="!canDeleteDocument(document) || actionLoadingId === `delete-${document.id}`"
            :data-testid="`document-delete-${document.id}`"
            @click="handleDeleteDocument(document)"
          >
            {{ t('admin.datasetDocuments.actions.delete') }}
          </a-button>
          </template>
          <a-button
            size="small"
            :data-testid="`document-segments-${document.id}`"
            @click="goToSegments(document.id)"
          >
            {{ t('admin.datasetDocuments.actions.viewSegments') }}
          </a-button>
        </div>
      </article>
    </section>

    <a-modal :visible="renameModalVisible" :footer="false" @cancel="closeRenameModal">
      <div class="space-y-4">
        <div class="text-lg font-semibold text-slate-900">
          {{ t('admin.datasetDocuments.renameModal.title') }}
        </div>
        <a-input
          v-model="renameDraftName"
          data-testid="document-rename-input"
          :placeholder="t('admin.datasetDocuments.renameModal.placeholder')"
        />
        <div class="flex justify-end gap-2">
          <a-button data-testid="document-rename-cancel" @click="closeRenameModal">
            {{ t('admin.datasetDocuments.renameModal.cancel') }}
          </a-button>
          <a-button
            type="primary"
            :loading="renameSubmitting"
            data-testid="document-rename-confirm"
            @click="handleRenameDocument"
          >
            {{ t('admin.datasetDocuments.renameModal.confirm') }}
          </a-button>
        </div>
      </div>
    </a-modal>
  </section>
</template>
