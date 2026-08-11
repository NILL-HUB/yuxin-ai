<script setup lang="ts">
import type { DeepThinkingProposal } from '@/views/shared/chat-stream'

defineProps<{ proposal: DeepThinkingProposal | null }>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()
</script>

<template>
  <div
    v-if="proposal"
    data-test="deep-thinking-proposal-card"
    class="aicss-proposal-card aicss-proposal-card--thinking"
  >
    <div class="aicss-proposal-card__title">建议进行深度思考</div>
    <p class="aicss-proposal-card__reason">{{ proposal.reason }}</p>
    <p v-if="proposal.estimated_steps" class="aicss-proposal-card__meta">
      预计步骤：{{ proposal.estimated_steps }} 步
    </p>
    <div class="aicss-proposal-card__actions">
      <button
        data-test="deep-thinking-confirm"
        class="aicss-btn aicss-btn--primary"
        type="button"
        @click="emit('confirm')"
      >
        确认深度思考
      </button>
      <button
        data-test="deep-thinking-cancel"
        class="aicss-btn aicss-btn--secondary"
        type="button"
        @click="emit('cancel')"
      >
        取消
      </button>
    </div>
  </div>
</template>

<style scoped>
.aicss-proposal-card {
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

.aicss-proposal-card--thinking {
  border-color: color-mix(in srgb, var(--aicss-warning) 30%, var(--aicss-border));
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--aicss-warning-soft) 42%, var(--aicss-surface)), var(--aicss-surface));
}

.aicss-proposal-card__title {
  margin-bottom: 8px;
  font-weight: 650;
  color: var(--aicss-text);
}

.aicss-proposal-card__reason {
  margin: 0 0 8px;
  color: var(--aicss-text-2);
}

.aicss-proposal-card__meta {
  margin: 0 0 14px;
  font-size: 12px;
  color: var(--aicss-muted);
}

.aicss-proposal-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
