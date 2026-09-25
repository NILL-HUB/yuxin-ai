<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { IconRefresh } from '@arco-design/web-vue/es/icon'
import { MCP_CLI_TEMPLATES } from './mcp-cli-templates'
import type { McpCliTemplate } from './types'

const emits = defineEmits<{
  (e: 'apply', template: McpCliTemplate): void
}>()

const { t } = useI18n()

const selectedKey = ref('')
const useLatest = ref(false)

const selected = computed(() => MCP_CLI_TEMPLATES.find((item) => item.key === selectedKey.value))

const templateLabel = (template: McpCliTemplate) => t(`configEditors.templates.${template.key}`)

const templateHint = (template: McpCliTemplate) =>
  template.requiresSecret
    ? t('configEditors.templateNeedsSecret', { name: template.secretKeyName })
    : t('configEditors.templateNoSecret')

const handleSelect = (
  key: string | number | boolean | Record<string, unknown> | (string | number | boolean | Record<string, unknown>)[],
) => {
  selectedKey.value = String(key ?? '')
}

const applyTemplate = () => {
  const template = selected.value
  if (!template) return
  const applied: McpCliTemplate = useLatest.value
    ? { ...template, versionedPackage: `${template.versionedPackage.slice(0, template.versionedPackage.lastIndexOf('@'))}@latest` }
    : template
  emits('apply', applied)
}
</script>

<template>
  <div class="rounded-lg border border-dashed border-blue-200 bg-blue-50/50 p-3">
    <div class="mb-2 text-sm font-semibold text-gray-800">
      {{ t('configEditors.templateTitle') }}
    </div>
    <div class="mb-2 text-xs leading-5 text-gray-500">
      {{ t('configEditors.templateDescription') }}
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <a-select
        :model-value="selectedKey"
        class="w-72"
        :placeholder="t('configEditors.templatePlaceholder')"
        @change="handleSelect"
      >
        <a-option v-for="template in MCP_CLI_TEMPLATES" :key="template.key" :value="template.key">
          {{ templateLabel(template) }}
        </a-option>
      </a-select>

      <a-button type="primary" :disabled="!selected" @click="applyTemplate">
        {{ t('configEditors.templateApply') }}
      </a-button>

      <a-checkbox v-model="useLatest">
        <template #default>
          <span class="inline-flex items-center gap-1">
            <icon-refresh />
            {{ t('configEditors.templateUseLatest') }}
          </span>
        </template>
      </a-checkbox>
    </div>

    <div v-if="selected" class="mt-2 text-xs text-gray-500">
      {{ templateHint(selected) }}
    </div>
  </div>
</template>
