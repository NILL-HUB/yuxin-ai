<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ToolConfirmationPrompt } from '@/models/tool-confirmation'

const props = defineProps<{
  prompt: ToolConfirmationPrompt
}>()

const emit = defineEmits<{
  confirm: [id: string]
  cancel: [id: string]
}>()

const { t } = useI18n()

const cancelButtonRef = ref<{ $el?: HTMLElement } | null>(null)

const riskColor = computed(() => {
  switch (props.prompt.risk_level) {
    case 'medium':
      return 'gold'
    case 'high':
      return 'orange'
    case 'sensitive':
      return 'red'
    default:
      return 'gray'
  }
})

const optionalMetaRows = computed(() => {
  const rows: { label: string; value: string }[] = []
  if (props.prompt.target_system) {
    rows.push({ label: t('toolConfirmation.targetSystem'), value: props.prompt.target_system })
  }
  if (props.prompt.target_environment) {
    rows.push({
      label: t('toolConfirmation.targetEnvironment'),
      value: props.prompt.target_environment,
    })
  }
  if (props.prompt.impact_scope) {
    rows.push({ label: t('toolConfirmation.impactScope'), value: props.prompt.impact_scope })
  }
  if (props.prompt.rollback_strategy) {
    rows.push({
      label: t('toolConfirmation.rollbackStrategy'),
      value: props.prompt.rollback_strategy,
    })
  }
  if (props.prompt.audit_hint) {
    rows.push({ label: t('toolConfirmation.auditHint'), value: props.prompt.audit_hint })
  }
  return rows
})

onMounted(() => {
  cancelButtonRef.value?.$el?.focus()
})

const handleConfirm = () => emit('confirm', props.prompt.id)
const handleCancel = () => emit('cancel', props.prompt.id)
</script>

<template>
  <div class="rounded-xl border border-orange-200 bg-orange-50 p-4 text-sm text-gray-800 shadow-sm">
    <div class="mb-3 flex items-center justify-between gap-2">
      <span class="font-semibold text-orange-900">{{ t('toolConfirmation.title') }}</span>
      <span class="flex items-center gap-1.5">
        <span class="text-gray-500">{{ t('toolConfirmation.riskLevel') }}</span>
        <a-tag :color="riskColor" size="small">{{ props.prompt.risk_level }}</a-tag>
      </span>
    </div>

    <div class="mb-1.5 break-all font-medium text-gray-900">{{ props.prompt.tool_name }}</div>
    <div class="mb-3 text-gray-700">
      <span class="font-semibold text-gray-900">{{ props.prompt.spent_credits }}</span>
      <span class="ml-1">{{ t('billing.usage.unit') }}</span>
    </div>

    <dl v-if="optionalMetaRows.length > 0" class="mb-3 space-y-1.5">
      <div v-for="row in optionalMetaRows" :key="row.label" class="flex gap-2 text-gray-700">
        <dt class="w-24 shrink-0 text-gray-500">{{ row.label }}</dt>
        <dd class="flex-1 break-words">{{ row.value }}</dd>
      </div>
    </dl>

    <div class="mb-1 text-gray-500">{{ t('toolConfirmation.toolInput') }}</div>
    <pre class="mb-4 max-h-40 overflow-auto rounded-lg bg-white/70 p-3 text-xs text-gray-600">{{ props.prompt.tool_input }}</pre>

    <div class="flex justify-end gap-2">
      <a-button ref="cancelButtonRef" data-test="tool-cancel" @click="handleCancel">
        {{ t('toolConfirmation.cancel') }}
      </a-button>
      <a-button type="primary" status="danger" data-test="tool-confirm" @click="handleConfirm">
        {{ t('toolConfirmation.confirm') }}
      </a-button>
    </div>
  </div>
</template>
