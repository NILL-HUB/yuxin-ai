<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import AdminWorkflowCard from '@/components/admin/AdminWorkflowCard.vue'
import AdminWorkflowToolbar from '@/components/admin/AdminWorkflowToolbar.vue'
import type { AdminWorkflowRecord, GetAdminWorkflowsRequest } from '@/models/admin-workflow'
import {
  batchOfflineAdminWorkflows,
  batchPublishAdminWorkflows,
  createAdminWorkflow,
  deleteAdminWorkflow,
  listAdminWorkflows,
} from '@/services/admin-workflows'
import { getErrorMessage } from '@/utils/error'

type WorkflowPaginator = {
  total_record: number
  total_page: number
  current_page: number
  page_size: number
}

type CreateWorkflowForm = {
  name: string
  description: string
  icon: string
  tool_call_name: string
}

/**
 * 后台工作流管理页，负责列表查询、创建、删除与跳转编辑器。
 */
const router = useRouter()
const { t } = useI18n()

const loading = ref(false)
const saving = ref(false)
const batchLoading = ref(false)
const workflows = ref<AdminWorkflowRecord[]>([])
const paginator = ref<WorkflowPaginator>({
  total_record: 0,
  total_page: 0,
  current_page: 1,
  page_size: 20,
})
const filters = ref<GetAdminWorkflowsRequest>({
  search: '',
  status: '',
  current_page: 1,
  page_size: 20,
})
const showCreateModal = ref(false)
const createForm = ref<CreateWorkflowForm>({ name: '', description: '', icon: '', tool_call_name: '' })
const selectedIds = ref<Set<string>>(new Set())
const allSelected = computed(() => workflows.value.length > 0 && workflows.value.every((w) => selectedIds.value.has(w.id)))
const selectedCount = computed(() => selectedIds.value.size)

const hasActiveFilters = computed(() => Boolean(filters.value.search || filters.value.status))
const emptyDescription = computed(() => {
  return hasActiveFilters.value
    ? t('admin.workflowsAdmin.emptyFiltered')
    : t('admin.workflowsAdmin.empty')
})

/**
 * 拉取后台工作流列表并同步分页状态。
 */
const loadWorkflows = async () => {
  loading.value = true
  try {
    const result = await listAdminWorkflows({ ...filters.value })
    workflows.value = result.list
    paginator.value = result.paginator
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.workflowsAdmin.loadFailed')))
  } finally {
    loading.value = false
  }
}

/**
 * 搜索条件变化后刷新列表，并回到第一页。
 */
const handleSearchChange = async (value: string) => {
  filters.value.search = value
  filters.value.current_page = 1
  await loadWorkflows()
}

/**
 * 状态筛选变化后刷新列表，并回到第一页。
 */
const handleStatusChange = async (value: string) => {
  filters.value.status = value
  filters.value.current_page = 1
  await loadWorkflows()
}

/**
 * 跳转到后台工作流编辑器。
 */
const handleEdit = async (workflowId: string) => {
  await router.push({ name: 'admin-workflow-edit', params: { workflow_id: workflowId } })
}

/**
 * 打开创建工作流弹窗。
 */
const openCreateModal = () => {
  createForm.value = { name: '', description: '', icon: '', tool_call_name: '' }
  showCreateModal.value = true
}

/**
 * 提交创建工作流，成功后跳转到编辑器。
 */
const submitCreate = async () => {
  if (!createForm.value.name?.trim()) {
    Message.warning(t('admin.workflowsAdmin.nameRequired'))
    return
  }
  saving.value = true
  try {
    const workflow = await createAdminWorkflow({
      name: createForm.value.name,
      description: createForm.value.description,
      icon: createForm.value.icon || 'https://placehold.co/100x100/png?text=WF',
      tool_call_name: createForm.value.tool_call_name || createForm.value.name,
    })
    Message.success(t('admin.workflowsAdmin.createSuccess'))
    showCreateModal.value = false
    await router.push({
      name: 'admin-workflow-edit',
      params: { workflow_id: workflow.id },
    })
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.workflowsAdmin.createFailed')))
  } finally {
    saving.value = false
  }
}

/**
 * 删除后台工作流。
 */
