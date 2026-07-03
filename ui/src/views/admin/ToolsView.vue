<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message, type FileItem, type ValidatedError, Form } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  useCreateApiToolProvider,
  useDeleteApiToolProvider,
  useGenerateIconPreview,
  useGetApiToolProvider,
  useUpdateApiToolProvider,
  useValidateOpenAPISchema,
} from '@/hooks/use-tool'
import { useUploadImage } from '@/hooks/use-upload-file'
import { getApiToolProvidersWithPage } from '@/services/api-tool'
import type { CreateApiToolProviderRequest } from '@/models/api-tool'
import { getErrorMessage } from '@/utils/error'
import { formatTimestampShort } from '@/utils/time-formatter'
import IconUploadGenerator from '@/components/IconUploadGenerator.vue'

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
 * 后台 API 工具管理页，负责 API Tool Provider 的创建、查看、编辑与删除。
 */
const { t } = useI18n()
const { image_url, handleUploadImage } = useUploadImage()
const { api_tool_provider, loadApiToolProvider } = useGetApiToolProvider()
const { handleDelete: handleDeleteApiToolProvider } = useDeleteApiToolProvider()
const { loading: updateApiToolProviderLoading, handleUpdateApiToolProvider } =
  useUpdateApiToolProvider()
const { loading: createApiToolProviderLoading, handleCreateApiToolProvider } =
  useCreateApiToolProvider()
const { handleValidateOpenAPISchema } = useValidateOpenAPISchema()
const { loading: generateIconPreviewLoading, handleGenerateIconPreview } = useGenerateIconPreview()

const loading = ref(false)
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

const tableColumns = computed(() => [
  { title: t('admin.toolsAdmin.columns.name'), dataIndex: 'name', slotName: 'name', width: 220 },
  {
    title: t('admin.toolsAdmin.columns.description'),
    dataIndex: 'description',
    ellipsis: true,
    tooltip: true,
  },
  { title: t('admin.toolsAdmin.columns.schemaStatus'), slotName: 'schemaStatus', width: 140 },
  { title: t('admin.toolsAdmin.columns.toolCount'), slotName: 'toolCount', width: 100 },
  { title: t('admin.toolsAdmin.columns.createdAt'), slotName: 'createdAt', width: 140 },
  {
    title: t('admin.toolsAdmin.columns.actions'),
    slotName: 'actions',
    width: 140,
    fixed: 'right' as const,
  },
])

const hasActiveFilters = computed(() => Boolean(search_word.value.trim()))
const emptyDescription = computed(() => {
  return hasActiveFilters.value ? t('admin.toolsAdmin.emptyFiltered') : t('admin.toolsAdmin.empty')
})

/**
 * 拉取 API Tool Provider 分页列表。
 */
const loadProviders = async () => {
  loading.value = true
  try {
    const resp = await getApiToolProvidersWithPage(
      paginator.value.current_page,
      paginator.value.page_size,
      search_word.value.trim(),
    )
    providers.value = (resp.data.list as ApiToolProviderListItem[]) || []
    paginator.value = resp.data.paginator
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.toolsAdmin.loadFailed')))
  } finally {
    loading.value = false
  }
}

/**
 * 触发搜索并重置到第一页。
 */
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

/**
 * 打开编辑模态窗，先拉取 provider 详情填充表单。
 */
const openEditModal = async (record: ApiToolProviderListItem) => {
  resetForm()
  editingProviderId.value = record.id
  await loadApiToolProvider(record.id)
  const detail = api_tool_provider.value as {
    icon: string
    name: string
    openapi_schema: string
    headers: Array<{ key: string; value: string }>
  }
  form.value.icon = detail.icon || ''
  form.value.fileList = detail.icon
    ? [{ uid: '1', name: t('space.tools.iconPlaceholder'), url: detail.icon }]
    : []
  form.value.name = detail.name || ''
  form.value.openapi_schema = detail.openapi_schema || ''
  form.value.headers = (detail.headers || []).map((h) => ({ key: h.key, value: h.value }))
  showUpdateModal.value = true
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
  if (showUpdateModal.value && editingProviderId.value) {
    await handleUpdateApiToolProvider(
      editingProviderId.value,
      values as CreateApiToolProviderRequest,
    )
  } else {
    await handleCreateApiToolProvider(values as CreateApiToolProviderRequest)
  }
  handleModalCancel()
  await loadProviders()
}

const handleDelete = (record: ApiToolProviderListItem) => {
  handleDeleteApiToolProvider(record.id, () => {
    void loadProviders()
  })
}

onMounted(() => {
  void loadProviders()
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

    <section class="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4">
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

    <section class="rounded-xl border border-slate-200 bg-white">
      <a-table
        :columns="tableColumns"
        :data="providers"
        :loading="loading"
        :pagination="{
          total: paginator.total_record,
          current: paginator.current_page,
          pageSize: paginator.page_size,
          showTotal: true,
          showPageSize: true,
        }"
        row-key="id"
        :scroll="{ x: 960 }"
        @page-change="handlePageChange"
        @page-size-change="handlePageSizeChange"
      >
        <template #name="{ record }">
          <div class="flex items-center gap-2">
            <a-avatar :size="32" shape="square" :image-url="record.icon" />
            <span class="font-medium text-slate-900">{{ record.name }}</span>
          </div>
        </template>
        <template #schemaStatus="{ record }">
          <a-tag v-if="record.tools && record.tools.length" color="green" size="small">
            {{ t('admin.toolsAdmin.schemaParsed') }}
          </a-tag>
          <a-tag v-else color="gray" size="small">
            {{ t('admin.toolsAdmin.schemaEmpty') }}
          </a-tag>
        </template>
        <template #toolCount="{ record }">
          {{ (record.tools && record.tools.length) || 0 }}
        </template>
        <template #createdAt="{ record }">
          {{ formatTimestampShort(record.created_at) }}
        </template>
        <template #actions="{ record }">
          <a-space :size="8">
            <a-button type="text" size="small" @click="openEditModal(record)">
              {{ t('admin.toolsAdmin.editButton') }}
            </a-button>
            <a-button type="text" status="danger" size="small" @click="handleDelete(record)">
              {{ t('admin.toolsAdmin.deleteButton') }}
            </a-button>
          </a-space>
        </template>
      </a-table>
      <p
        v-if="!providers.length && !loading"
        class="px-6 py-12 text-center text-sm text-slate-500"
      >
        {{ emptyDescription }}
      </p>
    </section>

    <footer class="text-xs text-slate-400">
      {{ t('admin.toolsAdmin.total', { count: paginator.total_record }) }}
    </footer>

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
              :loading="createApiToolProviderLoading || updateApiToolProviderLoading"
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
