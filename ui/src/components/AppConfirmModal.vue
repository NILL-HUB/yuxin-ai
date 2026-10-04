<script setup lang="ts">
/**
 * 确认弹窗基座：危险/重要操作的统一确认交互（标题 + 说明 + 目标名 + 取消/确认）。
 *
 * 按钮统一走 AppButton；确认按钮默认 danger（删除类），可切换 primary；
 * 文案默认取 common 键，可由调用方覆盖。
 */
import { useI18n } from 'vue-i18n'
import AppButton from '@/components/AppButton.vue'

const props = withDefaults(
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

const { t } = useI18n()

const close = () => emit('update:visible', false)
</script>

<template>
  <a-modal :visible="visible" :title="title" :footer="false" @cancel="close">
    <p v-if="message" class="app-confirm__message">{{ message }}</p>
    <p v-if="target" class="app-confirm__target">{{ target }}</p>
    <slot />
    <div class="app-confirm__footer">
      <AppButton variant="text" @click="close">
        {{ cancelText || t('common.cancel') }}
      </AppButton>
      <AppButton :variant="confirmVariant" :loading="loading" @click="emit('confirm')">
        {{ confirmText || t('common.actions.confirm') }}
      </AppButton>
    </div>
  </a-modal>
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

.app-confirm__footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}
</style>
