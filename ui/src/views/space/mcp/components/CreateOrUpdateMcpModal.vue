<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { type FileItem, Form, Message, type ValidatedError } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import IconUploadGenerator from '@/components/IconUploadGenerator.vue'
import { useUploadImage } from '@/hooks/use-upload-file'
import { getErrorMessage } from '@/utils/error'
import { getStoreCategoryDisplayName } from '@/utils/store-display'
import { getMcpCategories, getMcpProvider, createMcpProvider, updateMcpProvider, generateMcpIconPreview, regenerateMcpIcon } from '@/services/mcp'
import { getAdminMcp, updateAdminMcp, regenerateAdminMcpIcon, createAdminMcp } from '@/services/admin-mcp'
import { mcpSchemaAssistantChat } from '@/services/ai'
import type { McpCategory } from '@/models/mcp'
import KeyValueEditor from '@/components/config-editors/KeyValueEditor.vue'
import OrderedArgListEditor from '@/components/config-editors/OrderedArgListEditor.vue'
import TagListEditor from '@/components/config-editors/TagListEditor.vue'
import ToolSchemaBuilder from '@/components/config-editors/ToolSchemaBuilder.vue'
import McpTemplatePicker from '@/components/config-editors/McpTemplatePicker.vue'
import type { McpCliTemplate } from '@/components/config-editors/types'
import { resolveBindingCredentials } from '@/components/config-editors/mcp-binding-source'

type HeaderItem = { key: string; value: string }

type McpForm = {
  fileList: FileItem[]
  icon: string
  name: string
  description: string
  category: string
  transport: string
  url: string
  command: string
  headers: HeaderItem[]
  tool_names: string[]
  args: string[]
  env: Record<string, string>
  tool_schema: Record<string, unknown>
  timeout_seconds: number
  task_keywords: string[]
}

const props = defineProps({
  mcp_provider_id: { type: String, default: '', required: false },
  visible: { type: Boolean, required: true },
  callback: { type: Function, required: false },
  adminMode: { type: Boolean, default: false, required: false },
})

const emits = defineEmits(['update:visible', 'update:mcp_provider_id'])
const { t, locale } = useI18n()

const categories = ref<McpCategory[]>([])
const formRef = ref<InstanceType<typeof Form>>()
const loadingProvider = ref(false)
const submitLoading = ref(false)
const generateLoading = ref(false)
const aiQuestion = ref('')
const aiAnswer = ref('')
const aiLoading = ref(false)
const { image_url, handleUploadImage } = useUploadImage()

const defaultForm = (): McpForm => ({
  fileList: [],
  icon: '',
  name: '',
  description: '',
  category: 'other',
  transport: 'streamable_http',
  url: '',
  command: '',
  headers: [],
  tool_names: [],
  args: [],
  env: {},
  tool_schema: {},
  timeout_seconds: 30,
  task_keywords: [],
})

const form = ref<McpForm>(defaultForm())

const isEditMode = computed(() => Boolean(props.mcp_provider_id))
const normalizedTransport = computed(() => String(form.value.transport || '').trim().toLowerCase())
const isHttpTransport = computed(() =>
  ['http', 'sse', 'streamable_http', 'streamable-http'].includes(normalizedTransport.value),
)
const isCliTransport = computed(() => normalizedTransport.value === 'cli')
const hasCommandField = computed(() => ['stdio', 'cli'].includes(normalizedTransport.value))
const getCategoryLabel = (value: string) =>
  getStoreCategoryDisplayName(value, locale.value as 'zh-CN' | 'en-US')

const hideModal = () => emits('update:visible', false)

const loadCategories = async () => {
  try {
    const res = await getMcpCategories()
    categories.value = res.data.categories || []
  } catch {
    categories.value = []
  }
}

const extractJsonObject = (content: string) => {
  const fenceMatch = content.match(/```(?:json)?\s*([\s\S]*?)```/i)
  const normalized = (fenceMatch?.[1] ?? content).trim()
  const firstBrace = normalized.indexOf('{')
  const lastBrace = normalized.lastIndexOf('}')
  if (firstBrace !== -1 && lastBrace > firstBrace) {
    return normalized.slice(firstBrace, lastBrace + 1)
  }
  return normalized
}

