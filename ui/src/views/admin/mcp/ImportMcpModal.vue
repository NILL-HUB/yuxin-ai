<script setup lang="ts">
import { ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import {
  importAdminMcpJson,
  importAdminMcpJsonConfig,
  importAdminMcpUrl,
  previewAdminMcpUrl,
} from '@/services/admin-mcp'

const props = defineProps({
  visible: { type: Boolean, required: true },
  callback: { type: Function, required: false },
})

const emits = defineEmits(['update:visible'])
const { t } = useI18n()

const activeTab = ref<'mcpJson' | 'urlImport' | 'jsonConfig'>('mcpJson')
const hideModal = () => emits('update:visible', false)

// Tab 1
const mcpJsonText = ref('')
const mcpJsonOverwrite = ref(false)
// Tab 2
const urlValue = ref('')
const urlName = ref('')
const urlDescription = ref('')
const urlTransport = ref('http')
const urlCategory = ref('')
const urlIcon = ref('')
const urlHeaders = ref<Array<{ key: string; value: string }>>([{ key: '', value: '' }])
const urlPreviewLoading = ref(false)
const urlPreviewTools = ref<Array<{ name: string; label?: string; description?: string }>>([])
// Tab 3
const jsonConfigText = ref('')
const jsonConfigOverwrite = ref(false)

const loading = ref(false)

const transportOptions = [
  { label: 'http', value: 'http' },
  { label: 'sse', value: 'sse' },
  { label: 'streamable_http', value: 'streamable_http' },
]

const resetForm = () => {
  activeTab.value = 'mcpJson'
  mcpJsonText.value = ''
  mcpJsonOverwrite.value = false
  urlValue.value = ''
  urlName.value = ''
  urlDescription.value = ''
  urlTransport.value = 'http'
  urlCategory.value = ''
  urlIcon.value = ''
  urlHeaders.value = [{ key: '', value: '' }]
  urlPreviewTools.value = []
  jsonConfigText.value = ''
  jsonConfigOverwrite.value = false
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      resetForm()
    }
  },
)

const addHeader = () => {
  urlHeaders.value.push({ key: '', value: '' })
}

const removeHeader = (index: number) => {
  urlHeaders.value.splice(index, 1)
}

const getCleanHeaders = () => {
  return urlHeaders.value
    .filter((h) => h.key.trim().length > 0)
    .map((h) => ({ key: h.key.trim(), value: h.value }))
}

const handlePreviewUrl = async () => {
  if (!urlValue.value.trim()) {
    Message.warning(t('admin.mcpAdmin.importUrlRequired'))
    return
  }
  urlPreviewLoading.value = true
  urlPreviewTools.value = []
  try {
    const result = await previewAdminMcpUrl(urlValue.value.trim(), urlTransport.value, getCleanHeaders())
    urlPreviewTools.value = result.tools || []
    Message.success(t('admin.mcpAdmin.previewSuccess', { count: urlPreviewTools.value.length }))
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.mcpAdmin.previewFailed')))
  } finally {
    urlPreviewLoading.value = false
  }
}

