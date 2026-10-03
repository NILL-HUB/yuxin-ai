<script setup lang="ts">
/**
 * 统一按钮组件：全站按钮的唯一入口。
 *
 * 颜色与圆角一律来自主题 token（--aicss-* / Arco 主色链），
 * 调用方只选语义（variant / status / size），禁止在调用处写颜色样式。
 */
import { computed } from 'vue'

type AppButtonVariant = 'primary' | 'secondary' | 'outline' | 'text' | 'ghost' | 'danger'
type AppButtonStatus = 'normal' | 'danger' | 'warning' | 'success'

const props = withDefaults(
  defineProps<{
    /** 语义类型：primary 主操作 / secondary 次操作 / outline 描边 / text 纯文字 / ghost 图标位 / danger 危险主操作 */
    variant?: AppButtonVariant
    /** 叠加状态色：text/ghost + danger 即列表内的删除类操作 */
    status?: AppButtonStatus
    size?: 'mini' | 'small' | 'medium' | 'large'
    /** 仅图标：渲染为圆形，配合 icon 插槽或默认插槽使用 */
    iconOnly?: boolean
    loading?: boolean
    disabled?: boolean
    htmlType?: 'button' | 'submit' | 'reset'
  }>(),
  {
    variant: 'secondary',
    status: 'normal',
    size: 'medium',
    iconOnly: false,
    loading: false,
    disabled: false,
    htmlType: 'button',
  },
)

const emit = defineEmits<{ (e: 'click', ev: MouseEvent): void }>()

const arcoType = computed(() => {
  switch (props.variant) {
    case 'primary':
    case 'danger':
      return 'primary'
    case 'outline':
      return 'outline'
    case 'text':
    case 'ghost':
      return 'text'
    default:
      return 'secondary'
  }
})

const arcoStatus = computed(() => {
  if (props.variant === 'danger') return 'danger'
  return props.status === 'normal' ? undefined : props.status
})

const onClick = (ev: MouseEvent) => {
  if (props.disabled || props.loading) return
  emit('click', ev)
}
</script>

<template>
  <a-button
    class="app-button"
    :class="[`app-button--${variant}`, { 'app-button--icon-only': iconOnly }]"
    :type="arcoType"
    :status="arcoStatus"
    :size="size"
    :shape="iconOnly ? 'circle' : undefined"
    :loading="loading"
    :disabled="disabled"
    :html-type="htmlType"
    @click="onClick"
  >
    <template v-if="$slots.icon" #icon>
      <slot name="icon" />
    </template>
    <slot />
  </a-button>
</template>

<style scoped>
/* 圆角跟随主题；重复类名提升特异度以稳定覆盖 arco 默认圆角 */
.app-button.app-button {
  border-radius: var(--aicss-radius-sm, 8px);
}

/* ghost：透明无边框，hover 出现品牌浅底（卡片 hover 操作位） */
.app-button--ghost.app-button--ghost {
  color: var(--aicss-muted);
}

.app-button--ghost.app-button--ghost:hover {
  color: var(--aicss-accent);
  background: var(--aicss-accent-soft);
}

/* 仅图标时不额外撑宽，靠 arco 圆形径向尺寸 */
.app-button--icon-only.app-button--icon-only {
  padding: 0;
}
</style>
