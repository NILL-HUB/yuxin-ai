<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { IconPlus, IconDelete, IconCode } from '@arco-design/web-vue/es/icon'
import { TOOL_PARAMETER_TYPES, type ToolDefinitionItem, type ToolParameterItem, type ToolParameterType } from './types'
import { formatJson, parseJsonObject } from './config-parse'

const props = withDefaults(
  defineProps<{
    modelValue: Record<string, unknown>
    readonly?: boolean
  }>(),
  {
    readonly: false,
  },
)

const emits = defineEmits<{
  (e: 'update:modelValue', value: Record<string, unknown>): void
}>()

const { t } = useI18n()

const emptyParam = (): ToolParameterItem => ({
  name: '',
  type: 'string',
  required: false,
  description: '',
})

const emptyTool = (): ToolDefinitionItem => ({
  name: '',
  description: '',
  parameters: [],
})

const toItems = (schema: unknown): ToolDefinitionItem[] => {
  if (!schema || typeof schema !== 'object' || Array.isArray(schema)) return []
  return Object.entries(schema as Record<string, unknown>).map(([name, raw]) => {
    const definition = raw && typeof raw === 'object' && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)
      : {}
    const parametersSchema = definition.parameters
    const parametersObject =
      parametersSchema && typeof parametersSchema === 'object' && !Array.isArray(parametersSchema)
        ? (parametersSchema as Record<string, unknown>)
        : {}
    const properties =
      parametersObject.properties && typeof parametersObject.properties === 'object' && !Array.isArray(parametersObject.properties)
        ? (parametersObject.properties as Record<string, unknown>)
        : {}
    const requiredNames = Array.isArray(parametersObject.required)
      ? (parametersObject.required as unknown[]).map((item) => String(item ?? ''))
      : []
    return {
      name: String(name),
      description: String(definition.description ?? ''),
      parameters: Object.entries(properties).map(([paramName, paramRaw]) => {
        const paramDefinition =
          paramRaw && typeof paramRaw === 'object' && !Array.isArray(paramRaw)
            ? (paramRaw as Record<string, unknown>)
            : {}
        const rawType = String(paramDefinition.type ?? 'string')
        const type = (TOOL_PARAMETER_TYPES as string[]).includes(rawType)
          ? (rawType as ToolParameterType)
          : 'string'
        return {
          name: String(paramName),
          type,
          required: requiredNames.includes(String(paramName)),
          description: String(paramDefinition.description ?? ''),
        }
      }),
    }
  })
}

const toSchema = (items: ToolDefinitionItem[]): Record<string, unknown> => {
  const schema: Record<string, unknown> = {}
  items.forEach((tool) => {
    const toolName = tool.name.trim()
    if (!toolName) return
    const properties: Record<string, unknown> = {}
    const required: string[] = []
    tool.parameters.forEach((param) => {
      const paramName = param.name.trim()
      if (!paramName) return
      properties[paramName] = {
        type: param.type,
        ...(param.description ? { description: param.description } : {}),
      }
      if (param.required) required.push(paramName)
    })
    schema[toolName] = {
      description: tool.description,
      parameters: {
        type: 'object',
        properties,
        ...(required.length ? { required } : {}),
      },
    }
  })
  return schema
}

const tools = ref<ToolDefinitionItem[]>(toItems(props.modelValue))

const commit = () => {
  emits('update:modelValue', toSchema(tools.value))
}

const addTool = () => {
  if (props.readonly) return
  tools.value = [...tools.value, emptyTool()]
}

const removeTool = (index: number) => {
  if (props.readonly) return
  tools.value = tools.value.filter((_, idx) => idx !== index)
  commit()
}

const updateToolName = (index: number, value: string) => {
  const tool = tools.value[index]
  if (!tool) return
  tool.name = value
  commit()
}

const updateToolDescription = (index: number, value: string) => {
  const tool = tools.value[index]
  if (!tool) return
  tool.description = value
  commit()
}

const addParam = (toolIndex: number) => {
  if (props.readonly) return
  const tool = tools.value[toolIndex]
  if (!tool) return
  tool.parameters = [...tool.parameters, emptyParam()]
}

const removeParam = (toolIndex: number, paramIndex: number) => {
  if (props.readonly) return
  const tool = tools.value[toolIndex]
  if (!tool) return
  tool.parameters = tool.parameters.filter((_, idx) => idx !== paramIndex)
  commit()
}

const updateParam = <K extends keyof ToolParameterItem>(
  toolIndex: number,
  paramIndex: number,
  field: K,
  value: ToolParameterItem[K],
) => {
  const tool = tools.value[toolIndex]
  const param = tool?.parameters[paramIndex]
  if (!tool || !param) return
  param[field] = value
  commit()
}

