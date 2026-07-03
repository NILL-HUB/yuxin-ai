<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import type {
  CreateMcpProviderRequest,
  GetMcpProvidersWithPageRequest,
  McpCategory,
  McpProvider,
} from '@/models/mcp'
import { createAdminMcp, deleteAdminMcp, listAdminMcpProviders } from '@/services/admin-mcp'
import { getPublicMcpCategories } from '@/services/mcp'
import { getErrorMessage } from '@/utils/error'
import { formatTimestampShort } from '@/utils/time-formatter'
import { getStoreCategoryDisplayName, getStoreTypeDisplayName } from '@/utils/store-display'
import CreateOrUpdateMcpModal from '@/views/space/mcp/components/CreateOrUpdateMcpModal.vue'
import ResourceCardDescription from '@/components/ResourceCardDescription.vue'
import CardGridSkeleton from '@/components/skeletons/CardGridSkeleton.vue'

type McpPaginator = {
  total_record: number
  total_page: number
  current_page: number
  page_size: number
}

/**
 * 后台 MCP 管理页，负责展示平台可见的 MCP Provider 列表，并提供创建/删除入口。
 * UI 风格与商店页（store/mcp/ListView）保持一致：响应式卡片网格 + 分类筛选 + 详情抽屉。
 */
const router = useRouter()
const { t, locale } = useI18n()

const loading = ref(false)
const saving = ref(false)
const categories = ref<McpCategory[]>([])
const providers = ref<McpProvider[]>([])
const selectedCategory = ref('all')
const showCreateOrUpdateMcpModalVisible = ref(false)
const showAdminCreateModal = ref(false)
const updateMcpProviderId = ref('')
const showDetailVisible = ref(false)
const activeProvider = ref<McpProvider | null>(null)
const paginator = ref<McpPaginator>({
  total_record: 0,
  total_page: 0,
  current_page: 1,
  page_size: 50,
})
const filters = ref<GetMcpProvidersWithPageRequest>({
  search_word: '',
  current_page: 1,
  page_size: 50,
  category: '',
})
const adminForm = ref<CreateMcpProviderRequest>({
  name: '',
  description: '',
  transport: 'streamable_http',
  url: '',
  command: '',
})

/**
 * 头像调色板：渐变兜底，与商店页保持一致。
 */
const avatarPalettes = [
  ['#334155', '#0f172a'],
  ['#0369a1', '#1d4ed8'],
  ['#047857', '#0f766e'],
  ['#c2410c', '#d97706'],
  ['#be123c', '#e11d48'],
  ['#0f766e', '#14b8a6'],
]

const hashString = (value: string) => {
  let hash = 0
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 33 + value.charCodeAt(i)) >>> 0
  }
  return hash
}

const getAvatarText = (provider: McpProvider) => {
  const source = (provider.label || provider.name || provider.provider_key || 'M').trim()
  const latinParts = source.match(/[A-Za-z0-9]+/g)
  if (latinParts && latinParts.length > 0) {
    return latinParts
      .slice(0, 2)
      .map((item) => item[0]?.toUpperCase())
      .join('')
  }
  const chineseParts = source.match(/[\u4e00-\u9fff]/g)
  if (chineseParts && chineseParts.length > 0) {
    return chineseParts.slice(0, 2).join('')
  }
  return source.slice(0, 2).toUpperCase()
}

const getAvatarStyle = (provider: McpProvider) => {
  const palette =
    avatarPalettes[
      hashString(`${provider.provider_key}:${provider.category}:${provider.label}`) %
        avatarPalettes.length
    ]
  return {
    background: `linear-gradient(135deg, ${palette[0]} 0%, ${palette[1]} 100%)`,
    boxShadow: 'inset 0 1px 0 rgba(255, 255, 255, 0.15)',
  }
}

const categoryNameMap = computed(() => {
  return new Map(categories.value.map((item) => [item.id, item.name]))
})

const getCategoryName = (category: string) => {
  const normalized = String(category || '').trim()
  const mappedName = categoryNameMap.value.get(normalized)
  if (locale.value === 'zh-CN' && mappedName) {
    return mappedName
  }
  return getStoreCategoryDisplayName(normalized, locale.value as 'zh-CN' | 'en-US')
}

