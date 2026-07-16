<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  createModelProvider,
  deleteModelProvider,
  listModelProviders,
  setModelProviderStatus,
  updateModelProvider,
} from '@/services/admin-model-providers'
import { getErrorMessage } from '@/utils/error'

type ProviderRecord = {
  id: string
  name: string
  label: string
  description?: string
  icon?: string
  background?: string
  default_base_url: string
  supported_model_types: string[]
  model_count: number
  status: string
  created_at?: number
  updated_at?: number
}

const { t } = useI18n()

const ALL_MODEL_TYPES = [
  'chat', 'completion', 'embedding', 'multimodal',
  'image_generation', 'video_generation', 'ocr', 'tts', 'asr', 'rerank',
]

const loading = ref(false)
const actionLoading = ref(false)
const providers = ref<ProviderRecord[]>([])

const search = ref('')
const statusFilter = ref('')

const stats = computed(() => ({
  total: providers.value.length,
  active: providers.value.filter((item) => item.status === 'active').length,
  disabled: providers.value.filter((item) => item.status === 'disabled').length,
}))

const filteredProviders = computed(() => {
  let list = providers.value
  if (search.value.trim()) {
    const keyword = search.value.trim().toLowerCase()
    list = list.filter((p) =>
      p.name.toLowerCase().includes(keyword)
      || (p.label || '').toLowerCase().includes(keyword)
      || (p.default_base_url || '').toLowerCase().includes(keyword),
    )
  }
  if (statusFilter.value) {
    list = list.filter((p) => p.status === statusFilter.value)
  }
  return list
})

const modalVisible = ref(false)
const editMode = ref(false)
const editingId = ref('')
const form = ref({
  name: '',
  label: '',
  description: '',
  default_base_url: '',
  supported_model_types: [] as string[],
  status: 'active',
})

const loadAll = async () => {
  loading.value = true
  try {
    const params: Record<string, unknown> = { current_page: 1, page_size: 200 }
    if (search.value.trim()) params.search = search.value.trim()
    if (statusFilter.value) params.status = statusFilter.value
    const result = await listModelProviders(params) as { data?: { list?: ProviderRecord[] } }
    providers.value = result.data?.list || []
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.modelProviders.loadFailed')))
  } finally {
    loading.value = false
  }
}

const resetForm = () => {
  form.value = {
    name: '',
    label: '',
    description: '',
    default_base_url: '',
    supported_model_types: [],
    status: 'active',
  }
}

const openCreate = () => {
  editMode.value = false
  editingId.value = ''
  resetForm()
  modalVisible.value = true
}

const openEdit = (provider: ProviderRecord) => {
  editMode.value = true
  editingId.value = provider.id
  form.value = {
    name: provider.name,
    label: provider.label || '',
    description: provider.description || '',
    default_base_url: provider.default_base_url || '',
    supported_model_types: [...(provider.supported_model_types || [])],
    status: provider.status || 'active',
  }
  modalVisible.value = true
}

const submitProvider = async () => {
  if (!form.value.name.trim()) {
    Message.error(t('admin.modelProviders.nameRequired'))
    return
  }
  if (!form.value.label.trim()) {
    Message.error(t('admin.modelProviders.labelRequired'))
    return
  }
  if (!form.value.default_base_url.trim()) {
    Message.error(t('admin.modelProviders.baseUrlRequired'))
    return
  }
  actionLoading.value = true
  try {
    if (editMode.value) {
      await updateModelProvider(editingId.value, { ...form.value })
      Message.success(t('admin.modelProviders.updateSuccess'))
    } else {
      await createModelProvider({ ...form.value })
      Message.success(t('admin.modelProviders.createSuccess'))
    }
    modalVisible.value = false
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.modelProviders.updateSuccess')))
  } finally {
    actionLoading.value = false
  }
}

const toggleStatus = async (provider: ProviderRecord, enabled: boolean) => {
  actionLoading.value = true
  try {
    await setModelProviderStatus(provider.id, enabled ? 'active' : 'disabled')
    Message.success(t('admin.modelProviders.statusUpdateSuccess'))
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.modelProviders.statusUpdateSuccess')))
  } finally {
    actionLoading.value = false
  }
}

const removeProvider = (provider: ProviderRecord) => {
  Modal.warning({
    title: t('admin.modelProviders.delete'),
    content: t('admin.modelProviders.deleteConfirm'),
    hideCancel: false,
    onOk: async () => {
      actionLoading.value = true
      try {
        await deleteModelProvider(provider.id)
        Message.success(t('admin.modelProviders.deleteSuccess'))
        await loadAll()
      } catch (error) {
        Message.error(getErrorMessage(error, t('admin.modelProviders.hasModelsConflict')))
      } finally {
        actionLoading.value = false
      }
    },
  })
}

onMounted(loadAll)
</script>

