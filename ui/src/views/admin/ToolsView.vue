<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message, Modal, type FileItem, type ValidatedError, Form } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { apiPrefix } from '@/config'
import { useGenerateAdminIconPreview, useValidateAdminOpenAPISchema } from '@/hooks/use-admin-tool'
import { useAdminUploadImage } from '@/hooks/use-admin-upload-file'
import { useGetAdminBuiltinTools, useGetAdminCategories } from '@/hooks/use-admin-builtin-tool'
import {
  createAdminApiTool,
  deleteAdminApiTool,
  getAdminApiTool,
  listAdminApiTools,
  updateAdminApiTool,
} from '@/services/admin-tools'
import type { CreateApiToolProviderRequest, UpdateApiToolProviderRequest } from '@/models/api-tool'
import { getErrorMessage } from '@/utils/error'
import { formatTimestampShort } from '@/utils/time-formatter'
import IconUploadGenerator from '@/components/IconUploadGenerator.vue'
import ResourceCardDescription from '@/components/ResourceCardDescription.vue'
import CardGridSkeleton from '@/components/skeletons/CardGridSkeleton.vue'
import { getStoreCategoryDisplayName, getStoreTypeDisplayName } from '@/utils/store-display'

type ApiToolProviderListItem = {
  id: string
  name: string
  icon: string
  description: string
  headers: Array<{ key: string; value: string }>
  tools: Array<{ name: string; description: string }>
  creator_name: string
  creator_avatar: string
  updated_at: number
  created_at: number
}

type ApiToolProviderFormValues = {
  fileList: FileItem[]
  icon: string
  name: string
  openapi_schema: string
  headers: Array<{ key: string; value: string }>
}

type ToolPaginator = {
  total_record: number
  total_page: number
  current_page: number
  page_size: number
}

/**
 * 后台 API 工具管理页，负责 API Tool Provider 的创建、查看、编辑与删除，
 * 同时展示系统内置工具（只读）。
 */
const { t, locale } = useI18n()
const { image_url, handleUploadImage } = useAdminUploadImage()
const { handleValidateOpenAPISchema } = useValidateAdminOpenAPISchema()
const { loading: generateIconPreviewLoading, handleGenerateIconPreview } = useGenerateAdminIconPreview()

const activeTab = ref('api')

const loading = ref(false)
const saving = ref(false)
const providers = ref<ApiToolProviderListItem[]>([])
const search_word = ref('')
const paginator = ref<ToolPaginator>({
  total_record: 0,
  total_page: 0,
  current_page: 1,
  page_size: 20,
})

const showCreateModal = ref(false)
const showUpdateModal = ref(false)
const editingProviderId = ref('')
const formRef = ref<InstanceType<typeof Form>>()
const form = ref<ApiToolProviderFormValues>({
  fileList: [],
  icon: '',
  name: '',
  openapi_schema: '',
  headers: [],
})

const hasActiveFilters = computed(() => Boolean(search_word.value.trim()))
const emptyDescription = computed(() => {
  return hasActiveFilters.value ? t('admin.toolsAdmin.emptyFiltered') : t('admin.toolsAdmin.empty')
})

// ---- 内置工具 ----
const { loading: builtinLoading, builtin_tools, loadBuiltinTools } = useGetAdminBuiltinTools()
const { categories, loadCategories } = useGetAdminCategories()
const builtin_category = ref<string>('all')
const builtin_search_word = ref<string>('')
const showBuiltinDrawer = ref(false)
const activeBuiltinIdx = ref(-1)

const filteredBuiltinTools = computed(() => {
  return builtin_tools.value.filter((item: any) => {
    const matchCategory =
      builtin_category.value === 'all' || item.category === builtin_category.value
    const matchSearch =
      builtin_search_word.value === '' ||
      (item.label || '').toLowerCase().includes(builtin_search_word.value.toLowerCase())
    return matchCategory && matchSearch
  })
})

