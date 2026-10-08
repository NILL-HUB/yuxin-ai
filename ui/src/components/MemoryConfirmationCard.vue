<script setup lang="ts">
/**
 * 机密记忆读取确认卡片（AppCard / AppButton / AppTag 基座派生）。
 *
 * 展示本次召回命中的机密记忆（脱敏预览 + 类型标签），用户允许后 30 分钟内
 * 后端可直接注入同一批记忆。类型标签走 i18n（memoryConfirmation.types.*），
 * 后端下发的 label 仅作为未知类型的兜底，保证中英文切换一致。
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppButton from '@/components/AppButton.vue'
import AppCard from '@/components/AppCard.vue'
import AppTag from '@/components/AppTag.vue'
import type { MemoryConfirmationItem, MemoryConfirmationStatus } from '@/models/memory-confirmation'

const props = withDefaults(
  defineProps<{
    items: MemoryConfirmationItem[]
    status?: MemoryConfirmationStatus
    loading?: boolean
  }>(),
  { status: 'pending', loading: false },
)

const emit = defineEmits<{ allow: []; deny: [] }>()

const { t, te } = useI18n()

const isDone = computed(() => props.status === 'confirmed' || props.status === 'cancelled')

const statusLabel = computed(() => {
  if (props.status === 'confirmed') return t('memoryConfirmation.allowed')
  if (props.status === 'cancelled') return t('memoryConfirmation.denied')
  return ''
})

const statusVariant = computed<'success' | 'neutral'>(() =>
  props.status === 'confirmed' ? 'success' : 'neutral',
)

/** 类型标签：优先 i18n；未知类型回退后端中文 label，仍无则展示原始 type */
const itemTypeLabels = (item: MemoryConfirmationItem): string[] => {
  const labels = (item.types || []).map((type) => {
    const key = `memoryConfirmation.types.${type}`
    return te(key) ? t(key) : ''
  })
  const known = labels.filter(Boolean)
  if (known.length > 0) return known
  if (item.label) return [item.label]
  return item.types || []
}
</script>

<template>
  <AppCard class="memory-confirm" variant="surface" padding="medium">
    <template #title>
      <span class="memory-confirm__title">{{ t('memoryConfirmation.title') }}</span>
    </template>
    <template v-if="isDone && statusLabel" #meta>
      <AppTag :variant="statusVariant" size="small">{{ statusLabel }}</AppTag>
    </template>

    <p class="memory-confirm__desc">{{ t('memoryConfirmation.desc') }}</p>

    <ul v-if="props.items.length > 0" class="memory-confirm__items">
      <li
        v-for="(item, index) in props.items"
        :key="item.memory_id || `memory-item-${index}`"
        class="memory-confirm__item"
      >
        <span class="memory-confirm__types">
          <AppTag
            v-for="label in itemTypeLabels(item)"
            :key="label"
            variant="warning"
            size="small"
          >
            {{ label }}
          </AppTag>
        </span>
        <code class="memory-confirm__preview">{{ item.preview }}</code>
      </li>
    </ul>

    <p v-if="props.status === 'confirmed'" class="memory-confirm__hint" data-test="memory-allowed-hint">
      {{ t('memoryConfirmation.needAskAgain') }}
    </p>
    <p v-else-if="props.status === 'cancelled'" class="memory-confirm__hint">
      {{ t('memoryConfirmation.denied') }}
    </p>

    <div v-if="!isDone" class="memory-confirm__actions">
      <AppButton
        variant="secondary"
        size="small"
        :disabled="props.loading"
        data-test="memory-deny"
        @click="emit('deny')"
      >
        {{ t('memoryConfirmation.deny') }}
      </AppButton>
      <AppButton
        variant="primary"
        size="small"
        :loading="props.loading"
        :disabled="props.loading"
        data-test="memory-allow"
        @click="emit('allow')"
      >
        {{ t('memoryConfirmation.allow') }}
      </AppButton>
    </div>
  </AppCard>
</template>

<style scoped>
.memory-confirm {
  width: 100%;
  font-size: 13px;
  line-height: 1.55;
}

.memory-confirm__title {
  font-weight: 650;
  color: var(--aicss-text);
}

.memory-confirm__desc {
  margin: 0;
  color: var(--aicss-muted);
  font-size: 12px;
}

.memory-confirm__items {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.memory-confirm__item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius-sm, 8px);
  background: var(--aicss-bg-subtle);
}

.memory-confirm__types {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.memory-confirm__preview {
  color: var(--aicss-text-2);
  font-family: var(--aicss-mono);
  font-size: 12px;
  word-break: break-word;
  white-space: pre-wrap;
}

.memory-confirm__hint {
  margin: 0;
  color: var(--aicss-accent-text, var(--aicss-accent));
  font-size: 12px;
}

.memory-confirm__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 2px;
}
</style>
