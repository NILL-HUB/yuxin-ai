<script setup lang="ts">
import type { ToolConfirmationPrompt } from '@/models/tool-confirmation'

const props = defineProps<{
  prompt: ToolConfirmationPrompt
}>()

const emit = defineEmits<{
  confirm: [id: string]
  cancel: [id: string]
}>()
</script>

<template>
  <div class="rounded-xl border border-orange-200 bg-orange-50 p-4 text-sm text-gray-800 shadow-sm">
    <div class="mb-2 font-semibold text-orange-900">高风险工具执行确认</div>
    <div class="mb-2 text-gray-700">
      工具：<span class="font-medium">{{ props.prompt.tool_name }}</span>
    </div>
    <div class="mb-2 text-gray-700">
      风险等级：<span class="font-medium">{{ props.prompt.risk_level }}</span>
    </div>
    <div class="mb-4 text-gray-700">
      预计消耗：<span class="font-medium">{{ props.prompt.spent_credits }}</span> credits
    </div>
    <pre class="mb-4 max-h-40 overflow-auto rounded-lg bg-white/70 p-3 text-xs text-gray-600">{{ props.prompt.tool_input }}</pre>
    <div class="flex flex-wrap gap-2">
      <button
        data-test="tool-confirm"
        class="rounded-lg bg-orange-600 px-3 py-1.5 text-white hover:bg-orange-700"
        type="button"
        @click="emit('confirm', props.prompt.id)"
      >
        确认执行
      </button>
      <button
        data-test="tool-cancel"
        class="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-gray-700 hover:bg-gray-50"
        type="button"
        @click="emit('cancel', props.prompt.id)"
      >
        取消
      </button>
    </div>
  </div>
</template>
