<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

/**
 * 统一删除确认弹窗：提示资源将进入回收站，并选择留存（销毁）天数。
 *
 * 后端约定：管理员删除资源统一走回收站，留存天数仅允许 7/30/90/180（默认 30）。
 */
const props = withDefaults(
  defineProps<{
    visible: boolean
    title?: string
    resourceName?: string
    loading?: boolean
  }>(),
  {
    title: '',
    resourceName: '',
    loading: false,
  },
)

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'confirm', retentionDays: number): void
}>()

const { t } = useI18n()

const RETENTION_CHOICES = [7, 30, 90, 180]
const retentionDays = ref(30)

watch(
  () => props.visible,
  (visible) => {
    if (visible) retentionDays.value = 30
  },
)

const handleOk = () => {
  emit('confirm', retentionDays.value)
}
</script>

<template>
  <a-modal
    :visible="visible"
    :title="title || t('common.actions.delete')"
    :confirm-loading="loading"
    :ok-text="t('common.actions.delete')"
    :cancel-text="t('common.actions.cancel')"
    @ok="handleOk"
    @cancel="emit('update:visible', false)"
  >
    <div class="space-y-3">
      <div v-if="resourceName" class="truncate rounded-lg bg-gray-50 px-3 py-2 text-sm font-medium text-gray-800">
        {{ resourceName }}
      </div>
      <slot />
      <div class="rounded-lg border border-amber-100 bg-amber-50/60 px-3 py-2.5">
        <div class="flex flex-wrap items-center gap-3">
          <span class="shrink-0 text-sm text-slate-600">
            {{ t('admin.recycleBin.retentionLabel') }}
          </span>
          <a-radio-group v-model="retentionDays" type="button" size="small" class="flex-wrap">
            <a-radio v-for="d in RETENTION_CHOICES" :key="d" :value="d">
              {{ d }} {{ t('admin.recycleBin.retentionDaysUnit') }}
            </a-radio>
          </a-radio-group>
        </div>
        <p class="mt-2 text-xs text-slate-500">
          {{ t('admin.recycleBin.deleteConfirmHint') }}
        </p>
        <p class="mt-1 text-xs text-amber-600">
          {{ t('admin.recycleBin.retentionHint') }}
        </p>
      </div>
    </div>
  </a-modal>
</template>
