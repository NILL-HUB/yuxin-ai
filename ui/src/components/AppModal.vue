<script setup lang="ts">
/**
 * 弹窗外壳基座：统一的弹窗容器与底部操作区（取消 / 确认 + loading / 危险变体）。
 *
 * 内容经默认插槽传入；确认类弹窗（AppConfirmModal）与表单/选择类弹窗均基于本基座，
 * 避免各页面重复实现 footer 按钮区与文案默认值。
 */
import { useI18n } from 'vue-i18n'
import AppButton from '@/components/AppButton.vue'

withDefaults(
  defineProps<{
    visible: boolean
    title?: string
    cancelText?: string
    confirmText?: string
    confirmVariant?: 'primary' | 'danger'
    loading?: boolean
    /** 隐藏底部操作区（纯展示弹窗） */
    hideFooter?: boolean
    width?: number | string
  }>(),
  {
    title: '',
    cancelText: '',
    confirmText: '',
    confirmVariant: 'primary',
    loading: false,
    hideFooter: false,
    width: undefined,
  },
)

const emit = defineEmits<{ (e: 'update:visible', value: boolean): void; (e: 'confirm'): void }>()

const { t } = useI18n()

const close = () => emit('update:visible', false)
</script>

<template>
  <a-modal :visible="visible" :title="title" :footer="false" :width="width" @cancel="close">
    <slot />
    <div v-if="!hideFooter" class="app-modal__footer">
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
.app-modal__footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}
</style>