const applyMcpPayload = (payload: Record<string, unknown>) => {
  const { headers: rawHeaders, env: rawEnv } = resolveBindingCredentials(payload)
  const headers = Array.isArray(rawHeaders) ? rawHeaders : []
  const toolNames = Array.isArray(payload.tool_names) ? payload.tool_names : []
  const args = Array.isArray(payload.args) ? payload.args : []
  const env = rawEnv && typeof rawEnv === 'object' && !Array.isArray(rawEnv) ? (rawEnv as Record<string, unknown>) : {}
  const toolSchema =
    payload.tool_schema && typeof payload.tool_schema === 'object' && !Array.isArray(payload.tool_schema)
      ? payload.tool_schema
      : {}

  form.value.name = String(payload.name || '').trim()
  form.value.description = String(payload.description || '').trim()
  form.value.category = String(payload.category || 'other').trim() || 'other'
  form.value.transport = String(payload.transport || 'streamable_http').trim() || 'streamable_http'
  form.value.url = String(payload.url || '').trim()
  form.value.command = String(payload.command || '').trim()
  form.value.headers = headers.map((item) => ({
    key: String((item as HeaderItem)?.key || '').trim(),
    value: String((item as HeaderItem)?.value || ''),
  }))
  form.value.tool_names = toolNames.map((item) => String(item).trim()).filter(Boolean)
  form.value.args = args.map((item) => String(item).trim()).filter(Boolean)
  form.value.env = Object.fromEntries(
    Object.entries(env).map(([key, value]) => [key, String(value ?? '')]),
  )
  form.value.tool_schema = toolSchema as Record<string, unknown>
  form.value.timeout_seconds = Number(payload.timeout_seconds || 30)
  form.value.icon = String(payload.icon || form.value.icon || '')
  const taskKeywords = Array.isArray(payload.task_keywords) ? payload.task_keywords : []
  form.value.task_keywords = taskKeywords
    .map((item: unknown) => String(item || '').trim())
    .filter(Boolean)
  if (form.value.icon) {
    form.value.fileList = [{ uid: '1', name: t('space.mcp.iconPlaceholder'), url: form.value.icon }]
  }
}

const loadProvider = async (providerId: string) => {
  if (!providerId) {
    form.value = defaultForm()
    return
  }

  loadingProvider.value = true
  try {
    const res = props.adminMode ? await getAdminMcp(providerId) : await getMcpProvider(providerId)
    applyMcpPayload(res.data)
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('space.mcp.detailLoadFailed')))
  } finally {
    loadingProvider.value = false
  }
}

const handleUploadIcon = async (file: File) => {
  await handleUploadImage(file)
  form.value.icon = image_url.value
  form.value.fileList = [{ uid: '1', name: t('space.mcp.iconPlaceholder'), url: image_url.value }]
  Message.success(t('space.mcp.iconUploadSuccess'))
}

const handleGenerateIcon = async () => {
  if (!form.value.name || form.value.name.trim() === '') {
    Message.warning(t('space.mcp.nameRequired'))
    return
  }

  try {
    generateLoading.value = true
    if (isEditMode.value) {
      const providerId = props.mcp_provider_id
      const res = props.adminMode
        ? await regenerateAdminMcpIcon(providerId)
        : await regenerateMcpIcon(providerId)
      if (res.data.icon) {
        form.value.icon = res.data.icon
        form.value.fileList = [{ uid: '1', name: t('space.mcp.iconPlaceholder'), url: res.data.icon }]
        Message.success(t('space.mcp.iconGenerateSuccess'))
      }
    } else {
      const res = await generateMcpIconPreview(form.value.name, form.value.description)
      if (res.data.icon) {
        form.value.icon = res.data.icon
        form.value.fileList = [{ uid: '1', name: t('space.mcp.iconPlaceholder'), url: res.data.icon }]
        Message.success(t('space.mcp.iconGenerateSuccess'))
      }
    }
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('space.mcp.iconGenerateFailed')))
  } finally {
    generateLoading.value = false
  }
}

