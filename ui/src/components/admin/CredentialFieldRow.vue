<script setup lang="ts">
/**
 * 凭证字段行（admin 共用基座）：**状态 + 掩码可见 + 显式编辑**。
 *
 * 为什么抽成组件：内置工具凭证与沙箱凭证是同一交互——「已配置的值加密入库、接口只回掩码」。
 * 若把掩码塞进一个空输入框当 placeholder，观感就是「有值，但框里是空的」（2026-10-08 反馈）。
 * 两处共用同一行渲染，避免各写一套后再次漂移。
 *
 * 交互：
 * - 未编辑：`已配置/未配置` 标签 + **掩码可见** + `替换/填写` 按钮；
 * - 编辑中：输入框（占位提示说明「留空并保存 = 删除该键」）+ `取消` + 待提交提示；
 * - 只提交被编辑过的键由调用方负责（本组件只发事件）。
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppButton from '@/components/AppButton.vue'
import AppTag from '@/components/AppTag.vue'

const props = withDefaults(
  defineProps<{
    /** 凭证键（= 环境变量名） */
    label: string
    /** 是否已配置（后端按掩码是否存在判定） */
    configured: boolean
    /** 已配置值的掩码（后端只回掩码，绝不回明文） */
    mask?: string
    /** 是否处于编辑态（由调用方控制） */
    editing: boolean
    /** 编辑草稿值 */
    draft?: string
    /** 草稿是否被修改过（用于「保存后更新/删除」提示） */
    touched?: boolean
    disabled?: boolean
    /** 可选的来源标签：db（此处配置）/ env（环境变量兜底）/ none */
    source?: 'db' | 'env' | 'none' | ''
    /** 来源标签文案（由调用方翻译，便于各页复用同一组件） */
    sourceLabel?: string
  }>(),
  {
    mask: '',
    draft: '',
    touched: false,
    disabled: false,
    source: '',
    sourceLabel: '',
  },
)

const emit = defineEmits<{
  (e: 'start-edit'): void
  (e: 'cancel-edit'): void
  (e: 'update:value', value: string): void
}>()

const { t } = useI18n()

const inputPlaceholder = computed(() =>
  props.configured
    ? t('common.credential.replacePlaceholder')
    : t('common.credential.inputPlaceholder'),
)

const sourceVariant = computed(() => {
  if (props.source === 'db') return 'success' as const
  if (props.source === 'env') return 'info' as const
  return 'neutral' as const
})
</script>

<template>
  <div class="flex items-center gap-2 flex-wrap">
    <span class="w-48 shrink-0 font-mono text-xs text-gray-600">{{ label }}</span>

    <!-- 编辑中：输入框 + 取消 + 待提交提示 -->
    <template v-if="editing">
      <a-input
        :model-value="draft"
        :disabled="disabled"
        :placeholder="inputPlaceholder"
        class="!w-80"
        size="small"
        allow-clear
        @update:model-value="(value: string) => emit('update:value', value ?? '')"
      />
      <AppButton v-if="!disabled" variant="text" size="mini" @click="emit('cancel-edit')">
        {{ t('common.actions.cancel') }}
      </AppButton>
      <span v-if="touched" class="text-xs text-orange-600">
        {{ draft ? t('common.credential.willUpdate') : t('common.credential.willClear') }}
      </span>
    </template>

    <!-- 未编辑：显式状态 + 掩码（可见，不再只当 placeholder） -->
    <template v-else>
      <AppTag :variant="configured ? 'success' : 'neutral'">
        {{ configured ? t('common.credential.configured') : t('common.credential.empty') }}
      </AppTag>
      <span class="w-72 truncate font-mono text-xs text-gray-500">
        {{ mask || t('common.credential.maskNone') }}
      </span>
      <AppButton v-if="!disabled" size="mini" @click="emit('start-edit')">
        {{ configured ? t('common.credential.replace') : t('common.credential.fill') }}
      </AppButton>
      <AppTag v-if="source && sourceLabel" :variant="sourceVariant">{{ sourceLabel }}</AppTag>
    </template>
  </div>
</template>