const getCategoryLabel = (value: string) => {
  return getStoreCategoryDisplayName(value, locale.value as 'zh-CN' | 'en-US')
}

const getTypeLabel = (value: string) => {
  return getStoreTypeDisplayName(value, locale.value as 'zh-CN' | 'en-US')
}

const openBuiltinDrawer = (idx: number) => {
  activeBuiltinIdx.value = idx
  showBuiltinDrawer.value = true
}

const closeBuiltinDrawer = () => {
  activeBuiltinIdx.value = -1
  showBuiltinDrawer.value = false
}

// ---- 头像渐变兜底 ----
const avatarPalettes = [
  ['#334155', '#0f172a'],
  ['#0369a1', '#1d4ed8'],
  ['#047857', '#0f766e'],
  ['#c2410c', '#d97706'],
  ['#be123c', '#e11d48'],
  ['#0f766e', '#14b8a6'],
  ['#7c3aed', '#a855f7'],
  ['#b45309', '#f59e0b'],
]

const hashString = (value: string) => {
  let hash = 0
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 33 + value.charCodeAt(i)) >>> 0
  }
  return hash
}

const extractAvatarText = (source: string) => {
  const text = (source || 'T').trim()
  const latinParts = text.match(/[A-Za-z0-9]+/g)
  if (latinParts && latinParts.length > 0) {
    return latinParts
      .slice(0, 2)
      .map((item) => item[0]?.toUpperCase())
      .join('')
  }
  const chineseParts = text.match(/[\u4e00-\u9fff]/g)
  if (chineseParts && chineseParts.length > 0) {
    return chineseParts.slice(0, 2).join('')
  }
  return text.slice(0, 2).toUpperCase()
}

const getApiToolAvatarText = (provider: ApiToolProviderListItem) => {
  return extractAvatarText(provider.name || 'T')
}

const getApiToolAvatarStyle = (provider: ApiToolProviderListItem) => {
  const palette =
    avatarPalettes[hashString(`${provider.id}:${provider.name}`) % avatarPalettes.length]
  return {
    background: `linear-gradient(135deg, ${palette[0]} 0%, ${palette[1]} 100%)`,
    boxShadow: 'inset 0 1px 0 rgba(255, 255, 255, 0.15)',
  }
}

const getBuiltinAvatarText = (tool: any) => {
  return extractAvatarText(tool.label || tool.name || 'B')
}

const getBuiltinAvatarStyle = (tool: any) => {
  const palette = avatarPalettes[hashString(`${tool.name}:${tool.label}`) % avatarPalettes.length]
  return {
    background: `linear-gradient(135deg, ${palette[0]} 0%, ${palette[1]} 100%)`,
    boxShadow: 'inset 0 1px 0 rgba(255, 255, 255, 0.15)',
  }
}

// ---- API 工具加载与分页 ----
const loadProviders = async () => {
  loading.value = true
  try {
    const data = await listAdminApiTools({
      current_page: paginator.value.current_page,
      page_size: paginator.value.page_size,
      search_word: search_word.value.trim(),
    })
    providers.value = (data.list as ApiToolProviderListItem[]) || []
    paginator.value = data.paginator
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.toolsAdmin.loadFailed')))
  } finally {
    loading.value = false
  }
}

const handleSearch = async () => {
  paginator.value.current_page = 1
  await loadProviders()
}

const handlePageChange = (page: number) => {
  paginator.value.current_page = page
  void loadProviders()
}

const handlePageSizeChange = (size: number) => {
  paginator.value.page_size = size
  paginator.value.current_page = 1
  void loadProviders()
}

const resetForm = () => {
  formRef.value?.resetFields()
  form.value = { fileList: [], icon: '', name: '', openapi_schema: '', headers: [] }
  editingProviderId.value = ''
}

const openCreateModal = () => {
  resetForm()
  showCreateModal.value = true
}

