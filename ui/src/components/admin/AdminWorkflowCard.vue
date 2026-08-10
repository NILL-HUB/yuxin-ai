<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { AdminWorkflowRecord } from '@/models/admin-workflow'

/**
 * 后台工作流卡片，展示单条工作流摘要和可执行动作。
 */
const props = withDefaults(
  defineProps<{
    workflow: AdminWorkflowRecord
    canUpdate: boolean
    canDelete?: boolean
    canEdit?: boolean
  }>(),
  {
    canDelete: undefined,
    canEdit: true,
  },
)

const emit = defineEmits<{
  (event: 'edit', workflowId: string): void
  (event: 'toggle-public', workflow: AdminWorkflowRecord): void
  (event: 'offline', workflow: AdminWorkflowRecord): void
  (event: 'delete', workflow: AdminWorkflowRecord): void
  (event: 'export', workflow: AdminWorkflowRecord): void
}>()

const { t } = useI18n()

const visibilityLabel = computed(() => {
  return props.workflow.is_public
    ? t('admin.workflowsAdmin.visibility.public')
    : t('admin.workflowsAdmin.visibility.private')
})

const visibilityActionLabel = computed(() => {
  return props.workflow.is_public
    ? t('admin.workflowsAdmin.actions.makePrivate')
    : t('admin.workflowsAdmin.actions.makePublic')
})
</script>

<template>
  <article class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
    <div class="flex items-start justify-between gap-4">
      <div class="min-w-0">
        <h3 class="truncate text-lg font-semibold text-slate-900">{{ workflow.name }}</h3>
        <p class="mt-1 text-sm text-slate-500">{{ workflow.tool_call_name }}</p>
        <p class="mt-3 line-clamp-2 text-sm text-slate-600">
          {{ workflow.description || t('admin.workflowsAdmin.noDescription') }}
        </p>
        <p class="mt-2 text-xs text-slate-400">
          {{ t('admin.workflowsAdmin.creator') }}: {{ workflow.creator_name || '-' }}
        </p>
      </div>
      <div class="flex shrink-0 flex-col items-end gap-2 text-xs text-slate-500">
        <span class="rounded-full bg-slate-100 px-2 py-1">{{ workflow.status }}</span>
        <span>{{ visibilityLabel }}</span>
      </div>
    </div>

    <div class="mt-4 flex flex-wrap gap-2">
      <a-button
        v-if="canEdit"
        type="primary"
        :data-testid="`workflow-edit-${workflow.id}`"
        @click="emit('edit', workflow.id)"
      >
        {{ t('admin.workflowsAdmin.actions.edit') }}
      </a-button>
      <a-button
        v-if="canUpdate"
        :data-testid="`workflow-visibility-${workflow.id}`"
        @click="emit('toggle-public', workflow)"
      >
        {{ visibilityActionLabel }}
      </a-button>
      <a-button
        :data-testid="`workflow-export-${workflow.id}`"
        @click="emit('export', workflow)"
      >
        {{ t('admin.workflowsAdmin.actions.export') }}
      </a-button>
      <a-button
        v-if="canUpdate"
        status="danger"
        :data-testid="`workflow-offline-${workflow.id}`"
        @click="emit('offline', workflow)"
      >
        {{ t('admin.workflowsAdmin.actions.offline') }}
      </a-button>
      <a-button
        v-if="canDelete ?? canUpdate"
        status="danger"
        type="outline"
        :data-testid="`workflow-delete-${workflow.id}`"
        @click="emit('delete', workflow)"
      >
        {{ t('admin.workflowsAdmin.actions.delete') }}
      </a-button>
    </div>
  </article>
</template>