const handleDelete = (workflow: AdminWorkflowRecord) => {
  Modal.warning({
    title: t('admin.workflowsAdmin.deleteTitle'),
    content: t('admin.workflowsAdmin.deleteContent', { name: workflow.name }),
    hideCancel: false,
    onOk: async () => {
      try {
        await deleteAdminWorkflow(workflow.id)
        Message.success(t('admin.workflowsAdmin.deleteSuccess'))
      } catch (error) {
        Message.error(getErrorMessage(error, t('admin.workflowsAdmin.deleteFailed')))
      } finally {
        void loadWorkflows()
      }
    },
  })
}

/**
 * 切换单个工作流选择状态。
 */
const toggleSelect = (workflowId: string) => {
  const next = new Set(selectedIds.value)
  if (next.has(workflowId)) {
    next.delete(workflowId)
  } else {
    next.add(workflowId)
  }
  selectedIds.value = next
}

/**
 * 全选/取消全选当前页工作流。
 */
const toggleSelectAll = () => {
  if (allSelected.value) {
    selectedIds.value = new Set()
  } else {
    selectedIds.value = new Set(workflows.value.map((w) => w.id))
  }
}

const clearSelection = () => {
  selectedIds.value = new Set()
}

/**
 * 批量发布选中的工作流。
 */
const handleBatchPublish = () => {
  if (selectedCount.value === 0) {
    Message.info(t('admin.workflowsAdmin.batch.noSelection'))
    return
  }
  Modal.warning({
    title: t('admin.workflowsAdmin.batch.publishTitle'),
    content: t('admin.workflowsAdmin.batch.publishContent', { count: selectedCount.value }),
    hideCancel: false,
    onOk: async () => {
      batchLoading.value = true
      try {
        const result = await batchPublishAdminWorkflows(Array.from(selectedIds.value))
        const okCount = result.succeeded.length
        const failCount = result.failed.length
        if (failCount === 0) {
          Message.success(t('admin.workflowsAdmin.batch.publishSuccess', { count: okCount }))
        } else {
          Message.warning(
            t('admin.workflowsAdmin.batch.partialSuccess', { ok: okCount, fail: failCount }),
          )
        }
        clearSelection()
        await loadWorkflows()
      } catch (error) {
        Message.error(getErrorMessage(error, t('admin.workflowsAdmin.batch.publishFailed')))
      } finally {
        batchLoading.value = false
      }
    },
  })
}

/**
 * 批量下架选中的工作流。
 */
const handleBatchOffline = () => {
  if (selectedCount.value === 0) {
    Message.info(t('admin.workflowsAdmin.batch.noSelection'))
    return
  }
  Modal.warning({
    title: t('admin.workflowsAdmin.batch.offlineTitle'),
    content: t('admin.workflowsAdmin.batch.offlineContent', { count: selectedCount.value }),
    hideCancel: false,
    onOk: async () => {
      batchLoading.value = true
      try {
        const result = await batchOfflineAdminWorkflows(Array.from(selectedIds.value))
        const okCount = result.succeeded.length
        const failCount = result.failed.length
        if (failCount === 0) {
          Message.success(t('admin.workflowsAdmin.batch.offlineSuccess', { count: okCount }))
        } else {
          Message.warning(
            t('admin.workflowsAdmin.batch.partialSuccess', { ok: okCount, fail: failCount }),
          )
        }
        clearSelection()
        await loadWorkflows()
      } catch (error) {
        Message.error(getErrorMessage(error, t('admin.workflowsAdmin.batch.offlineFailed')))
      } finally {
        batchLoading.value = false
      }
    },
  })
}

const onPageChange = (page: number) => {
  filters.value.current_page = page
  clearSelection()
  void loadWorkflows()
}

const onPageSizeChange = (size: number) => {
  filters.value.page_size = size
  filters.value.current_page = 1
  clearSelection()
  void loadWorkflows()
}

onMounted(() => {
  void loadWorkflows()
})
</script>

