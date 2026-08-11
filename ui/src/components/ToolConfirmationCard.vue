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

const cancelButtonRef = ref<HTMLElement | { $el?: HTMLElement } | null>(null)

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
  const element = cancelButtonRef.value
  if (!element) return
  if (element instanceof HTMLElement) {
    element.focus()
    return
  }
  element.$el?.focus()
})

const handleConfirm = () => emit('confirm', props.prompt.id)
const handleCancel = () => emit('cancel', props.prompt.id)
</script>

<template>
  <div
    class="aicss-tool-confirm"
    :class="`aicss-tool-confirm--${props.prompt.risk_level || 'low'}`"
  >
    <div class="aicss-tool-confirm__head">
      <span class="aicss-tool-confirm__title">{{ t('toolConfirmation.title') }}</span>
      <span class="aicss-tool-confirm__risk">
        <span class="aicss-tool-confirm__risk-label">{{ t('toolConfirmation.riskLevel') }}</span>
        <span class="aicss-tool-confirm__risk-value">{{ props.prompt.risk_level }}</span>
      </span>
    </div>

    <div class="aicss-tool-confirm__tool">{{ props.prompt.tool_name }}</div>
    <div class="aicss-tool-confirm__cost">
      <span class="aicss-tool-confirm__cost-value">{{ props.prompt.spent_credits }}</span>
      <span>{{ t('billing.usage.unit') }}</span>
    </div>

    <dl v-if="optionalMetaRows.length > 0" class="aicss-tool-confirm__meta">
      <div v-for="row in optionalMetaRows" :key="row.label" class="aicss-tool-confirm__meta-row">
        <dt class="aicss-tool-confirm__meta-label">{{ row.label }}</dt>
        <dd class="aicss-tool-confirm__meta-value">{{ row.value }}</dd>
      </div>
    </dl>

    <div class="aicss-tool-confirm__input-label">{{ t('toolConfirmation.toolInput') }}</div>
    <pre class="aicss-tool-confirm__input">{{ props.prompt.tool_input }}</pre>

    <div class="aicss-tool-confirm__actions">
      <button ref="cancelButtonRef" type="button" class="aicss-btn aicss-btn--secondary" data-test="tool-cancel" @click="handleCancel">
        {{ t('toolConfirmation.cancel') }}
      </button>
      <button type="button" class="aicss-btn aicss-btn--danger" data-test="tool-confirm" @click="handleConfirm">
        {{ t('toolConfirmation.confirm') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.aicss-tool-confirm {
  width: 100%;
  max-width: 560px;
  padding: 16px;
  border-radius: 12px;
  background: var(--aicss-surface);
  border: 1px solid var(--aicss-border);
  box-shadow: var(--aicss-shadow-card);
  font-size: 13px;
  line-height: 1.55;
  color: var(--aicss-text);
}

.aicss-tool-confirm--high,
.aicss-tool-confirm--sensitive {
  border-color: color-mix(in srgb, var(--aicss-danger) 32%, var(--aicss-border));
}

.aicss-tool-confirm--medium {
  border-color: color-mix(in srgb, var(--aicss-warning) 32%, var(--aicss-border));
}

.aicss-tool-confirm__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.aicss-tool-confirm__title {
  font-weight: 650;
  color: var(--aicss-text);
}

.aicss-tool-confirm__risk {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.aicss-tool-confirm__risk-label {
  color: var(--aicss-muted);
}

.aicss-tool-confirm__risk-value {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--aicss-surface-2);
  border: 1px solid var(--aicss-border);
  color: var(--aicss-text-2);
  text-transform: uppercase;
  font-size: 11px;
}

.aicss-tool-confirm--high .aicss-tool-confirm__risk-value,
.aicss-tool-confirm--sensitive .aicss-tool-confirm__risk-value {
  background: var(--aicss-danger-soft);
  border-color: color-mix(in srgb, var(--aicss-danger) 26%, transparent);
  color: var(--aicss-danger);
}

.aicss-tool-confirm--medium .aicss-tool-confirm__risk-value {
  background: var(--aicss-warning-soft);
  border-color: color-mix(in srgb, var(--aicss-warning) 26%, transparent);
  color: var(--aicss-warning);
}

.aicss-tool-confirm__tool {
  margin-bottom: 6px;
  font-weight: 600;
  color: var(--aicss-text);
  overflow-wrap: anywhere;
}

.aicss-tool-confirm__cost {
  margin-bottom: 12px;
  color: var(--aicss-muted);
}

.aicss-tool-confirm__cost-value {
  font-weight: 650;
  color: var(--aicss-accent-text);
  margin-right: 2px;
}

.aicss-tool-confirm__meta {
  margin: 0 0 12px;
}

.aicss-tool-confirm__meta-row {
  display: flex;
  gap: 10px;
  padding: 3px 0;
}

.aicss-tool-confirm__meta-label {
  flex: none;
  width: 96px;
  color: var(--aicss-muted);
}

.aicss-tool-confirm__meta-value {
  min-width: 0;
  color: var(--aicss-text-2);
  overflow-wrap: anywhere;
}

.aicss-tool-confirm__input-label {
  margin-bottom: 6px;
  color: var(--aicss-muted);
}

.aicss-tool-confirm__input {
  margin: 0 0 14px;
  max-height: 160px;
  overflow: auto;
  padding: 10px 12px;
  border-radius: 9px;
  background: var(--aicss-bg-subtle);
  border: 1px solid var(--aicss-border);
  color: var(--aicss-text-2);
  font-family: var(--aicss-mono);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.aicss-tool-confirm__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