const handleGenerateByAI = async () => {
  const question = aiQuestion.value.trim()
  if (!question) {
    Message.warning(t('space.mcp.aiDescriptionRequired'))
    return
  }

  aiLoading.value = true
  aiAnswer.value = ''
  try {
    await mcpSchemaAssistantChat(question, (eventResponse) => {
      const content = String((eventResponse?.data as { content?: string } | undefined)?.content ?? '')
      if (!content) return
      aiAnswer.value += content
    })

    const jsonText = extractJsonObject(aiAnswer.value)
    const payload = JSON.parse(jsonText)
    applyMcpPayload(payload)
    Message.success(t('space.mcp.aiConfigSuccess'))
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('space.mcp.aiConfigFailed')))
  } finally {
    aiLoading.value = false
  }
}

const applyCliTemplate = (template: McpCliTemplate) => {
  form.value.transport = template.transport
  form.value.command = template.command
  form.value.args = [...template.args]
  form.value.env = { ...template.env }
  if (template.requiresSecret && template.secretKeyName && !(template.secretKeyName in form.value.env)) {
    form.value.env[template.secretKeyName] = ''
  }
  form.value.tool_schema = JSON.parse(JSON.stringify(template.toolSchema))
  Message.success(t('configEditors.templateApplied'))
}

const handleSubmit = async ({ errors }: { errors: Record<string, ValidatedError> | undefined }) => {
  if (errors) return

  const headers: HeaderItem[] = (form.value.headers || [])
    .map((item) => ({ key: String(item?.key || '').trim(), value: String(item?.value || '') }))
    .filter((item) => item.key)
  const env: Record<string, string> = { ...(form.value.env || {}) }
  const toolSchema: Record<string, unknown> = { ...(form.value.tool_schema || {}) }

  const toolNames = (form.value.tool_names || []).map((item) => String(item).trim()).filter(Boolean)
  const args = (form.value.args || []).map((item) => String(item)).filter((item) => item !== '')
  const taskKeywords = (form.value.task_keywords || []).map((item) => String(item).trim()).filter(Boolean)

  const payload = {
    name: form.value.name.trim(),
    description: form.value.description.trim(),
    category: form.value.category,
    transport: form.value.transport,
    url: String(form.value.url || '').trim(),
    command: String(form.value.command || '').trim(),
    headers,
    tool_names: toolNames,
    args,
    env,
    tool_schema: toolSchema,
    timeout_seconds: Number(form.value.timeout_seconds || 30),
    icon: form.value.icon,
    task_keywords: taskKeywords,
  }

  if (payload.transport === 'stdio' && !payload.command) {
    Message.warning(t('space.mcp.stdioCommandRequired'))
    return
  }
  if (['http', 'sse', 'streamable_http', 'streamable-http'].includes(payload.transport) && !payload.url) {
    Message.warning(t('space.mcp.urlRequired'))
    return
  }
  if (payload.transport === 'cli') {
    if (!payload.command) {
      Message.warning(t('space.mcp.stdioCommandRequired'))
      return
    }
    if (!Object.keys(payload.tool_schema || {}).length) {
      Message.warning(t('space.mcp.toolSchemaRequired'))
      return
    }
  }

  submitLoading.value = true
  try {
    if (isEditMode.value) {
      if (props.adminMode) {
        await updateAdminMcp(props.mcp_provider_id, payload)
      } else {
        await updateMcpProvider(props.mcp_provider_id, payload)
      }
      Message.success(t('space.mcp.updateSuccess'))
    } else {
      if (props.adminMode) {
        await createAdminMcp(payload)
      } else {
        await createMcpProvider(payload)
      }
      Message.success(t('space.mcp.createSuccess'))
    }
    emits('update:visible', false)
    emits('update:mcp_provider_id', '')
    if (props.callback) props.callback()
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('space.mcp.saveFailed')))
  } finally {
    submitLoading.value = false
  }
}

watch(
  () => props.visible,
  async (visible) => {
    formRef.value?.resetFields()
    aiQuestion.value = ''
    aiAnswer.value = ''
    if (!visible) {
      form.value = defaultForm()
      emits('update:mcp_provider_id', '')
      return
    }

    await loadCategories()
    if (props.mcp_provider_id) {
      await loadProvider(props.mcp_provider_id)
    } else {
      form.value = defaultForm()
    }
  },
)
</script>

