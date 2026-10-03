<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import {
  createCliProvider,
  updateCliProvider,
  type CliProvider,
  type CliProviderPayload,
  type CliToolSpec,
} from '@/services/admin-cli'

const props = defineProps<{
  visible: boolean
  provider: CliProvider | null
}>()
const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'saved'): void
}>()

const { t } = useI18n()

const form = reactive({
  name: '',
  label: '',
  description: '',
  category: '',
  command: '',
  timeout_seconds: 30,
  enabled: true,
})
const argRows = ref<string[]>([])
const keywordRows = ref<string[]>([])
const toolRows = ref<Array<{ id: string; description: string; parametersText: string }>>([])
const envRows = ref<Array<{ key: string; value: string }>>([])
const clearEnv = ref(false)
const envTouched = ref(false)
const jsonMode = ref(false)
const jsonText = ref('')
const saving = ref(false)

const isEdit = computed(() => Boolean(props.provider))

const fillFromProvider = (provider: CliProvider | null) => {
  form.name = provider?.name ?? ''
  form.label = provider?.label ?? ''
  form.description = provider?.description ?? ''
  form.category = provider?.category ?? ''
  form.command = provider?.command ?? ''
  form.timeout_seconds = provider?.timeout_seconds ?? 30
  form.enabled = provider?.enabled ?? true
  argRows.value = [...(provider?.args ?? [])]
  keywordRows.value = [...(provider?.task_keywords ?? [])]
  toolRows.value = Object.entries(provider?.tool_schema ?? {}).map(([id, spec]) => ({
    id,
    description: spec?.description ?? '',
    parametersText: spec?.parameters ? JSON.stringify(spec.parameters, null, 2) : '',
  }))
  // GET 不回显 env（加密安全约束）：编辑态 env 保持「未编辑不提交」
  envRows.value = []
  clearEnv.value = false
  envTouched.value = false
  jsonMode.value = false
  jsonText.value = ''
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) fillFromProvider(props.provider)
  },
  { immediate: true },
)

const addArg = () => argRows.value.push('')
const removeArg = (index: number) => argRows.value.splice(index, 1)
const addKeyword = () => keywordRows.value.push('')
const removeKeyword = (index: number) => keywordRows.value.splice(index, 1)
const addTool = () => toolRows.value.push({ id: '', description: '', parametersText: '' })
const removeTool = (index: number) => toolRows.value.splice(index, 1)
const addEnv = () => {
  envRows.value.push({ key: '', value: '' })
  envTouched.value = true
}
const removeEnv = (index: number) => {
  envRows.value.splice(index, 1)
  envTouched.value = true
}

const buildToolSchema = (): Record<string, CliToolSpec> | null => {
  if (!toolRows.value.length) {
    Message.error(t('admin.adminCli.modal.schemaRequired'))
    return null
  }
  const schema: Record<string, CliToolSpec> = {}
  for (const row of toolRows.value) {
    const id = row.id.trim()
    if (!id) {
      Message.error(t('admin.adminCli.modal.toolIdRequired'))
      return null
    }
    if (schema[id]) {
      Message.error(t('admin.adminCli.modal.toolIdDuplicate', { id }))
      return null
    }
    const description = row.description.trim()
    if (!description) {
      Message.error(t('admin.adminCli.modal.toolDescRequired'))
      return null
    }
    let parameters: Record<string, unknown> = {}
    const text = row.parametersText.trim()
    if (text) {
      try {
        const parsed = JSON.parse(text)
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
          throw new Error('not an object')
        }
        parameters = parsed as Record<string, unknown>
      } catch {
        Message.error(t('admin.adminCli.modal.paramsInvalid'))
        return null
      }
    }
    schema[id] = { description, parameters }
  }
  return schema
}

const toggleJsonMode = () => {
  if (!jsonMode.value) {
    const schema = buildToolSchema()
    if (!schema) return
    jsonText.value = JSON.stringify(schema, null, 2)
    jsonMode.value = true
    return
  }
  try {
    const parsed = JSON.parse(jsonText.value || '')
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed) || !Object.keys(parsed).length) {
      Message.error(t('admin.adminCli.modal.jsonInvalid'))
      return
    }
    toolRows.value = Object.entries(parsed as Record<string, CliToolSpec>).map(([id, spec]) => ({
      id,
      description: spec?.description ?? '',
      parametersText: spec?.parameters ? JSON.stringify(spec.parameters, null, 2) : '',
    }))
    jsonMode.value = false
  } catch {
    Message.error(t('admin.adminCli.modal.jsonInvalid'))
  }
}

