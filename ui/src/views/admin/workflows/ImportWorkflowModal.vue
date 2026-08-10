<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import { importAdminWorkflow } from '@/services/admin-workflows'
import { importWorkflow } from '@/services/workflow'

const props = withDefaults(
  defineProps<{
    visible: boolean
    apiMode?: 'admin' | 'user'
    callback?: () => void | Promise<void>
  }>(),
  {
    apiMode: 'admin',
    callback: undefined,
  },
)

const emits = defineEmits(['update:visible'])
const { t } = useI18n()

const jsonText = ref('')
const overwriteName = ref(false)
const submitting = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const hideModal = () => emits('update:visible', false)

const resetState = () => {
  jsonText.value = ''
  overwriteName.value = false
  submitting.value = false
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      resetState()
    }
  },
)

const parsedJson = computed<Record<string, unknown> | null>(() => {
  const text = jsonText.value.trim()
  if (!text) return null
  try {
    const value = JSON.parse(text)
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return value as Record<string, unknown>
    }
    return null
  } catch {
    return null
  }
})

const jsonValid = computed(() => parsedJson.value !== null)

const triggerFilePick = () => {
  fileInput.value?.click()
}

const handleFileChange = async (event: Event) => {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  try {
    const text = await file.text()
    jsonText.value = text
    Message.success(t('admin.workflowsAdmin.import.fileLoaded'))
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.workflowsAdmin.import.fileLoadFailed')))
  } finally {
    target.value = ''
  }
}

const handleImport = async () => {
  if (!jsonText.value.trim()) {
    Message.warning(t('admin.workflowsAdmin.import.jsonRequired'))
    return
  }
  if (!jsonValid.value) {
    Message.error(t('admin.workflowsAdmin.import.jsonInvalid'))
    return
  }
  submitting.value = true
  try {
    if (props.apiMode === 'admin') {
      await importAdminWorkflow(parsedJson.value!, overwriteName.value)
    } else {
      await importWorkflow(parsedJson.value!, overwriteName.value)
    }
    Message.success(t('admin.workflowsAdmin.import.success'))
    if (props.callback) await props.callback()
    hideModal()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.workflowsAdmin.import.failed')))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <a-modal
    :visible="visible"
    :width="640"
    :footer="false"
    :mask-closable="false"
    @cancel="hideModal"
  >
    <template #title>{{ t('admin.workflowsAdmin.import.title') }}</template>
    <div class="space-y-4 py-2">
      <div class="flex items-center justify-between gap-2">
        <div class="text-sm text-slate-700">
          {{ t('admin.workflowsAdmin.import.textLabel') }}
        </div>
        <a-button size="small" type="text" @click="triggerFilePick">
          <template #icon><icon-upload /></template>
          {{ t('admin.workflowsAdmin.import.fromFile') }}
        </a-button>
        <input
          ref="fileInput"
          type="file"
          accept=".json,application/json"
          class="hidden"
          @change="handleFileChange"
        />
      </div>
      <a-textarea
        v-model="jsonText"
        :auto-size="{ minRows: 10, maxRows: 20 }"
        :placeholder="t('admin.workflowsAdmin.import.placeholder')"
        allow-clear
      />
      <div
        v-if="jsonText.trim() && !jsonValid"
        class="text-xs text-red-600"
      >
        {{ t('admin.workflowsAdmin.import.jsonInvalid') }}
      </div>
      <div class="flex items-center justify-between">
        <a-space>
          <a-switch v-model="overwriteName" />
          <span class="text-sm text-slate-600">
            {{ t('admin.workflowsAdmin.import.overwriteName') }}
          </span>
        </a-space>
        <div class="flex items-center gap-2">
          <a-button @click="hideModal">{{ t('common.actions.cancel') }}</a-button>
          <a-button
            type="primary"
            :loading="submitting"
            :disabled="!jsonValid"
            @click="handleImport"
          >
            {{ t('admin.workflowsAdmin.import.button') }}
          </a-button>
        </div>
      </div>
    </div>
  </a-modal>
</template>