const getTypeName = (value: string) => {
  return getStoreTypeDisplayName(value, locale.value as 'zh-CN' | 'en-US')
}

const getCategoryButtonClass = (active: boolean) =>
  ['mcp-category-btn', active ? 'mcp-category-btn-active' : 'mcp-category-btn-inactive'].join(' ')

const getSourceName = (provider: McpProvider) => {
  if (provider.source_type === 'catalog') {
    return t('admin.mcpAdmin.publicSource')
  }
  return t('admin.mcpAdmin.userCreatedSource')
}

const hasActiveFilters = computed(
  () => Boolean(filters.value.search_word?.trim()) || selectedCategory.value !== 'all',
)
const emptyDescription = computed(() => {
  return hasActiveFilters.value
    ? t('admin.mcpAdmin.emptyFiltered')
    : t('admin.mcpAdmin.empty')
})

const activeToolsCount = computed(() => {
  const provider = activeProvider.value
  if (!provider) return 0
  return provider.tools?.length || provider.tool_names?.length || 0
})

/**
 * 拉取 MCP 分类（与商店同源，使用公开分类接口）。
 */
const loadCategories = async () => {
  try {
    const res = await getPublicMcpCategories()
    categories.value = res.data.categories || []
  } catch (_error: unknown) {
    categories.value = []
  }
}

/**
 * 拉取后台 MCP Provider 列表并同步分页信息。
 */