const showRawEditor = ref(false)
const rawText = ref('')
const rawError = ref('')

const toggleRawEditor = () => {
  showRawEditor.value = !showRawEditor.value
  if (showRawEditor.value) {
    rawText.value = formatJson(props.modelValue, '{}')
    rawError.value = ''
  }
}

const applyRawText = () => {
  try {
    const parsed = parseJsonObject(rawText.value)
    tools.value = toItems(parsed)
    rawError.value = ''
    commit()
  } catch {
    rawError.value = t('configEditors.schemaInvalidJson')
  }
}
</script>

<template>
  <div class="space-y-3">
    <div
      v-for="(tool, toolIndex) in tools"
      :key="toolIndex"
      class="rounded-lg border border-gray-200 p-3"
    >
      <div class="mb-2 flex items-center gap-2">
        <a-input
          :model-value="tool.name"
          class="flex-1"
          :placeholder="t('configEditors.toolNamePlaceholder')"
          :readonly="readonly"
          :disabled="readonly"
          allow-clear
          @update:model-value="(value: string) => updateToolName(toolIndex, value)"
        />
        <a-button v-if="!readonly" type="text" size="small" status="danger" @click="removeTool(toolIndex)">
          <template #icon><icon-delete /></template>
        </a-button>
      </div>

      <a-textarea
        :model-value="tool.description"
        class="mb-2"
        :auto-size="{ minRows: 1, maxRows: 3 }"
        :placeholder="t('configEditors.toolDescriptionPlaceholder')"
        :readonly="readonly"
        :disabled="readonly"
        @update:model-value="(value: string) => updateToolDescription(toolIndex, value)"
      />

      <div class="space-y-2">
        <div
          v-for="(param, paramIndex) in tool.parameters"
          :key="paramIndex"
          class="flex items-center gap-2"
        >
          <a-input
            :model-value="param.name"
            class="flex-1"
            :placeholder="t('configEditors.paramNamePlaceholder')"
            :readonly="readonly"
            :disabled="readonly"
            allow-clear
            @update:model-value="(value: string) => updateParam(toolIndex, paramIndex, 'name', value)"
          />
          <a-select
            :model-value="param.type"
            class="w-32 shrink-0"
            :disabled="readonly"
            @change="(value: unknown) => updateParam(toolIndex, paramIndex, 'type', value as ToolParameterType)"
          >
            <a-option v-for="type in TOOL_PARAMETER_TYPES" :key="type" :value="type">{{ type }}</a-option>
          </a-select>
          <a-checkbox
            :model-value="param.required"
            :disabled="readonly"
            @change="(value: boolean | (string | number | boolean)[]) => updateParam(toolIndex, paramIndex, 'required', Boolean(value))"
          >
            {{ t('configEditors.paramRequired') }}
          </a-checkbox>
          <a-input
            :model-value="param.description"
            class="flex-1"
            :placeholder="t('configEditors.paramDescriptionPlaceholder')"
            :readonly="readonly"
            :disabled="readonly"
            allow-clear
            @update:model-value="(value: string) => updateParam(toolIndex, paramIndex, 'description', value)"
          />
          <a-button
            v-if="!readonly"
            type="text"
            size="small"
            status="danger"
            @click="removeParam(toolIndex, paramIndex)"
          >
            <template #icon><icon-delete /></template>
          </a-button>
        </div>
      </div>

      <a-button v-if="!readonly" type="text" size="small" class="mt-2" @click="addParam(toolIndex)">
        <template #icon><icon-plus /></template>
        {{ t('configEditors.addParam') }}
      </a-button>
    </div>

    <a-button v-if="!readonly" type="text" size="small" @click="addTool">
      <template #icon><icon-plus /></template>
      {{ t('configEditors.addTool') }}
    </a-button>

    <div class="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-2">
      <a-button type="text" size="small" @click="toggleRawEditor">
        <template #icon><icon-code /></template>
        {{ t('configEditors.toggleRawJson') }}
      </a-button>
      <div v-if="showRawEditor" class="mt-2 space-y-2">
        <a-textarea
          v-model="rawText"
          :auto-size="{ minRows: 4, maxRows: 12 }"
          :readonly="readonly"
          :disabled="readonly"
        />
        <div v-if="rawError" class="text-xs text-red-600">{{ rawError }}</div>
        <a-button v-if="!readonly" type="text" size="small" @click="applyRawText">
          {{ t('configEditors.applyRawJson') }}
        </a-button>
      </div>
    </div>
  </div>
</template>