const openEditModal = async (record: ApiToolProviderListItem) => {
  resetForm()
  editingProviderId.value = record.id
  try {
    const detail = await getAdminApiTool(record.id)
    form.value.icon = detail.icon || ''
    form.value.fileList = detail.icon
      ? [{ uid: '1', name: t('space.tools.iconPlaceholder'), url: detail.icon }]
      : []
    form.value.name = detail.name || ''
    form.value.openapi_schema = detail.openapi_schema || ''
    form.value.headers = (detail.headers || []).map((h: { key: string; value: string }) => ({
      key: h.key,
      value: h.value,
    }))
    showUpdateModal.value = true
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.toolsAdmin.loadFailed')))
  }
}

const handleUploadIcon = async (file: File) => {
  await handleUploadImage(file)
  form.value.icon = image_url.value
  form.value.fileList = [{ uid: '1', name: t('space.tools.iconPlaceholder'), url: image_url.value }]
  Message.success(t('space.tools.iconUploadSuccess'))
}

const handleGenerateIcon = async () => {
  if (!form.value.name || form.value.name.trim() === '') {
    Message.warning(t('space.tools.enterNameFirst'))
    return
  }
  try {
    const iconUrl = await handleGenerateIconPreview(form.value.name, '')
    if (iconUrl) {
      form.value.icon = iconUrl
      form.value.fileList = [
        { uid: '1', name: t('space.tools.iconPlaceholder'), url: iconUrl },
      ]
      Message.success(t('space.tools.iconGenerateSuccess'))
    }
  } catch {
    // 错误已在 hook 中处理
  }
}

const handleValidateSchemaBlur = async () => {
  const schema = form.value.openapi_schema.trim()
  if (!schema) return
  try {
    await handleValidateOpenAPISchema(schema)
  } catch {
    // 校验失败提示由 hook 处理
  }
}

const handleModalCancel = () => {
  showCreateModal.value = false
  showUpdateModal.value = false
  resetForm()
}

const handleSubmit = async ({
  values,
  errors,
}: {
  values: ApiToolProviderFormValues
  errors: Record<string, ValidatedError> | undefined
}) => {
  if (errors) return
  saving.value = true
  try {
    if (showUpdateModal.value && editingProviderId.value) {
      await updateAdminApiTool(
        editingProviderId.value,
        values as UpdateApiToolProviderRequest,
      )
      Message.success(t('admin.toolsAdmin.updateSuccess'))
    } else {
      await createAdminApiTool(values as CreateApiToolProviderRequest)
      Message.success(t('admin.toolsAdmin.createSuccess'))
    }
    handleModalCancel()
    await loadProviders()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.toolsAdmin.saveFailed')))
  } finally {
    saving.value = false
  }
}

const handleDelete = (record: ApiToolProviderListItem) => {
  Modal.warning({
    title: t('admin.toolsAdmin.deleteTitle'),
    content: t('admin.toolsAdmin.deleteContent'),
    hideCancel: false,
    onOk: async () => {
      try {
        await deleteAdminApiTool(record.id)
        Message.success(t('admin.toolsAdmin.deleteSuccess'))
      } catch (error) {
        Message.error(getErrorMessage(error, t('admin.toolsAdmin.deleteFailed')))
      } finally {
        void loadProviders()
      }
    },
  })
}

onMounted(() => {
  void loadProviders()
  loadCategories()
  loadBuiltinTools()
})
</script>