const loadProviders = async () => {
  loading.value = true
  try {
    filters.value.category = selectedCategory.value === 'all' ? '' : selectedCategory.value
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
 * 切换分类筛选并重新拉取列表。
 */
const handleCategoryChange = async (category: string) => {
  selectedCategory.value = category
  filters.value.current_page = 1
  await loadProviders()
}

/**
 * 点击卡片打开详情抽屉（直接复用列表数据，无需额外请求）。
 */
const handleCardClick = (provider: McpProvider) => {
  activeProvider.value = provider
  showDetailVisible.value = true
}

/**
 * 阻止操作按钮区域的事件冒泡，避免触发卡片点击。
 */
const stopPropagation = (event: Event) => {
  event.stopPropagation()
}

/**
 * 打开后台创建 MCP 弹窗（直接调 admin 接口）。
 */
const openAdminCreateModal = () => {
  adminForm.value = {
    name: '',
    description: '',
    transport: 'streamable_http',
    url: '',
    command: '',
  }
  showAdminCreateModal.value = true
}

/**
 * 提交后台创建 MCP。
 */
const submitAdminCreate = async () => {
  if (!adminForm.value.name?.trim()) {
    Message.warning(t('admin.mcpAdmin.nameRequired'))
    return
  }
  saving.value = true
  try {
    await createAdminMcp(adminForm.value)
    Message.success(t('admin.mcpAdmin.createSuccess'))
    showAdminCreateModal.value = false
    await loadProviders()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.mcpAdmin.createFailed')))
  } finally {
    saving.value = false
  }
}

/**
 * 打开编辑 MCP 弹窗（复用空间端组件，完整编辑能力）。
 */
const openEditModal = (provider: McpProvider) => {
  updateMcpProviderId.value = provider.id
  showCreateOrUpdateMcpModalVisible.value = true
}

/**
 * 删除后台 MCP Provider。
 */
const handleDelete = (provider: McpProvider) => {
  Modal.warning({
    title: t('admin.mcpAdmin.deleteTitle'),
    content: t('admin.mcpAdmin.deleteContent'),
    hideCancel: false,
    onOk: async () => {
      try {
        await deleteAdminMcp(provider.id)
        Message.success(t('admin.mcpAdmin.deleteSuccess'))
      } catch (error) {
        Message.error(getErrorMessage(error, t('admin.mcpAdmin.deleteFailed')))
      } finally {
        void loadProviders()
      }
    },
  })
}

/**
 * 跳转到 MCP 管理页（内嵌空间端 MCP 管理视图，支持发布、删除等完整操作）。
 */
const handleManage = async () => {
  await router.push({ name: 'admin-mcp' })
}

onMounted(async () => {
  await loadCategories()
  await loadProviders()
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
        <a-button type="primary" @click="openAdminCreateModal">
          {{ t('admin.mcpAdmin.createButton') }}
        </a-button>
      </div>
    </header>

    <a-alert type="info" :show-icon="true">
      {{ t('admin.mcpAdmin.manageHint') }}
    </a-alert>

    <section
      class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4"
    >
      <div class="flex flex-wrap items-center gap-2">
        <a-button
          type="text"
          :class="getCategoryButtonClass(selectedCategory === 'all')"
          @click="handleCategoryChange('all')"
        >
          {{ t('admin.mcpAdmin.all') }}
        </a-button>
        <a-button
          v-for="item in categories"
          :key="item.id"
          type="text"
          :class="getCategoryButtonClass(selectedCategory === item.id)"
          @click="handleCategoryChange(item.id)"
        >
          {{ getCategoryName(item.id || item.name) }}
        </a-button>
      </div>
      <div class="flex items-center gap-2">
        <a-input
          v-model="filters.search_word"
          class="w-full sm:w-[260px]"
          :placeholder="t('admin.mcpAdmin.searchPlaceholder')"
          allow-clear
          @press-enter="handleSearch"
          @clear="handleSearch"
        />
        <a-button type="primary" :loading="loading" @click="handleSearch">
          {{ t('common.actions.search') }}
        </a-button>
        <a-button :loading="loading" @click="loadProviders">
          {{ t('common.actions.refresh') }}
        </a-button>
      </div>
    </section>

    <card-grid-skeleton v-if="loading && providers.length === 0" :count="8" />

    <a-row v-else-if="providers.length" :gutter="[16, 16]">
      <a-col
        v-for="provider in providers"
        :key="provider.id"
        :xs="24"
        :sm="12"
        :md="8"
        :lg="6"
        :xl="6"
      >
        <a-card
          hoverable
          class="cursor-pointer rounded-lg h-full overflow-hidden"
          :body-style="{ padding: '12px' }"
          @click="handleCardClick(provider)"
        >
          <div class="flex items-start gap-2.5 mb-2">
            <a-avatar
              :size="36"
              shape="square"
              class="shrink-0 overflow-hidden"
              :style="provider.icon ? { backgroundColor: '#f3f4f6' } : getAvatarStyle(provider)"
            >
              <img
                v-if="provider.icon"
                :src="provider.icon"
                :alt="provider.name"
                class="w-full h-full object-cover"
              />
              <span v-else class="text-white font-semibold text-[12px] tracking-wide">
                {{ getAvatarText(provider) }}
              </span>
            </a-avatar>
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-1.5 min-w-0">
                <div class="text-sm font-bold text-gray-900 truncate">
                  {{ provider.label || provider.name }}
                </div>
                <a-tag size="small" :color="provider.is_public ? 'green' : 'gray'">
                  {{
                    provider.is_public
                      ? t('admin.mcpAdmin.published')
                      : t('admin.mcpAdmin.unpublished')
                  }}
                </a-tag>
              </div>
              <div class="text-[11px] text-gray-500 line-clamp-1">
                {{
                  t('admin.mcpAdmin.providerSummary', {
                    name: provider.name,
                    count: provider.tool_count,
                  })
                }}
              </div>
            </div>
          </div>

          <resource-card-description :text="provider.description" />

          <div class="flex items-center gap-1.5 flex-wrap mt-2.5">
            <a-tag v-if="provider.category" size="small" color="gray">
              {{ getCategoryName(provider.category) }}
            </a-tag>
            <a-tag size="small" color="arcoblue">{{ provider.transport }}</a-tag>
          </div>

          <div class="flex items-center gap-1.5 mt-2.5">
            <a-avatar
              :size="16"
              class="bg-blue-700 shrink-0"
              :image-url="provider.creator_avatar"
            >
              {{ (provider.creator_name || 'M')[0] }}
            </a-avatar>
            <div class="text-[11px] text-gray-400 truncate">
              {{ provider.creator_name || t('admin.mcpAdmin.publicSource') }} ·
              {{ formatTimestampShort(provider.published_at || provider.created_at) }}
            </div>
          </div>

          <div
            class="flex items-center justify-end gap-1.5 mt-2.5 pt-2 border-t border-gray-100"
            @click="stopPropagation"
          >
            <a-button size="mini" type="outline" @click="openEditModal(provider)">
              {{ t('admin.mcpAdmin.editButton') }}
            </a-button>
            <a-button size="mini" status="danger" @click="handleDelete(provider)">
              {{ t('admin.mcpAdmin.deleteButton') }}
            </a-button>
          </div>
        </a-card>
      </a-col>
    </a-row>

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

    <a-drawer
      :visible="showDetailVisible"
      :width="560"
      :footer="false"
      :title="t('admin.mcpAdmin.detailTitle')"
      :drawer-style="{ background: '#F9FAFB' }"
      @cancel="showDetailVisible = false"
    >
      <div v-if="activeProvider" class="flex flex-col gap-4">
        <div class="flex items-start gap-3">
          <a-avatar
            :size="40"
            shape="square"
            class="overflow-hidden"
            :style="
              activeProvider.icon ? { backgroundColor: '#f3f4f6' } : getAvatarStyle(activeProvider)
            "
          >
            <img
              v-if="activeProvider.icon"
              :src="activeProvider.icon"
              :alt="activeProvider.name"
              class="w-full h-full object-cover"
            />
            <span v-else class="text-white font-semibold text-[12px] tracking-wide">
              {{ getAvatarText(activeProvider) }}
            </span>
          </a-avatar>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <div class="text-sm font-bold text-gray-900">
                {{ activeProvider.label || activeProvider.name }}
              </div>
              <a-tag size="small" :color="activeProvider.is_public ? 'green' : 'gray'">
                {{
                  activeProvider.is_public
                    ? t('admin.mcpAdmin.published')
                    : t('admin.mcpAdmin.unpublished')
                }}
              </a-tag>
            </div>
            <div class="text-[11px] text-gray-500 mt-1">
              {{ activeProvider.creator_name || t('admin.mcpAdmin.publicSource') }} ·
              {{ getSourceName(activeProvider) }}
            </div>
          </div>
        </div>

        <div class="rounded-lg bg-white p-3.5">
          <div class="text-sm text-gray-600 whitespace-pre-wrap">
            {{ activeProvider.description || t('admin.mcpAdmin.noDescription') }}
          </div>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div class="rounded-lg bg-white p-3">
            <div class="text-xs text-gray-500 mb-1">{{ t('admin.mcpAdmin.transport') }}</div>
            <div class="text-sm text-gray-800">{{ activeProvider.transport }}</div>
          </div>
          <div class="rounded-lg bg-white p-3">
            <div class="text-xs text-gray-500 mb-1">{{ t('admin.mcpAdmin.toolCount') }}</div>
            <div class="text-sm text-gray-800">{{ activeProvider.tool_count }}</div>
          </div>
          <div class="rounded-lg bg-white p-3">
            <div class="text-xs text-gray-500 mb-1">{{ t('admin.mcpAdmin.source') }}</div>
            <div class="text-sm text-gray-800">{{ getSourceName(activeProvider) }}</div>
          </div>
          <div class="rounded-lg bg-white p-3">
            <div class="text-xs text-gray-500 mb-1">{{ t('admin.mcpAdmin.category') }}</div>
            <div class="text-sm text-gray-800">
              <a-tag v-if="activeProvider.category" size="small" color="gray">
                {{ getCategoryName(activeProvider.category) }}
              </a-tag>
              <span v-else class="text-gray-400">-</span>
            </div>
          </div>
          <div class="rounded-lg bg-white p-3 col-span-2">
            <div class="text-xs text-gray-500 mb-1">{{ t('admin.mcpAdmin.providerKey') }}</div>
            <div class="text-sm text-gray-800 break-all">{{ activeProvider.provider_key }}</div>
          </div>
        </div>

        <div
          v-if="activeProvider.bind_reason"
          class="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"
        >
          {{ activeProvider.bind_reason }}
        </div>

        <div>
          <div class="flex items-center gap-2 mb-3">
            <div class="text-sm font-semibold text-gray-800">
              {{ t('admin.mcpAdmin.toolsTitle') }}
            </div>
            <a-tag size="small">
              {{ t('admin.mcpAdmin.toolsCountLabel', { count: activeToolsCount }) }}
            </a-tag>
          </div>

          <div
            v-if="(activeProvider.tools?.length || 0) > 0"
            class="flex flex-col gap-2"
          >
            <a-card
              v-for="tool in activeProvider.tools"
              :key="tool.name"
              class="rounded-lg"
              :body-style="{ padding: '12px' }"
            >
              <div class="font-semibold text-gray-900 mb-1">{{ tool.label || tool.name }}</div>
              <div class="text-xs text-gray-500">
                {{ tool.description || t('admin.mcpAdmin.noDescription') }}
              </div>
              <div v-if="tool.inputs && tool.inputs.length > 0" class="mt-3">
                <div class="text-xs text-gray-500 mb-2">
                  {{ t('admin.mcpAdmin.parameters') }}
                </div>
                <div class="flex flex-col gap-2">
                  <div
                    v-for="input in tool.inputs"
                    :key="input.name"
                    class="rounded-md bg-gray-50 p-2"
                  >
                    <div class="flex items-center gap-2 text-xs">
                      <div class="font-semibold text-gray-800">{{ input.name }}</div>
                      <div class="text-gray-500">{{ getTypeName(input.type) }}</div>
                      <a-tag v-if="input.required" size="small" color="red">
                        {{ t('admin.mcpAdmin.required') }}
                      </a-tag>
                    </div>
                    <div class="text-xs text-gray-500 mt-1">{{ input.description }}</div>
                  </div>
                </div>
              </div>
            </a-card>
          </div>

          <div
            v-else-if="(activeProvider.tool_names?.length || 0) > 0"
            class="flex flex-col gap-2"
          >
            <div
              v-for="toolName in activeProvider.tool_names"
              :key="toolName"
              class="rounded-md bg-white px-3 py-2 text-sm text-gray-700 border border-gray-100"
            >
              {{ toolName }}
            </div>
          </div>

          <a-empty v-else :description="t('admin.mcpAdmin.noTools')" />
        </div>
      </div>
    </a-drawer>

    <create-or-update-mcp-modal
      v-model:visible="showCreateOrUpdateMcpModalVisible"
      v-model:mcp_provider_id="updateMcpProviderId"
      :callback="async () => await loadProviders()"
    />

    <!-- 后台创建 MCP 弹窗（直接调 admin 接口） -->
    <a-modal
      v-model:visible="showAdminCreateModal"
      :title="t('admin.mcpAdmin.createButton')"
      :ok-loading="saving"
      :mask-closable="false"
      @ok="submitAdminCreate"
    >
      <a-form :model="adminForm" layout="vertical">
        <a-form-item :label="t('admin.mcpAdmin.formName')" field="name" required>
          <a-input v-model="adminForm.name" :placeholder="t('admin.mcpAdmin.namePlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('admin.mcpAdmin.formDescription')" field="description">
          <a-textarea
            v-model="adminForm.description"
            :placeholder="t('admin.mcpAdmin.descriptionPlaceholder')"
            :auto-size="{ minRows: 2, maxRows: 6 }"
          />
        </a-form-item>
        <a-form-item :label="t('admin.mcpAdmin.formTransport')" field="transport">
          <a-select v-model="adminForm.transport">
            <a-option value="streamable_http">streamable_http</a-option>
            <a-option value="stdio">stdio</a-option>
          </a-select>
        </a-form-item>
        <a-form-item
          v-if="adminForm.transport === 'streamable_http'"
          :label="t('admin.mcpAdmin.formUrl')"
          field="url"
        >
          <a-input v-model="adminForm.url" placeholder="https://example.com/mcp" />
        </a-form-item>
        <a-form-item
          v-if="adminForm.transport === 'stdio'"
          :label="t('admin.mcpAdmin.formCommand')"
          field="command"
        >
          <a-input v-model="adminForm.command" placeholder="npx -y @modelcontextprotocol/server" />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>

<style scoped>
.line-clamp-1 {
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.mcp-category-btn {
  height: 32px;
  border-radius: 10px;
  padding: 0 12px;
  font-size: 12px;
}

.mcp-category-btn-active {
  background: #eef2f7 !important;
  color: #111827 !important;
}

.mcp-category-btn-inactive {
  color: #4b5563 !important;
}

.mcp-category-btn:hover {
  background: #f3f4f6 !important;
}

.mcp-category-btn-active:hover {
  background: #e5e7eb !important;
}
</style>
