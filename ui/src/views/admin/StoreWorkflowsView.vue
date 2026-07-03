<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import AdminWorkflowCard from '@/components/admin/AdminWorkflowCard.vue'
import AdminWorkflowToolbar from '@/components/admin/AdminWorkflowToolbar.vue'
import type { AdminWorkflowRecord, GetAdminWorkflowsRequest } from '@/models/admin-workflow'
import { listAdminWorkflows, offlineAdminWorkflow, updateAdminWorkflow } from '@/services/admin-workflows'
import { useAdminStore } from '@/stores/admin'
import { getErrorMessage } from '@/utils/error'

type WorkflowPaginator = {
  total_record: number
  total_page: number
  current_page: number
  page_size: number
}

/**
 * 资源运营-工作流商店上下架管理页，负责公共商店中工作流资源的上架/下架操作。
 */
const adminStore = useAdminStore()
const { t } = useI18n()

const loading = ref(false)
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

const canUpdate = computed(() => adminStore.hasPermission('workflow:update'))
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
 * 切换工作流公开状态（上架/下架），并在成功后刷新当前列表。
 */
const handleTogglePublic = async (workflow: AdminWorkflowRecord) => {
  try {
    await updateAdminWorkflow(workflow.id, { is_public: !workflow.is_public })
    Message.success(t('admin.workflowsAdmin.updateSuccess'))
    await loadWorkflows()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.workflowsAdmin.updateFailed')))
  }
}

/**
 * 强制下架工作流，并在成功后刷新当前列表。
 */
const handleOffline = async (workflow: AdminWorkflowRecord) => {
  try {
    await offlineAdminWorkflow(workflow.id)
    Message.success(t('admin.workflowsAdmin.offlineSuccess', { name: workflow.name }))
    await loadWorkflows()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.workflowsAdmin.offlineFailed')))
  }
}

/**
 * 在新标签页中以用户视角预览公共工作流商店。
 */
const handlePreviewStore = () => {
  window.open('/store/workflows', '_blank')
}

onMounted(() => {
  void loadWorkflows()
})
</script>

<template>
  <section class="space-y-6">
    <header class="flex items-start justify-between gap-4">
      <div>
        <h1 class="text-2xl font-semibold text-slate-900">{{ t('admin.storeOps.workflowsTitle') }}</h1>
        <p class="mt-1 text-sm text-slate-500">{{ t('admin.storeOps.workflowsDescription') }}</p>
      </div>
      <a-tooltip :content="t('admin.storeOps.previewStoreTip')" position="bl">
        <a-button @click="handlePreviewStore">
          <template #icon>
            <icon-eye />
          </template>
          {{ t('admin.storeOps.previewStore') }}
        </a-button>
      </a-tooltip>
    </header>

    <a-alert type="info" :show-icon="true">
      {{ t('admin.storeOps.opsHint') }}
    </a-alert>

    <a-alert type="info" :show-icon="true">
      {{ t('admin.storeOps.sourceHint') }}
    </a-alert>

    <AdminWorkflowToolbar
      :search="filters.search"
      :status="filters.status"
      :loading="loading"
      @update:search="handleSearchChange"
      @update:status="handleStatusChange"
      @refresh="loadWorkflows"
    />

    <section v-if="workflows.length" class="grid gap-4 xl:grid-cols-2">
      <AdminWorkflowCard
        v-for="workflow in workflows"
        :key="workflow.id"
        :workflow="workflow"
        :can-update="canUpdate"
        :can-edit="false"
        @toggle-public="handleTogglePublic"
        @offline="handleOffline"
      />
    </section>

    <section
      v-else
      class="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center"
    >
      <h2 class="text-lg font-medium text-slate-900">{{ t('admin.workflowsAdmin.emptyTitle') }}</h2>
      <p class="mt-2 text-sm text-slate-500">{{ emptyDescription }}</p>
    </section>

    <footer class="text-xs text-slate-400">
      {{ t('admin.workflowsAdmin.total', { count: paginator.total_record }) }}
    </footer>
  </section>
</template>
