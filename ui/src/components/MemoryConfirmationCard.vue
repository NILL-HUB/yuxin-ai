<script setup lang="ts">
import type { MemoryCandidatePrompt } from '@/models/memory'

const props = defineProps<{
  candidate: MemoryCandidatePrompt
}>()

const emit = defineEmits<{
  confirm: [id: string]
  ignore: [id: string]
  'never-remind': [id: string]
}>()
</script>

<template>
  <div class="rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm text-gray-800 shadow-sm">
    <div class="mb-2 font-semibold text-gray-900">是否保存这条长期记忆？</div>
    <div class="mb-3 text-gray-700">{{ props.candidate.content }}</div>
    <div class="mb-4 text-xs text-gray-500">
      已高置信出现 {{ props.candidate.occurrences }} 次，置信度 {{ props.candidate.confidence }}
    </div>
    <div class="flex flex-wrap gap-2">
      <button
        data-test="memory-confirm"
        class="rounded-lg bg-blue-600 px-3 py-1.5 text-white hover:bg-blue-700"
        type="button"
        @click="emit('confirm', props.candidate.id)"
      >
        保存
      </button>
      <button
        data-test="memory-ignore"
        class="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-gray-700 hover:bg-gray-50"
        type="button"
        @click="emit('ignore', props.candidate.id)"
      >
        暂不保存
      </button>
      <button
        data-test="memory-never-remind"
        class="rounded-lg px-3 py-1.5 text-gray-500 hover:bg-white/60"
        type="button"
        @click="emit('never-remind', props.candidate.id)"
      >
        不再提醒
      </button>
    </div>
  </div>
</template>
