<script setup lang="ts">
import type { DeepThinkingProposal } from '@/views/shared/chat-stream'

defineProps<{ proposal: DeepThinkingProposal | null }>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()
</script>

<template>
  <div
    v-if="proposal"
    data-test="deep-thinking-proposal-card"
    class="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-gray-800 shadow-sm"
  >
    <div class="mb-2 font-semibold text-amber-900">建议进行深度思考</div>
    <p class="mb-2 text-amber-700">{{ proposal.reason }}</p>
    <p v-if="proposal.estimated_steps" class="mb-4 text-xs text-amber-600">
      预计步骤：{{ proposal.estimated_steps }} 步
    </p>
    <div class="flex flex-wrap gap-2">
      <button
        data-test="deep-thinking-confirm"
        class="rounded-lg bg-amber-600 px-3 py-1.5 text-white hover:bg-amber-700"
        type="button"
        @click="emit('confirm')"
      >
        确认深度思考
      </button>
      <button
        data-test="deep-thinking-cancel"
        class="rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-amber-700 hover:bg-amber-100"
        type="button"
        @click="emit('cancel')"
      >
        取消
      </button>
    </div>
  </div>
</template>