const handleOk = async () => {
  if (activeTab.value === 'mcpJson') {
    if (!mcpJsonText.value.trim()) {
      Message.warning(t('admin.mcpAdmin.importJsonRequired'))
      return
    }
    try {
      JSON.parse(mcpJsonText.value)
    } catch {
      Message.error(t('admin.mcpAdmin.importJsonInvalid'))
      return
    }
    loading.value = true
    try {
      const result = await importAdminMcpJson(mcpJsonText.value, mcpJsonOverwrite.value)
      Message.success(
        t('admin.mcpAdmin.importResult', {
          imported: result.imported?.length || 0,
          skipped: result.skipped?.length || 0,
          failed: result.failed?.length || 0,
        }),
      )
      if (result.imported?.length && props.callback) {
        await props.callback()
      }
      hideModal()
    } catch (error) {
      Message.error(getErrorMessage(error, t('admin.mcpAdmin.importFailed')))
    } finally {
      loading.value = false
    }
  } else if (activeTab.value === 'urlImport') {
    if (!urlValue.value.trim()) {
      Message.warning(t('admin.mcpAdmin.importUrlRequired'))
      return
    }
    if (!urlName.value.trim()) {
      Message.warning(t('admin.mcpAdmin.importNameRequired'))
      return
    }
    loading.value = true
    try {
      await importAdminMcpUrl({
        url: urlValue.value.trim(),
        name: urlName.value.trim(),
        description: urlDescription.value.trim() || undefined,
        transport: urlTransport.value,
        headers: getCleanHeaders(),
        category: urlCategory.value.trim() || undefined,
        icon: urlIcon.value.trim() || undefined,
      })
      Message.success(t('admin.mcpAdmin.importSuccess'))
      if (props.callback) {
        await props.callback()
      }
      hideModal()
    } catch (error) {
      Message.error(getErrorMessage(error, t('admin.mcpAdmin.importFailed')))
    } finally {
      loading.value = false
    }
  } else if (activeTab.value === 'jsonConfig') {
    if (!jsonConfigText.value.trim()) {
      Message.warning(t('admin.mcpAdmin.importJsonRequired'))
      return
    }
    try {
      JSON.parse(jsonConfigText.value)
    } catch {
      Message.error(t('admin.mcpAdmin.importJsonInvalid'))
      return
    }
    loading.value = true
    try {
      const result = await importAdminMcpJsonConfig(jsonConfigText.value, jsonConfigOverwrite.value)
      Message.success(
        t('admin.mcpAdmin.importResult', {
          imported: result.imported?.length || 0,
          skipped: result.skipped?.length || 0,
          failed: result.failed?.length || 0,
        }),
      )
      if (result.imported?.length && props.callback) {
        await props.callback()
      }
      hideModal()
    } catch (error) {
      Message.error(getErrorMessage(error, t('admin.mcpAdmin.importFailed')))
    } finally {
      loading.value = false
    }
  }
}
</script>