const handleSave = async () => {
  if (!isEdit.value && !form.name.trim()) {
    Message.error(t('admin.adminCli.modal.nameRequired'))
    return
  }
  if (!form.command.trim()) {
    Message.error(t('admin.adminCli.modal.commandRequired'))
    return
  }

  let toolSchema: Record<string, CliToolSpec> | null = null
  if (jsonMode.value) {
    try {
      const parsed = JSON.parse(jsonText.value || '')
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed) || !Object.keys(parsed).length) {
        Message.error(t('admin.adminCli.modal.jsonInvalid'))
        return
      }
      toolSchema = parsed as Record<string, CliToolSpec>
    } catch {
      Message.error(t('admin.adminCli.modal.jsonInvalid'))
      return
    }
  } else {
    toolSchema = buildToolSchema()
    if (!toolSchema) return
  }

  const payload: CliProviderPayload = {
    label: form.label.trim(),
    description: form.description.trim(),
    category: form.category.trim() || 'other',
    command: form.command.trim(),
    args: argRows.value.map((item) => item.trim()).filter(Boolean),
    tool_schema: toolSchema,
    task_keywords: keywordRows.value.map((item) => item.trim()).filter(Boolean),
    timeout_seconds: Number(form.timeout_seconds) || 30,
    enabled: form.enabled,
  }
  if (!isEdit.value) payload.name = form.name.trim()

  // env：GET 不回显——仅在主动编辑（或勾选清空）时提交，未编辑不带 env 键（服务端保持原值）
  if (clearEnv.value) {
    payload.env = {}
  } else if (envTouched.value && envRows.value.length) {
    payload.env = Object.fromEntries(
      envRows.value
        .filter((row) => row.key.trim())
        .map((row) => [row.key.trim(), row.value]),
    )
  }

  saving.value = true
  try {
    if (props.provider) {
      await updateCliProvider(props.provider.id, payload)
      Message.success(t('admin.adminCli.modal.updateSuccess'))
    } else {
      await createCliProvider(payload)
      Message.success(t('admin.adminCli.modal.createSuccess'))
    }
    emit('update:visible', false)
    emit('saved')
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.adminCli.modal.saveFailed')))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <a-modal
    :visible="visible"
    :title="isEdit ? t('admin.adminCli.modal.editTitle', { name: provider?.name }) : t('admin.adminCli.modal.createTitle')"
    :width="720"
    :footer="false"
    @cancel="emit('update:visible', false)"
  >
    <a-form layout="vertical">
      <h4 class="section-title">{{ t('admin.adminCli.modal.basicSection') }}</h4>
      <div class="grid grid-cols-2 gap-3">
        <a-form-item :label="t('admin.adminCli.modal.name')">
          <a-input
            v-if="!isEdit"
            v-model="form.name"
            data-test="name"
            :placeholder="t('admin.adminCli.modal.namePlaceholder')"
            allow-clear
          />
          <a-input v-else :model-value="provider?.name" disabled />
        </a-form-item>
        <a-form-item :label="t('admin.adminCli.modal.label')">
          <a-input v-model="form.label" :placeholder="t('admin.adminCli.modal.labelPlaceholder')" allow-clear />
        </a-form-item>
        <a-form-item :label="t('admin.adminCli.modal.descriptionLabel')">
          <a-input v-model="form.description" :placeholder="t('admin.adminCli.modal.descriptionPlaceholder')" allow-clear />
        </a-form-item>
        <a-form-item :label="t('admin.adminCli.modal.category')">
          <a-input v-model="form.category" :placeholder="t('admin.adminCli.modal.categoryPlaceholder')" allow-clear />
        </a-form-item>
        <a-form-item :label="t('admin.adminCli.modal.timeout')">
          <a-input-number v-model="form.timeout_seconds" :min="1" :step="1" :precision="0" />
        </a-form-item>
        <a-form-item :label="t('admin.adminCli.modal.enabled')">
          <a-switch v-model="form.enabled" />
        </a-form-item>
      </div>

      <h4 class="section-title">{{ t('admin.adminCli.modal.commandSection') }}</h4>
      <a-form-item :label="t('admin.adminCli.modal.command')">
        <a-input v-model="form.command" data-test="command" :placeholder="t('admin.adminCli.modal.commandPlaceholder')" allow-clear />
      </a-form-item>
      <a-form-item :label="t('admin.adminCli.modal.args')">
        <div v-for="(_arg, index) in argRows" :key="index" class="row-line">
          <a-input v-model="argRows[index]" :placeholder="t('admin.adminCli.modal.toolParamsPlaceholder')" />
          <button type="button" class="danger-link" @click="removeArg(index)">−</button>
        </div>
        <button type="button" class="add-link" @click="addArg">+ {{ t('admin.adminCli.modal.addArg') }}</button>
        <p class="hint-text">{{ t('admin.adminCli.modal.argsHint') }}</p>
      </a-form-item>

      <h4 class="section-title">
        {{ t('admin.adminCli.modal.schemaSection') }}
        <button type="button" class="add-link" @click="toggleJsonMode">
          {{ jsonMode ? t('admin.adminCli.modal.jsonBackToTable') : t('admin.adminCli.modal.jsonMode') }}
        </button>
      </h4>
      <a-textarea
        v-if="jsonMode"
        v-model="jsonText"
        data-test="schema-json"
        :rows="10"
        :placeholder="t('admin.adminCli.modal.toolParamsPlaceholder')"
      />
      <template v-else>
        <div v-for="(row, index) in toolRows" :key="index" class="tool-row">
          <a-input
            v-model="row.id"
            :data-test="`tool-id-${index}`"
            :placeholder="t('admin.adminCli.modal.toolIdPlaceholder')"
          />
          <a-input
            v-model="row.description"
            :data-test="`tool-desc-${index}`"
            :placeholder="t('admin.adminCli.modal.toolDescPlaceholder')"
          />
          <a-textarea
            v-model="row.parametersText"
            :rows="2"
            :placeholder="t('admin.adminCli.modal.toolParamsPlaceholder')"
          />
          <button type="button" class="danger-link" @click="removeTool(index)">−</button>
        </div>
        <button type="button" class="add-link add-tool" @click="addTool">
          + {{ t('admin.adminCli.modal.addTool') }}
        </button>
      </template>

      <h4 class="section-title">{{ t('admin.adminCli.modal.keywordSection') }}</h4>
      <div v-for="(_keyword, index) in keywordRows" :key="index" class="row-line">
        <a-input v-model="keywordRows[index]" :placeholder="t('admin.adminCli.modal.keywordPlaceholder')" />
        <button type="button" class="danger-link" @click="removeKeyword(index)">−</button>
      </div>
      <button type="button" class="add-link" @click="addKeyword">
        + {{ t('admin.adminCli.modal.addKeyword') }}
      </button>

      <h4 class="section-title">{{ t('admin.adminCli.modal.envSection') }}</h4>
      <div v-for="(row, index) in envRows" :key="index" class="row-line">
        <a-input v-model="row.key" :placeholder="t('admin.adminCli.modal.envKey')" />
        <a-input v-model="row.value" :placeholder="t('admin.adminCli.modal.envValue')" />
        <button type="button" class="danger-link" @click="removeEnv(index)">−</button>
      </div>
      <button type="button" class="add-link" @click="addEnv">
        + {{ t('admin.adminCli.modal.addEnv') }}
      </button>
      <label class="checkbox-line">
        <input v-model="clearEnv" data-test="clear-env" type="checkbox" />
        {{ t('admin.adminCli.modal.clearEnv') }}
      </label>
      <p class="hint-text">{{ t('admin.adminCli.modal.envHint') }}</p>
    </a-form>

    <div class="footer-bar">
      <button type="button" class="cancel-btn" @click="emit('update:visible', false)">
        {{ t('admin.adminCli.modal.cancel') }}
      </button>
      <button type="button" class="save-btn" :disabled="saving" @click="handleSave">
        {{ t('admin.adminCli.modal.save') }}
      </button>
    </div>
  </a-modal>
</template>

<style scoped>
.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 14px;
  font-weight: 600;
  margin: 16px 0 8px;
}
.row-line,
.tool-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  margin-bottom: 6px;
}
.tool-row > :first-child {
  width: 180px;
  flex: none;
}
.add-link {
  color: #165dff;
  font-size: 13px;
}
.danger-link {
  color: #f53f3f;
  padding: 0 6px;
}
.hint-text {
  font-size: 12px;
  color: #86909c;
  margin-top: 4px;
}
.checkbox-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  margin-top: 8px;
}
.footer-bar {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
.save-btn {
  background: #165dff;
  color: #fff;
  padding: 6px 16px;
  border-radius: 4px;
}
.cancel-btn {
  padding: 6px 16px;
  border: 1px solid #e5e6eb;
  border-radius: 4px;
}
</style>