<template>
  <section class="space-y-6">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold text-slate-900">{{ t('admin.workflowsAdmin.title') }}</h1>
        <p class="mt-1 text-sm text-slate-500">{{ t('admin.workflowsAdmin.description') }}</p>
      </div>
      <a-button type="primary" @click="openCreateModal">
        <template #icon>
          <icon-plus />
        </template>
        {{ t('admin.workflowsAdmin.createButton') }}
      </a-button>
    </header>

    <a-alert type="info" :show-icon="true">
      {{ t('admin.storeOps.storeHint') }}
    </a-alert>

    <AdminWorkflowToolbar
      :search="filters.search"
      :status="filters.status"
      :loading="loading"
      @update:search="handleSearchChange"
      @update:status="handleStatusChange"
      @refresh="loadWorkflows"
    />

    <!-- 批量操作工具条 -->
    <div
      v-if="workflows.length"
      class="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm"
    >
      <a-checkbox :model-value="allSelected" @change="toggleSelectAll">
        {{ t('admin.workflowsAdmin.batch.selectAll') }}
      </a-checkbox>
      <span class="text-xs text-slate-400">
        {{ t('admin.workflowsAdmin.batch.selected', { count: selectedCount }) }}
      </span>
      <div class="ml-auto flex flex-wrap gap-2">
        <a-button
          size="small"
          type="primary"
          :loading="batchLoading"
          :disabled="selectedCount === 0"
          @click="handleBatchPublish"
        >
          {{ t('admin.workflowsAdmin.batch.publish') }}
        </a-button>
        <a-button
          size="small"
          status="warning"
          :loading="batchLoading"
          :disabled="selectedCount === 0"
          @click="handleBatchOffline"
        >
          {{ t('admin.workflowsAdmin.batch.offline') }}
        </a-button>
        <a-button
          v-if="selectedCount > 0"
          size="small"
          :disabled="batchLoading"
          @click="clearSelection"
        >
          {{ t('admin.workflowsAdmin.batch.clearSelection') }}
        </a-button>
      </div>
    </div>

    <section v-if="workflows.length" class="grid gap-4 xl:grid-cols-2">
      <div
        v-for="workflow in workflows"
        :key="workflow.id"
        class="flex items-start gap-3"
        :class="{
          'rounded-xl ring-2 ring-blue-400': selectedIds.has(workflow.id),
        }"
      >
        <a-checkbox
          :model-value="selectedIds.has(workflow.id)"
          class="mt-5 shrink-0"
          @change="toggleSelect(workflow.id)"
        />
        <AdminWorkflowCard
          class="flex-1"
          :workflow="workflow"
          :can-update="false"
          :can-delete="true"
          @edit="handleEdit"
          @delete="handleDelete"
        />
      </div>
    </section>

    <section
      v-else
      class="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center"
    >
      <h2 class="text-lg font-medium text-slate-900">{{ t('admin.workflowsAdmin.emptyTitle') }}</h2>
      <p class="mt-2 text-sm text-slate-500">{{ emptyDescription }}</p>
    </section>

    <div v-if="workflows.length" class="flex items-center justify-between">
      <span class="text-xs text-slate-400">
        {{ t('admin.workflowsAdmin.total', { count: paginator.total_record }) }}
      </span>
      <a-pagination
        :total="paginator.total_record"
        :current="paginator.current_page"
        :page-size="paginator.page_size"
        show-total
        show-page-size
        :page-size-options="[10, 20, 50, 100]"
        @change="onPageChange"
        @page-size-change="onPageSizeChange"
      />
    </div>

    <!-- 创建工作流弹窗（仅 name + description） -->
    <a-modal
      v-model:visible="showCreateModal"
      :title="t('admin.workflowsAdmin.createButton')"
      :ok-loading="saving"
      :mask-closable="false"
      @ok="submitCreate"
    >
      <a-form :model="createForm" layout="vertical">
        <a-form-item :label="t('admin.workflowsAdmin.formName')" field="name" required>
          <a-input v-model="createForm.name" :placeholder="t('admin.workflowsAdmin.namePlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('admin.workflowsAdmin.formDescription')" field="description">
          <a-textarea
            v-model="createForm.description"
            :placeholder="t('admin.workflowsAdmin.descriptionPlaceholder')"
            :auto-size="{ minRows: 2, maxRows: 6 }"
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