<template>
  <a-modal
    :visible="props.visible"
    hide-title
    :footer="false"
    :width="1080"
    class="tools-modal mcp-create-modal"
    modal-class="mcp-create-modal-shell"
    @cancel="hideModal"
  >
    <a-spin :loading="loadingProvider" class="block h-full w-full">
      <div class="flex h-full w-full flex-col overflow-hidden lg:flex-row">
        <aside
          class="flex flex-col gap-4 border-b border-gray-200 bg-gray-50 p-4 lg:w-[330px] lg:border-b-0 lg:border-r lg:overflow-y-auto scrollbar-w-none"
        >
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="text-xl font-bold text-gray-800">
                {{ isEditMode ? t('space.mcp.updateTitle') : t('space.mcp.createTitle') }}
              </div>
              <div class="mt-1 text-xs leading-5 text-gray-500">
                {{ t('space.mcp.modalDescription') }}
              </div>
            </div>
            <a-button type="text" class="!text-gray-500 hover:!text-gray-700" size="small" @click="hideModal">
              <template #icon>
                <icon-close :size="20" />
              </template>
            </a-button>
          </div>

          <div class="mb-0">
            <IconUploadGenerator
              :name="form.name"
              :description="form.description"
              :icon="form.icon"
              :file-list="form.fileList"
              :loading="generateLoading"
              :placeholder="t('space.mcp.iconPlaceholder')"
              :on-upload="handleUploadIcon"
              :on-generate="handleGenerateIcon"
              @update:icon="(val) => (form.icon = val)"
              @update:fileList="(val) => (form.fileList = val)"
            />
          </div>

          <div class="rounded-lg border border-gray-200 bg-white p-4">
            <div class="flex items-center justify-between gap-2 mb-3">
              <div class="text-sm font-semibold text-gray-800">{{ t('space.mcp.aiTitle') }}</div>
              <a-button type="primary" size="small" :loading="aiLoading" @click="handleGenerateByAI">
                {{ t('space.mcp.aiButton') }}
              </a-button>
            </div>
            <a-textarea
              v-model="aiQuestion"
              :auto-size="{ minRows: 4, maxRows: 6 }"
              :placeholder="t('space.mcp.aiPlaceholder')"
            />
          </div>

          <div class="rounded-lg border border-blue-100 bg-blue-50 p-3 text-xs leading-5 text-blue-800">
            <div class="font-semibold text-blue-900 mb-1">{{ t('space.mcp.fillHintTitle') }}</div>
            <div>{{ t('space.mcp.fillHint') }}</div>
          </div>
        </aside>

        <section class="flex-1 min-w-0 bg-white p-4 lg:overflow-y-auto scrollbar-w-none">
          <a-form ref="formRef" :model="form" layout="vertical" @submit="handleSubmit">
            <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <a-form-item
                field="name"
                :label="t('space.mcp.nameLabel')"
                asterisk-position="end"
                class="lg:col-span-2"
                :rules="[{ required: true, message: t('space.mcp.nameRequired') }]"
              >
                <a-input v-model:model-value="form.name" :placeholder="t('space.mcp.namePlaceholder')" />
              </a-form-item>

              <a-form-item
                field="description"
                :label="t('space.mcp.descriptionLabel')"
                asterisk-position="end"
                class="lg:col-span-2"
                :rules="[{ required: true, message: t('space.mcp.descriptionRequired') }]"
              >
                <a-textarea
                  v-model:model-value="form.description"
                  :auto-size="{ minRows: 3, maxRows: 4 }"
                  :placeholder="t('space.mcp.descriptionPlaceholder')"
                />
              </a-form-item>

              <a-form-item field="category" :label="t('space.mcp.categoryLabel')">
                <a-select v-model:model-value="form.category" :placeholder="t('space.mcp.categoryPlaceholder')">
                  <a-option v-for="category in categories" :key="category.id" :value="category.id">
                    {{ getCategoryLabel(category.id || category.name) }}
                  </a-option>
                </a-select>
              </a-form-item>

              <a-form-item field="transport" :label="t('space.mcp.transportLabel')">
                <a-select v-model:model-value="form.transport" :placeholder="t('space.mcp.transportPlaceholder')">
                  <a-option value="streamable_http">streamable_http</a-option>
                  <a-option value="http">http</a-option>
                  <a-option value="sse">sse</a-option>
                  <a-option value="stdio">stdio</a-option>
                  <a-option value="cli">cli</a-option>
                </a-select>
              </a-form-item>

              <a-form-item field="timeout_seconds" :label="t('space.mcp.timeoutLabel')">
                <a-input-number v-model:model-value="form.timeout_seconds" :min="1" :max="600" />
              </a-form-item>

              <div class="hidden rounded-lg border border-dashed border-gray-200 bg-gray-50 p-4 text-xs leading-5 text-gray-500 lg:block">
                <div class="font-semibold text-gray-800 mb-1">{{ t('space.mcp.advancedHintTitle') }}</div>
                <div>{{ t('space.mcp.advancedHint') }}</div>
              </div>

              <a-form-item
                v-if="isHttpTransport"
                field="url"
                :label="t('space.mcp.urlLabel')"
                class="lg:col-span-2"
              >
                <a-input v-model:model-value="form.url" :placeholder="t('space.mcp.urlPlaceholder')" />
              </a-form-item>

              <a-form-item
                v-if="hasCommandField"
                field="command"
                :label="t('space.mcp.commandLabel')"
                class="lg:col-span-2"
              >
                <a-input v-model:model-value="form.command" :placeholder="t('space.mcp.commandPlaceholder')" />
              </a-form-item>

              <a-form-item
                v-if="isCliTransport"
                class="lg:col-span-2"
                :label="t('configEditors.templateTitle')"
              >
                <mcp-template-picker @apply="applyCliTemplate" />
              </a-form-item>

              <a-form-item
                v-if="isHttpTransport"
                field="headers"
                :label="t('space.mcp.headersLabel')"
                class="lg:col-span-2"
              >
                <key-value-editor v-model="form.headers" secret />
              </a-form-item>

              <a-form-item
                v-if="hasCommandField"
                field="args"
                :label="t('space.mcp.argsLabel')"
                class="lg:col-span-2"
              >
                <ordered-arg-list-editor v-model="form.args" />
              </a-form-item>

              <a-form-item
                v-if="hasCommandField"
                field="env"
                :label="t('space.mcp.envLabel')"
                class="lg:col-span-2"
              >
                <key-value-editor v-model="form.env" secret />
              </a-form-item>

              <a-form-item
                v-if="isCliTransport"
                field="tool_schema"
                :label="t('space.mcp.toolSchemaLabel')"
                class="lg:col-span-2"
              >
                <tool-schema-builder v-model="form.tool_schema" />
              </a-form-item>

              <a-form-item
                v-if="isHttpTransport"
                field="tool_names"
                :label="t('space.mcp.toolNamesLabel')"
                class="lg:col-span-2"
              >
                <tag-list-editor v-model="form.tool_names" :placeholder="t('space.mcp.toolNamesPlaceholder')" />
              </a-form-item>

              <a-form-item field="task_keywords" :label="t('space.mcp.taskKeywordsLabel')" class="lg:col-span-2">
                <tag-list-editor v-model="form.task_keywords" :placeholder="t('space.mcp.taskKeywordsPlaceholder')" />
              </a-form-item>
            </div>

            <div class="flex items-center justify-end gap-3 pt-4">
              <a-button html-type="button" size="large" class="rounded-lg px-6" @click="hideModal">{{ t('common.actions.cancel') }}</a-button>
              <a-button
                :loading="submitLoading"
                type="primary"
                html-type="submit"
                size="large"
                class="rounded-lg px-6"
              >
                {{ t('common.actions.save') }}
              </a-button>
            </div>
          </a-form>
        </section>
      </div>
    </a-spin>
  </a-modal>
</template>

<style>
@reference "tailwindcss";
.mcp-create-modal-shell {
  height: calc(100dvh - 32px);
  max-height: calc(100dvh - 32px);
  width: min(96vw, 1080px);
}

.mcp-create-modal .arco-modal-wrapper {
  @apply text-right;
}

.mcp-create-modal .arco-modal-body {
  @apply h-full w-full rounded-xl p-0 overflow-hidden;
}

@supports not (height: 100dvh) {
  .mcp-create-modal-shell {
    height: calc(100vh - 32px);
    max-height: calc(100vh - 32px);
  }
}
</style>
