<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  app: {
    type: Object,
    default: () => ({}),
    required: true,
  },
})

const config = computed(() => props.app?.draft_app_config || {})
const modelName = computed(() => String(config.value.model_config?.model || '').trim())
const description = computed(() => String(props.app?.description || '').trim())
const openingStatement = computed(() => String(config.value.opening_statement || '').trim())
const openingQuestions = computed(() => (config.value.opening_questions || []).filter(Boolean))

const tools = computed(() => config.value.tools || [])
const mcpBindings = computed(() => config.value.mcp_bindings || [])
const skills = computed(() => config.value.skills || [])
const agentBindings = computed(() => config.value.agent_bindings || [])
const workflows = computed(() => config.value.workflows || [])
const knowledgeBases = computed(() => config.value.knowledge_bases || [])

const abilityItems = computed(() => {
  const items: Array<{ key: string; label: string; count: number }> = [
    { key: 'tools', label: t('appStudio.abilities.tools.title'), count: tools.value.length },
    { key: 'mcp', label: 'MCP', count: mcpBindings.value.length },
    { key: 'skills', label: 'Skills', count: skills.value.length },
    {
      key: 'agents',
      label: t('appStudio.abilities.agents.title'),
      count: agentBindings.value.length,
    },
    {
      key: 'workflows',
      label: t('appStudio.abilities.workflows.title'),
      count: workflows.value.length,
    },
    {
      key: 'knowledge',
      label: t('appStudio.abilities.datasets.title'),
      count: knowledgeBases.value.length,
    },
  ]
  return items.filter((item) => item.count > 0)
})
</script>

<template>
  <div class="flex h-full min-h-0 w-full flex-col">
    <div class="px-5 pt-5">
      <div v-if="description" class="text-sm leading-relaxed text-text-2">
        {{ description }}
      </div>

      <div class="mt-3 flex flex-wrap items-center gap-2">
        <a-tag v-if="modelName" color="arcoblue" size="small">
          <template #icon><icon-robot /></template>
          {{ modelName }}
        </a-tag>
        <a-tag color="gray" size="small">
          {{ t('publicApps.preview.usageOnly') }}
        </a-tag>
      </div>
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto px-5 pb-5 pt-4">
      <div v-if="openingStatement || openingQuestions.length > 0" class="mb-4 rounded-lg border border-border-c bg-surface p-4">
        <div class="mb-2 text-sm font-semibold text-text">
          {{ t('appStudio.abilities.opening.title') }}
        </div>
        <p v-if="openingStatement" class="text-sm leading-relaxed text-text-2">
          {{ openingStatement }}
        </p>
        <div v-if="openingQuestions.length > 0" class="mt-2 space-y-2">
          <div
            v-for="(question, index) in openingQuestions"
            :key="index"
            class="rounded-md bg-surface-2 px-3 py-2 text-sm text-text-2"
          >
            {{ question }}
          </div>
        </div>
      </div>

      <div v-if="abilityItems.length > 0" class="mb-4 rounded-lg border border-border-c bg-surface p-4">
        <div class="mb-3 text-sm font-semibold text-text">
          {{ t('publicApps.preview.abilities') }}
        </div>
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <div
            v-for="item in abilityItems"
            :key="item.key"
            class="flex items-center justify-between rounded-md bg-surface-2 px-3 py-2"
          >
            <span class="min-w-0 truncate text-sm text-text-2">{{ item.label }}</span>
            <a-tag size="small" class="ml-2 shrink-0">{{ item.count }}</a-tag>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
