<script setup lang="ts">
/**
 * 语义标签基座：统一「来源 / 状态」类小标签的样式（胶囊形、无外边距）与语义色。
 *
 * 调用方只选语义（variant），不再逐处写 Arco color 枚举与 tailwind 覆盖类；
 * brand 走主题主色链（body 层 --arcoblue-*），随主题联动。
 */
import { computed } from 'vue'

type AppTagVariant = 'brand' | 'neutral' | 'success' | 'warning' | 'danger' | 'info'

const props = withDefaults(
  defineProps<{
    variant?: AppTagVariant
    size?: 'small' | 'medium'
  }>(),
  { variant: 'neutral', size: 'small' },
)

const ARCO_COLOR: Record<AppTagVariant, string> = {
  brand: 'arcoblue',
  neutral: 'gray',
  success: 'green',
  warning: 'orange',
  danger: 'red',
  info: 'cyan',
}

const color = computed(() => ARCO_COLOR[props.variant])
</script>

<template>
  <a-tag class="app-tag" :color="color" :size="size">
    <slot />
  </a-tag>
</template>

<style scoped>
.app-tag.app-tag {
  margin: 0;
  border-radius: 999px;
  padding: 0 8px;
  line-height: 1.6;
}
</style>