<template>
  <section class="space-y-6">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold text-slate-900">{{ t('admin.toolsAdmin.title') }}</h1>
        <p class="mt-1 text-sm text-slate-500">{{ t('admin.toolsAdmin.description') }}</p>
      </div>
      <a href="/admin/tool-governance" class="text-sm font-semibold text-blue-600 hover:underline">
        {{ t('admin.toolsAdmin.governanceLink') }}
      </a>
    </header>

    <a-tabs v-model:active-key="activeTab" type="rounded" animation>
      <!-- ============ Tab 1: API 工具 ============ -->
      <a-tab-pane key="api" :title="t('admin.toolsAdmin.tabApi')">
        <section class="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 mb-4">
          <a-input
            v-model="search_word"
            class="max-w-xl flex-1 min-w-[260px]"
            :placeholder="t('admin.toolsAdmin.searchPlaceholder')"
            allow-clear
            @press-enter="handleSearch"
          />
          <a-button type="primary" :loading="loading" @click="handleSearch">
            {{ t('common.actions.search') }}
          </a-button>
          <a-button :loading="loading" @click="loadProviders">
            {{ t('common.actions.refresh') }}
          </a-button>
          <a-button type="primary" status="success" @click="openCreateModal">
            <template #icon>
              <icon-plus />
            </template>
            {{ t('admin.toolsAdmin.createButton') }}
          </a-button>
        </section>

        <card-grid-skeleton v-if="loading && providers.length === 0" :count="8" />
        <section v-else class="rounded-xl">
          <a-row :gutter="[16, 16]">
            <a-col
              v-for="record in providers"
              :key="record.id"
              :xs="24"
              :sm="12"
              :md="8"
              :lg="6"
              :xl="6"
            >
              <a-card
                hoverable
                class="rounded-lg h-full overflow-hidden"
                :body-style="{ padding: '12px' }"
              >
                <div class="flex items-start gap-2.5 mb-2">
                  <a-avatar
                    :size="36"
                    shape="square"
                    class="shrink-0 overflow-hidden"
                    :style="record.icon ? { backgroundColor: '#f3f4f6' } : getApiToolAvatarStyle(record)"
                  >
                    <img
                      v-if="record.icon"
                      :src="record.icon"
                      :alt="record.name"
                      class="w-full h-full object-cover"
                    />
                    <span v-else class="text-white font-semibold text-[12px] tracking-wide">
                      {{ getApiToolAvatarText(record) }}
                    </span>
                  </a-avatar>
                  <div class="flex-1 min-w-0">
                    <div class="text-sm font-bold text-gray-900 truncate">{{ record.name }}</div>
                    <div class="text-[11px] text-gray-500 line-clamp-1">
                      {{ t('admin.toolsAdmin.toolCountLabel', { count: (record.tools && record.tools.length) || 0 }) }}
                    </div>
                  </div>
                </div>

                <resource-card-description :text="record.description" />

                <div class="flex items-center justify-between mt-2.5">
                  <div class="text-[11px] text-gray-400">
                    {{ formatTimestampShort(record.created_at) }}
                  </div>
                  <a-space :size="4">
                    <a-button type="text" size="mini" @click.stop="openEditModal(record)">
                      {{ t('admin.toolsAdmin.editButton') }}
                    </a-button>
                    <a-button
                      type="text"
                      status="danger"
                      size="mini"
                      @click.stop="handleDelete(record)"
                    >
                      {{ t('admin.toolsAdmin.deleteButton') }}
                    </a-button>
                  </a-space>
                </div>
              </a-card>
            </a-col>

            <a-col v-if="!providers.length" :span="24">
              <a-empty :description="emptyDescription" class="py-16" />
            </a-col>
          </a-row>
        </section>

        <footer class="flex items-center justify-between mt-4">
          <span class="text-xs text-slate-400">
            {{ t('admin.toolsAdmin.total', { count: paginator.total_record }) }}
          </span>
          <a-pagination
            :total="paginator.total_record"
            :current="paginator.current_page"
            :page-size="paginator.page_size"
            show-total
            show-page-size
            @change="handlePageChange"
            @page-size-change="handlePageSizeChange"
          />
        </footer>
      </a-tab-pane>

      <!-- ============ Tab 2: 内置工具 ============ -->
      <a-tab-pane key="builtin" :title="t('admin.toolsAdmin.tabBuiltin')">
        <section class="flex items-center justify-between mb-4 flex-wrap gap-2 rounded-xl border border-slate-200 bg-white p-4">
          <div class="flex items-center gap-2 flex-wrap">
            <a-button
              :type="builtin_category === 'all' ? 'secondary' : 'text'"
              class="rounded-lg !text-gray-700 px-3"
              @click="builtin_category = 'all'"
            >
              {{ t('store.tools.all') }}
            </a-button>
            <a-button
              v-for="item in categories"
              :key="item.category"
              :type="builtin_category === item.category ? 'secondary' : 'text'"
              class="rounded-lg !text-gray-700 px-3"
              @click="builtin_category = item.category"
            >
              {{ getCategoryLabel(item.category || item.name) }}
            </a-button>
          </div>
          <a-input-search
            v-model="builtin_search_word"
            :placeholder="t('store.tools.searchPlaceholder')"
            class="w-full sm:w-[240px] bg-white rounded-lg border-gray-300"
          />
        </section>

        <card-grid-skeleton v-if="builtinLoading && builtin_tools.length === 0" :count="8" />
        <section v-else class="rounded-xl">
          <a-row :gutter="[16, 16]">
            <a-col
              v-for="(builtinTool, idx) in filteredBuiltinTools"
              :key="builtinTool.name"
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
                @click="openBuiltinDrawer(idx)"
              >
                <div class="flex items-start gap-2.5 mb-2">
                  <a-avatar
                    :size="36"
                    shape="square"
                    class="shrink-0 overflow-hidden relative"
                    :style="getBuiltinAvatarStyle(builtinTool)"
                  >
                    <span class="text-white font-semibold text-[12px] tracking-wide">{{ getBuiltinAvatarText(builtinTool) }}</span>
                    <img
                      :src="`${apiPrefix}/builtin-tools/${builtinTool.name}/icon`"
                      :alt="builtinTool.name"
                      class="absolute inset-0 w-full h-full object-contain"
                      @error="(e: Event) => (e.target as HTMLElement).style.display = 'none'"
                    />
                  </a-avatar>
                  <div class="flex-1 min-w-0">
                    <div class="text-sm font-bold text-gray-900 truncate">{{ builtinTool.label }}</div>
                    <div class="text-[11px] text-gray-500 line-clamp-1">
                      {{ t('store.tools.providerSummary', { name: builtinTool.name, count: builtinTool.tools.length }) }}
                    </div>
                  </div>
                </div>

                <resource-card-description :text="builtinTool.description" />

                <div class="flex items-center gap-1.5 flex-wrap mt-2.5">
                  <a-tag v-if="builtinTool.category" size="small" color="gray">
                    {{ getCategoryLabel(builtinTool.category) }}
                  </a-tag>
                  <a-tag size="small" color="arcoblue">
                    {{ t('admin.toolsAdmin.toolCountLabel', { count: builtinTool.tools.length }) }}
                  </a-tag>
                </div>

                <div class="flex items-center gap-1.5 mt-2.5">
                  <a-avatar :size="16" class="bg-blue-700">
                    <icon-user />
                  </a-avatar>
                  <div class="text-[11px] text-gray-400">
                    {{ t('store.tools.publishedAt', { time: formatTimestampShort(builtinTool.created_at) }) }}
                  </div>
                </div>
              </a-card>
            </a-col>

            <a-col v-if="filteredBuiltinTools.length === 0" :span="24">
              <a-empty :description="t('store.tools.empty')" class="py-16" />
            </a-col>
          </a-row>
        </section>

        <footer class="text-xs text-slate-400 mt-4">
          {{ t('admin.toolsAdmin.builtinTotal', { count: builtin_tools.length }) }}
        </footer>

        <!-- 内置工具详情抽屉 -->
        <a-drawer
          :visible="showBuiltinDrawer"
          :width="380"
          :footer="false"
          :title="t('store.tools.detailTitle')"
          :drawer-style="{ background: '#F9FAFB' }"
          @cancel="closeBuiltinDrawer"
        >
          <div v-if="activeBuiltinIdx !== -1 && filteredBuiltinTools[activeBuiltinIdx]" class="flex flex-col gap-4">
            <div class="flex items-start gap-3">
              <a-avatar
                :size="40"
                shape="square"
                class="shrink-0 overflow-hidden relative"
                :style="getBuiltinAvatarStyle(filteredBuiltinTools[activeBuiltinIdx])"
              >
                <span class="text-white font-semibold text-[13px] tracking-wide">{{ getBuiltinAvatarText(filteredBuiltinTools[activeBuiltinIdx]) }}</span>
                <img
                  :src="`${apiPrefix}/builtin-tools/${filteredBuiltinTools[activeBuiltinIdx].name}/icon`"
                  :alt="filteredBuiltinTools[activeBuiltinIdx].name"
                  class="absolute inset-0 w-full h-full object-contain"
                  @error="(e: Event) => (e.target as HTMLElement).style.display = 'none'"
                />
              </a-avatar>
              <div class="flex flex-col">
                <div class="text-base text-gray-900 font-bold">
                  {{ filteredBuiltinTools[activeBuiltinIdx].label }}
                </div>
                <div class="text-xs text-gray-500 line-clamp-1">
                  {{ t('store.tools.providerSummary', { name: filteredBuiltinTools[activeBuiltinIdx].name, count: filteredBuiltinTools[activeBuiltinIdx].tools.length }) }}
                </div>
              </div>
            </div>

            <div class="leading-[18px] text-gray-500 text-sm">
              {{ filteredBuiltinTools[activeBuiltinIdx].description }}
            </div>

            <hr class="my-2" />

            <div class="flex flex-col gap-2">
              <div class="text-xs text-gray-500">
                {{ t('store.tools.containsTools', { count: filteredBuiltinTools[activeBuiltinIdx].tools.length }) }}
              </div>

              <a-card
                v-for="tool in filteredBuiltinTools[activeBuiltinIdx].tools"
                :key="tool.name"
                class="rounded-xl"
              >
                <div class="font-bold text-gray-900 mb-2">{{ tool.label }}</div>
                <div class="text-gray-500 text-xs">{{ tool.description }}</div>
                <div v-if="tool.inputs && tool.inputs.length > 0">
                  <div class="flex items-center gap-2 my-3">
                    <div class="text-xs font-bold text-gray-500">{{ t('store.tools.parameters') }}</div>
                    <hr class="flex-1" />
                  </div>
                  <div class="flex flex-col gap-3">
                    <div v-for="input in tool.inputs" :key="input.name" class="flex flex-col gap-1">
                      <div class="flex items-center gap-2 text-xs">
                        <div class="text-gray-900 font-bold">{{ input.name }}</div>
                        <div class="text-gray-500">{{ getTypeLabel(input.type) }}</div>
                        <div v-if="input.required" class="text-red-700">{{ t('store.tools.required') }}</div>
                      </div>
                      <div class="text-xs text-gray-500">{{ input.description }}</div>
                    </div>
                  </div>
                </div>
              </a-card>
            </div>
          </div>
        </a-drawer>
      </a-tab-pane>
    </a-tabs>

    <!-- 创建/编辑模态窗 -->
    <a-modal
      :width="630"
      :visible="showCreateModal || showUpdateModal"
      hide-title
      :footer="false"
      modal-class="rounded-xl"
      @cancel="handleModalCancel"
    >
      <div class="flex items-center justify-between">
        <div class="text-lg font-bold text-gray-700">
          {{ showUpdateModal ? t('space.tools.updateTitle') : t('space.tools.createTitle') }}
        </div>
        <a-button type="text" class="!text-gray-700" size="small" @click="handleModalCancel">
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>

      <div class="pt-6">
        <a-form ref="formRef" :model="form" layout="vertical" @submit="handleSubmit">
          <a-form-item
            field="fileList"
            hide-label
            :rules="[{ required: true, message: t('space.tools.iconRequired') }]"
          >
            <IconUploadGenerator
              :name="form.name"
              description=""
              :icon="form.icon"
              :file-list="form.fileList"
              :loading="generateIconPreviewLoading"
              :placeholder="t('space.tools.iconPlaceholder')"
              :on-upload="handleUploadIcon"
              :on-generate="handleGenerateIcon"
              @update:icon="(val: string) => (form.icon = val)"
              @update:fileList="(val: FileItem[]) => (form.fileList = val)"
            />
          </a-form-item>

          <a-form-item
            field="name"
            :label="t('space.tools.pluginName')"
            asterisk-position="end"
            :rules="[{ required: true, message: t('space.tools.pluginNameRequired') }]"
          >
            <a-input
              v-model="form.name"
              :placeholder="t('space.tools.pluginNamePlaceholder')"
              show-word-limit
              :max-length="60"
            />
          </a-form-item>

          <a-form-item
            field="openapi_schema"
            label="OpenAPI Schema"
            asterisk-position="end"
            :rules="[{ required: true, message: t('space.tools.openapiSchemaRequired') }]"
          >
            <div class="w-full flex flex-col gap-3">
              <div class="rounded-lg border border-gray-200 p-3">
                <a-textarea
                  v-model="form.openapi_schema"
                  :auto-size="{ minRows: 12, maxRows: 24 }"
                  :placeholder="t('space.tools.openapiSchemaPlaceholder')"
                  @blur="handleValidateSchemaBlur"
                />
              </div>

              <div class="rounded-lg border border-gray-200 w-full overflow-x-auto">
                <table class="w-full leading-[18px] text-xs text-gray-700 font-normal">
                  <thead class="text-gray-500">
                    <tr class="border-b border-gray-200">
                      <th class="p-2 pl-3 font-medium">{{ t('space.tools.columns.key') }}</th>
                      <th class="p-2 pl-3 font-medium">{{ t('space.tools.columns.value') }}</th>
                      <th class="p-2 pl-3 font-medium w-[50px]">
                        {{ t('space.tools.columns.action') }}
                      </th>
                    </tr>
                  </thead>
                  <tbody v-if="form.headers.length > 0" class="border-b border-gray-200">
                    <tr
                      v-for="(header, idx) in form.headers"
                      :key="idx"
                      class="border-b last:border-0 border-gray-200"
                    >
                      <td class="p-2 pl-3">
                        <a-input v-model="header.key" :placeholder="t('space.tools.headerKeyPlaceholder')" />
                      </td>
                      <td class="p-2 pl-3">
                        <a-input
                          v-model="header.value"
                          :placeholder="t('space.tools.headerValuePlaceholder')"
                        />
                      </td>
                      <td class="p-2 pl-3">
                        <a-button
                          size="mini"
                          type="text"
                          class="!text-gray-700"
                          @click="form.headers.splice(idx, 1)"
                        >
                          <template #icon>
                            <icon-delete />
                          </template>
                        </a-button>
                      </td>
                    </tr>
                  </tbody>
                </table>
                <a-button
                  size="mini"
                  class="rounded ml-3 mb-3 !text-gray-700"
                  @click="form.headers.push({ key: '', value: '' })"
                >
                  <template #icon>
                    <icon-plus />
                  </template>
                  {{ t('space.tools.addHeader') }}
                </a-button>
              </div>
            </div>
          </a-form-item>

          <div class="flex items-center justify-end gap-4">
            <a-button class="rounded-lg" @click="handleModalCancel">
              {{ t('common.actions.cancel') }}
            </a-button>
            <a-button
              :loading="saving"
              type="primary"
              html-type="submit"
              class="rounded-lg"
            >
              {{ t('common.actions.save') }}
            </a-button>
          </div>
        </a-form>
      </div>
    </a-modal>
  </section>
</template>
