<script setup lang="ts">
/**
 * 确认弹窗基座：危险/重要操作的统一确认交互（标题 + 说明 + 目标名 + 取消/确认）。
 *
 * 外壳与按钮区复用 AppModal；确认按钮默认 danger（删除类），可切换 primary；
 * 文案默认取 common 键，可由调用方覆盖。
 */
import AppModal from '@/components/AppModal.vue'

withDefaults(
  defineProps<{
    visible: boolean
    title: string
    message?: string
    /** 操作目标名称（如文件名） */
    target?: string
    confirmText?: string
    cancelText?: string
    /** danger 删除类操作（默认） / primary 普通确认 */
    confirmVariant?: 'primary' | 'danger'
    loading?: boolean
  }>(),
  {
    message: '',
    target: '',
    confirmText: '',
    cancelText: '',
    confirmVariant: 'danger',
    loading: false,
  },
)

const emit = defineEmits<{ (e: 'update:visible', value: boolean): void; (e: 'confirm'): void }>()
</script>

<template>
  <AppModal
    :visible="visible"
    :title="title"
    :cancel-text="cancelText"
    :confirm-text="confirmText"
    :confirm-variant="confirmVariant"
    :loading="loading"
    @update:visible="emit('update:visible', $event)"
    @confirm="emit('confirm')"
  >
    <p v-if="message" class="app-confirm__message">{{ message }}</p>
    <p v-if="target" class="app-confirm__target">{{ target }}</p>
    <slot />
  </AppModal>
</template>

<style scoped>
.app-confirm__message {
  margin: 0;
  font-size: 13px;
  color: var(--aicss-text-2);
}

.app-confirm__target {
  margin: 8px 0 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--aicss-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