<template>
  <a-modal
    :visible="visible"
    :width="680"
    :title="t('admin.mcpAdmin.importTitle')"
    :mask-closable="false"
    :ok-loading="loading || urlPreviewLoading"
    :ok-text="t('admin.mcpAdmin.importButton')"
    @cancel="hideModal"
    @ok="handleOk"
  >
    <a-radio-group v-model="activeTab" type="button" class="mb-4">
      <a-radio value="mcpJson">{{ t('admin.mcpAdmin.importTabMcpJson') }}</a-radio>
      <a-radio value="urlImport">{{ t('admin.mcpAdmin.importTabUrl') }}</a-radio>
      <a-radio value="jsonConfig">{{ t('admin.mcpAdmin.importTabJsonConfig') }}</a-radio>
    </a-radio-group>

    <div v-if="activeTab === 'mcpJson'" class="space-y-3">
      <div class="text-sm text-slate-700">{{ t('admin.mcpAdmin.importJsonLabel') }}</div>
      <a-textarea
        v-model="mcpJsonText"
        :auto-size="{ minRows: 8, maxRows: 18 }"
        :placeholder="t('admin.mcpAdmin.importMcpJsonPlaceholder')"
        allow-clear
      />
      <div class="flex items-center gap-2">
        <a-switch v-model="mcpJsonOverwrite" />
        <span class="text-sm text-slate-600">{{ t('admin.mcpAdmin.importOverwrite') }}</span>
      </div>
    </div>

    <div v-else-if="activeTab === 'urlImport'" class="space-y-3">
      <div>
        <div class="mb-1 text-sm text-slate-700">{{ t('admin.mcpAdmin.importUrlLabel') }}</div>
        <a-input v-model="urlValue" :placeholder="t('admin.mcpAdmin.importUrlPlaceholder')" allow-clear />
      </div>
      <div>
        <div class="mb-1 text-sm text-slate-700">{{ t('admin.mcpAdmin.formTransport') }}</div>
        <a-select v-model="urlTransport" :options="transportOptions" />
      </div>
      <div>
        <div class="mb-1 text-sm text-slate-700">{{ t('admin.mcpAdmin.importHeadersLabel') }}</div>
        <div class="space-y-2">
          <div
            v-for="(header, idx) in urlHeaders"
            :key="idx"
            class="flex items-center gap-2"
          >
            <a-input
              v-model="header.key"
              class="flex-1"
              :placeholder="t('admin.mcpAdmin.importHeaderKeyPlaceholder')"
              allow-clear
            />
            <a-input
              v-model="header.value"
              class="flex-1"
              :placeholder="t('admin.mcpAdmin.importHeaderValuePlaceholder')"
              allow-clear
            />
            <a-button
              v-if="urlHeaders.length > 1"
              status="danger"
              type="text"
              size="small"
              @click="removeHeader(idx)"
            >
              <template #icon>
                <icon-delete />
              </template>
            </a-button>
          </div>
          <a-button type="text" size="small" @click="addHeader">
            <template #icon>
              <icon-plus />
            </template>
            {{ t('admin.mcpAdmin.importHeaderAdd') }}
          </a-button>
        </div>
      </div>
      <div class="flex justify-end">
        <a-button :loading="urlPreviewLoading" @click="handlePreviewUrl">
          {{ t('admin.mcpAdmin.previewTools') }}
        </a-button>
      </div>
      <div v-if="urlPreviewTools.length > 0" class="rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div class="mb-2 text-xs font-semibold text-slate-700">
          {{ t('admin.mcpAdmin.previewSuccess', { count: urlPreviewTools.length }) }}
        </div>
        <div class="max-h-[180px] space-y-2 overflow-y-auto">
          <div
            v-for="tool in urlPreviewTools"
            :key="tool.name"
            class="rounded-md bg-white px-3 py-2"
          >
            <div class="text-sm font-semibold text-slate-800">
              {{ tool.label || tool.name }}
            </div>
            <div v-if="tool.description" class="mt-0.5 text-xs text-slate-500">
              {{ tool.description }}
            </div>
          </div>
        </div>
      </div>
      <div>
        <div class="mb-1 text-sm text-slate-700">{{ t('admin.mcpAdmin.formName') }}</div>
        <a-input v-model="urlName" :placeholder="t('admin.mcpAdmin.namePlaceholder')" allow-clear />
      </div>
      <div>
        <div class="mb-1 text-sm text-slate-700">{{ t('admin.mcpAdmin.formDescription') }}</div>
        <a-textarea
          v-model="urlDescription"
          :auto-size="{ minRows: 2, maxRows: 4 }"
          :placeholder="t('admin.mcpAdmin.descriptionPlaceholder')"
          allow-clear
        />
      </div>
      <div class="grid grid-cols-2 gap-3">
        <div>
          <div class="mb-1 text-sm text-slate-700">{{ t('admin.mcpAdmin.category') }}</div>
          <a-input v-model="urlCategory" :placeholder="t('admin.mcpAdmin.importCategoryPlaceholder')" allow-clear />
        </div>
        <div>
          <div class="mb-1 text-sm text-slate-700">{{ t('admin.mcpAdmin.icon') }}</div>
          <a-input v-model="urlIcon" :placeholder="t('admin.mcpAdmin.importIconPlaceholder')" allow-clear />
        </div>
      </div>
    </div>

    <div v-else-if="activeTab === 'jsonConfig'" class="space-y-3">
      <div class="text-sm text-slate-700">{{ t('admin.mcpAdmin.importJsonConfigLabel') }}</div>
      <a-textarea
        v-model="jsonConfigText"
        :auto-size="{ minRows: 8, maxRows: 18 }"
        :placeholder="t('admin.mcpAdmin.importJsonConfigPlaceholder')"
        allow-clear
      />
      <div class="flex items-center gap-2">
        <a-switch v-model="jsonConfigOverwrite" />
        <span class="text-sm text-slate-600">{{ t('admin.mcpAdmin.importOverwrite') }}</span>
      </div>
    </div>
  </a-modal>
</template>