<template>
  <section class="space-y-6 p-6">
    <header>
      <h1 class="text-2xl font-semibold text-gray-900">{{ t('admin.modelProviders.title') }}</h1>
      <p class="mt-1 text-sm text-gray-500">{{ t('admin.modelProviders.pageDescription') }}</p>
    </header>

    <div class="grid gap-4 md:grid-cols-3">
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.modelProviders.modelCount') }}</p>
        <strong class="text-xl">{{ stats.total }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.modelProviders.active') }}</p>
        <strong class="text-xl">{{ stats.active }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.modelProviders.disabled') }}</p>
        <strong class="text-xl">{{ stats.disabled }}</strong>
      </article>
    </div>

    <div class="flex flex-wrap items-center gap-3">
      <a-input
        v-model="search"
        :placeholder="t('admin.modelProviders.name')"
        allow-clear
        style="width: 240px"
        @press-enter="loadAll"
        @clear="loadAll"
      />
      <a-select
        v-model="statusFilter"
        :placeholder="t('admin.modelProviders.status')"
        allow-clear
        style="width: 160px"
        @change="loadAll"
      >
        <a-option value="active">{{ t('admin.modelProviders.active') }}</a-option>
        <a-option value="disabled">{{ t('admin.modelProviders.disabled') }}</a-option>
      </a-select>
      <a-button @click="loadAll">{{ t('admin.modelProviders.actions') }}</a-button>
      <div class="flex-1" />
      <a-button type="primary" @click="openCreate">{{ t('admin.modelProviders.create') }}</a-button>
    </div>

    <a-spin :loading="loading" class="block">
      <div class="overflow-hidden rounded-lg border bg-white">
        <table class="w-full text-left text-sm">
          <thead class="bg-gray-50 text-gray-500">
            <tr>
              <th class="p-3">{{ t('admin.modelProviders.name') }}</th>
              <th class="p-3">{{ t('admin.modelProviders.label') }}</th>
              <th class="p-3">{{ t('admin.modelProviders.defaultBaseUrl') }}</th>
              <th class="p-3">{{ t('admin.modelProviders.supportedModelTypes') }}</th>
              <th class="p-3">{{ t('admin.modelProviders.modelCount') }}</th>
              <th class="p-3">{{ t('admin.modelProviders.status') }}</th>
              <th class="p-3">{{ t('admin.modelProviders.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!filteredProviders.length">
              <td class="p-6 text-center text-gray-400" colspan="7">{{ t('admin.modelProviders.empty') }}</td>
            </tr>
            <tr v-for="provider in filteredProviders" :key="provider.id" class="border-t">
              <td class="p-3 font-mono">{{ provider.name }}</td>
              <td class="p-3">{{ provider.label || '-' }}</td>
              <td class="p-3 font-mono text-xs">{{ provider.default_base_url || '-' }}</td>
              <td class="p-3">
                <a-tag v-for="mt in provider.supported_model_types" :key="mt" size="small" color="arcoblue">{{ mt }}</a-tag>
                <span v-if="!provider.supported_model_types?.length" class="text-gray-400">-</span>
              </td>
              <td class="p-3">{{ provider.model_count ?? 0 }}</td>
              <td class="p-3">
                <a-switch
                  :model-value="provider.status === 'active'"
                  :loading="actionLoading"
                  @change="(v: string | number | boolean) => toggleStatus(provider, Boolean(v))"
                />
              </td>
              <td class="p-3">
                <a-space>
                  <a-button size="mini" @click="openEdit(provider)">{{ t('admin.modelProviders.edit') }}</a-button>
                  <a-button size="mini" status="danger" @click="removeProvider(provider)">{{ t('admin.modelProviders.delete') }}</a-button>
                </a-space>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </a-spin>

    <a-modal
      v-model:visible="modalVisible"
      :title="editMode ? t('admin.modelProviders.edit') : t('admin.modelProviders.create')"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submitProvider"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item :label="t('admin.modelProviders.name')" field="name">
          <a-input v-model="form.name" :disabled="editMode" :placeholder="t('admin.modelProviders.name')" />
        </a-form-item>
        <a-form-item :label="t('admin.modelProviders.label')" field="label">
          <a-input v-model="form.label" :placeholder="t('admin.modelProviders.label')" />
        </a-form-item>
        <a-form-item :label="t('admin.modelProviders.defaultBaseUrl')" field="default_base_url">
          <a-input v-model="form.default_base_url" placeholder="https://api.openai.com/v1" />
        </a-form-item>
        <a-form-item :label="t('admin.modelProviders.description')" field="description">
          <a-textarea v-model="form.description" :placeholder="t('admin.modelProviders.description')" :auto-size="{ minRows: 2, maxRows: 4 }" />
        </a-form-item>
        <a-form-item :label="t('admin.modelProviders.supportedModelTypes')" field="supported_model_types">
          <a-select v-model="form.supported_model_types" multiple allow-search :placeholder="t('admin.modelProviders.supportedModelTypes')">
            <a-option v-for="mt in ALL_MODEL_TYPES" :key="mt" :value="mt">{{ mt }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.modelProviders.status')" field="status">
          <a-select v-model="form.status">
            <a-option value="active">{{ t('admin.modelProviders.active') }}</a-option>
            <a-option value="disabled">{{ t('admin.modelProviders.disabled') }}</a-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
