<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import type { GetMcpProvidersWithPageRequest, McpProvider } from '@/models/mcp'
import { listAdminMcpProviders } from '@/services/admin-mcp'
import { getErrorMessage } from '@/utils/error'
import CreateOrUpdateMcpModal from '@/views/space/mcp/components/CreateOrUpdateMcpModal.vue'

type McpPaginator = {
  total_record: number
  total_page: number
  current_page: number
  page_size: number
}

/**
 * 后台 MCP 管理页，负责展示平台可见的 MCP Provider 列表。
 */
const router = useRouter()
const { t } = useI18n()

const loading = ref(false)
const providers = ref<McpProvider[]>([])
const showCreateOrUpdateMcpModalVisible = ref(false)
const updateMcpProviderId = ref('')
const paginator = ref<McpPaginator>({
  total_record: 0,
  total_page: 0,
  current_page: 1,
  page_size: 20,
})
const filters = ref<GetMcpProvidersWithPageRequest>({
  search_word: '',
  current_page: 1,
  page_size: 20,
  category: '',
})

const hasActiveFilters = computed(() => Boolean(filters.value.search_word?.trim()))
const emptyDescription = computed(() => {
  return hasActiveFilters.value
    ? t('admin.mcpAdmin.emptyFiltered')
    : t('admin.mcpAdmin.empty')
})

/**
 * 拉取后台 MCP Provider 列表并同步分页信息。
 */
const loadProviders = async () => {
  loading.value = true
  try {
    const result = await listAdminMcpProviders({ ...filters.value })
    providers.value = result.list || []
    paginator.value = result.paginator
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.mcpAdmin.loadFailed')))
  } finally {
    loading.value = false
  }
}

/**
 * 触发搜索并重置到第一页。
 */
const handleSearch = async () => {
  filters.value.current_page = 1
  await loadProviders()
}

/**
 * 打开创建 MCP 弹窗（复用空间端创建组件）。
 */
const openCreateModal = () => {
  updateMcpProviderId.value = ''
  showCreateOrUpdateMcpModalVisible.value = true
}

/**
 * 打开编辑 MCP 弹窗。
 */
const openEditModal = (provider: McpProvider) => {
  updateMcpProviderId.value = provider.id
  showCreateOrUpdateMcpModalVisible.value = true
}

/**
 * 跳转到 MCP 管理页（内嵌空间端 MCP 管理视图，支持发布、删除等完整操作）。
 */
const handleManage = async () => {
  await router.push({ name: 'admin-mcp-list' })
}

onMounted(() => {
  void loadProviders()
})
</script>

<template>
  <section class="space-y-6">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold text-slate-900">{{ t('admin.mcpAdmin.title') }}</h1>
        <p class="mt-1 text-sm text-slate-500">{{ t('admin.mcpAdmin.description') }}</p>
      </div>
      <div class="flex items-center gap-2">
        <a-button @click="handleManage">
          {{ t('admin.mcpAdmin.manageEntry') }}
        </a-button>
        <a-button type="primary" @click="openCreateModal">
          {{ t('admin.mcpAdmin.createButton') }}
        </a-button>
      </div>
    </header>

    <a-alert type="info" :show-icon="true">
      {{ t('admin.mcpAdmin.manageHint') }}
    </a-alert>

    <section class="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4">
      <a-input
        v-model="filters.search_word"
        class="max-w-xl flex-1 min-w-[260px]"
        :placeholder="t('admin.mcpAdmin.searchPlaceholder')"
        @press-enter="handleSearch"
      />
      <a-button type="primary" :loading="loading" @click="handleSearch">
        {{ t('common.actions.search') }}
      </a-button>
      <a-button :loading="loading" @click="loadProviders">
        {{ t('common.actions.refresh') }}
      </a-button>
    </section>

    <section v-if="providers.length" class="grid gap-4 xl:grid-cols-2">
      <article
        v-for="provider in providers"
        :key="provider.id"
        class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-100"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <h2 class="truncate text-lg font-semibold text-slate-900">{{ provider.label || provider.name }}</h2>
            <p class="mt-2 text-sm text-slate-500">{{ provider.description || '-' }}</p>
          </div>
          <span class="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">
            {{ provider.transport }}
          </span>
        </div>

        <dl class="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <div>
            <dt class="text-slate-400">{{ t('admin.mcpAdmin.providerKey') }}</dt>
            <dd class="mt-1 break-all text-slate-700">{{ provider.provider_key }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">{{ t('admin.mcpAdmin.owner') }}</dt>
            <dd class="mt-1 text-slate-700">{{ provider.creator_name || '-' }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">{{ t('admin.mcpAdmin.toolCount') }}</dt>
            <dd class="mt-1 text-slate-700">{{ provider.tool_count }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">{{ t('admin.mcpAdmin.transport') }}</dt>
            <dd class="mt-1 text-slate-700">{{ provider.transport }}</dd>
          </div>
        </dl>

        <div class="mt-4 flex justify-end">
          <a-button size="small" type="outline" @click="openEditModal(provider)">
            {{ t('admin.mcpAdmin.editButton') }}
          </a-button>
        </div>
      </article>
    </section>

    <section
      v-else
      class="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center"
    >
      <h2 class="text-lg font-medium text-slate-900">{{ t('admin.mcpAdmin.emptyTitle') }}</h2>
      <p class="mt-2 text-sm text-slate-500">{{ emptyDescription }}</p>
    </section>

    <footer class="text-xs text-slate-400">
      {{ t('admin.mcpAdmin.total', { count: paginator.total_record }) }}
    </footer>

    <create-or-update-mcp-modal
      v-model:visible="showCreateOrUpdateMcpModalVisible"
      v-model:mcp_provider_id="updateMcpProviderId"
      :callback="async () => await loadProviders()"
    />
  </section>
</template>
