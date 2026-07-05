<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { APP_TYPE_OPTIONS, type AppType } from '@/models/app'

// 应用类型选择器：用于创建应用时选择应用类型，编辑模式下应禁用
const props = defineProps({
  modelValue: { type: String as () => AppType, default: 'chatbot' },
  disabled: { type: Boolean, default: false },
})
const emits = defineEmits(['update:modelValue'])

const { locale } = useI18n()

// 根据当前语言返回中/英文标签与描述
const isZh = computed(() => locale.value === 'zh-CN')
const options = computed(() =>
  APP_TYPE_OPTIONS.map((opt) => ({
    value: opt.value,
    label: isZh.value ? opt.label : opt.labelEn,
    description: isZh.value ? opt.description : opt.descriptionEn,
    icon: opt.icon,
  })),
)

// 点击卡片时触发选中事件（禁用状态下不触发）
const handleChange = (value: AppType) => {
  if (!props.disabled) {
    emits('update:modelValue', value)
  }
}
</script>

<template>
  <div class="app-type-selector">
    <div
      v-for="opt in options"
      :key="opt.value"
      class="app-type-card"
      :class="{
        active: modelValue === opt.value,
        disabled: disabled,
      }"
      @click="handleChange(opt.value)"
    >
      <div class="app-type-card-header">
        <component :is="opt.icon" class="app-type-card-icon" />
        <span class="app-type-card-title">{{ opt.label }}</span>
        <icon-check v-if="modelValue === opt.value" class="app-type-card-check" />
      </div>
      <p class="app-type-card-desc">{{ opt.description }}</p>
    </div>
  </div>
</template>

<style scoped>
.app-type-selector {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}
.app-type-card {
  border: 1px solid var(--color-border-2);
  border-radius: 8px;
  padding: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.app-type-card:hover {
  border-color: rgb(var(--primary-6));
}
.app-type-card.active {
  border-color: rgb(var(--primary-6));
  background-color: rgb(var(--primary-1));
}
.app-type-card.disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.app-type-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.app-type-card-icon {
  font-size: 18px;
  color: rgb(var(--primary-6));
  flex-shrink: 0;
}
.app-type-card-title {
  font-weight: 500;
  flex: 1;
}
.app-type-card-check {
  color: rgb(var(--primary-6));
  flex-shrink: 0;
}
.app-type-card-desc {
  font-size: 12px;
  color: var(--color-text-3);
  margin: 0;
}
</style>
