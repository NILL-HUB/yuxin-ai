<script setup lang="ts">
import { useI18n } from 'vue-i18n'

/**
 * 后台工作流工具栏，负责搜索、状态筛选和主动刷新。
 */
defineProps<{
  search: string
  status: string
  loading: boolean
}>()

const emit = defineEmits<{
  (event: 'update:search', value: string): void
  (event: 'update:status', value: string): void
  (event: 'refresh'): void
}>()

const { t } = useI18n()
</script>

<template>
  <div class="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm lg:flex-row lg:items-center">
    <a-input
      :model-value="search"
      :placeholder="t('admin.workflowsAdmin.searchPlaceholder')"
      allow-clear
      @update:model-value="emit('update:search', String($event ?? ''))"
    />
    <a-select
      :model-value="status"
      @update:model-value="emit('update:status', String($event ?? ''))"
    >
      <a-option value="">{{ t('admin.workflowsAdmin.filters.allStatuses') }}</a-option>
      <a-option value="draft">{{ t('admin.workflowsAdmin.filters.draft') }}</a-option>
      <a-option value="published">{{ t('admin.workflowsAdmin.filters.published') }}</a-option>
      <a-option value="offline">{{ t('admin.workflowsAdmin.filters.offline') }}</a-option>
    </a-select>
    <a-button type="primary" :loading="loading" @click="emit('refresh')">
      {{ t('common.actions.refresh') }}
    </a-button>
  </div>
</template>
