<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { SubtaskProgress, StreamState } from '@/views/shared/chat-stream'

defineProps({
  subtasks: {
    type: Array as () => SubtaskProgress[] | null,
    default: null,
  },
  taskPlan: {
    type: Object as () => StreamState['taskPlan'] | null,
    default: null,
  },
})

const { t } = useI18n()
</script>

<template>
  <div
    v-if="subtasks && subtasks.length > 0"
    class="subtask-progress-panel w-full rounded-lg border border-cyan-100 bg-white/70 backdrop-blur-md px-3 py-2.5"
  >
    <div class="flex items-center justify-between gap-2">
      <span class="text-xs font-semibold text-gray-700">
        {{ t('home.orchestration.taskPlan') }}
      </span>
      <span class="truncate text-xs text-gray-400">
        {{ taskPlan?.execution_mode || '' }}
      </span>
    </div>
    <ul class="mt-2 space-y-1.5">
      <li
        v-for="subtask in subtasks"
        :key="subtask.task_id"
        class="flex flex-col gap-0.5 rounded-md bg-white/70 px-2 py-1.5"
      >
        <div class="flex items-center gap-2 min-w-0">
          <span
            class="h-2 w-2 flex-shrink-0 rounded-full"
            :class="{
              'bg-gray-300': subtask.status === 'pending',
              'bg-cyan-500 animate-pulse': subtask.status === 'running',
              'bg-green-500': subtask.status === 'completed',
              'bg-red-500': subtask.status === 'failed',
            }"
          />
          <span class="min-w-0 flex-1 truncate text-xs text-gray-700">
            {{ subtask.title }}
          </span>
          <span class="flex-shrink-0 text-xs text-gray-500">
            {{ t(`home.orchestration.subtaskStatus.${subtask.status}`) }}
          </span>
        </div>
        <p
          v-if="subtask.answer_preview || (subtask.errors && subtask.errors.length > 0)"
          class="truncate pl-4 text-xs text-gray-400"
        >
          {{ subtask.errors && subtask.errors.length > 0 ? subtask.errors.join('; ') : subtask.answer_preview }}
        </p>
        <p
          v-if="subtask.timed_out"
          class="pl-4 text-xs text-red-500"
        >
          {{ t('home.orchestration.subtaskTimedOut') }}
        </p>
        <p
          v-else-if="subtask.stall_warning"
          class="pl-4 text-xs text-amber-500"
        >
          {{ t('home.orchestration.subtaskStalled') }}
        </p>
      </li>
    </ul>
  </div>
</template>
