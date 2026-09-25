<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { IconPlus, IconDelete, IconUp, IconDown } from '@arco-design/web-vue/es/icon'

const props = withDefaults(
  defineProps<{
    modelValue: string[]
    placeholder?: string
    readonly?: boolean
  }>(),
  {
    placeholder: '',
    readonly: false,
  },
)

const emits = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

const { t } = useI18n()

const items = computed<string[]>(() => {
  const value = props.modelValue
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item ?? ''))
})

const commit = (next: string[]) => {
  emits('update:modelValue', next)
}

const updateAt = (index: number, value: string) => {
  const next = [...items.value]
  next[index] = value
  commit(next)
}

const addItem = () => {
  if (props.readonly) return
  commit([...items.value, ''])
}

const removeItem = (index: number) => {
  if (props.readonly) return
  commit(items.value.filter((_, idx) => idx !== index))
}

const moveItem = (index: number, delta: number) => {
  const target = index + delta
  if (target < 0 || target >= items.value.length) return
  const next = [...items.value]
  const [moved] = next.splice(index, 1)
  next.splice(target, 0, moved)
  commit(next)
}
</script>

<template>
  <div class="space-y-2">
    <div
      v-for="(item, index) in items"
      :key="index"
      class="flex items-center gap-2"
    >
      <span class="w-6 shrink-0 text-center text-xs text-gray-400">{{ index + 1 }}</span>
      <a-input
        :model-value="item"
        class="flex-1"
        :placeholder="placeholder || t('configEditors.argPlaceholder')"
        :readonly="readonly"
        :disabled="readonly"
        allow-clear
        @update:model-value="(value: string) => updateAt(index, value)"
      />
      <template v-if="!readonly">
        <a-button type="text" size="small" data-testid="arg-up" :disabled="index === 0" @click="moveItem(index, -1)">
          <template #icon><icon-up /></template>
        </a-button>
        <a-button
          type="text"
          size="small"
          data-testid="arg-down"
          :disabled="index === items.length - 1"
          @click="moveItem(index, 1)"
        >
          <template #icon><icon-down /></template>
        </a-button>
        <a-button type="text" size="small" status="danger" data-testid="arg-delete" @click="removeItem(index)">
          <template #icon><icon-delete /></template>
        </a-button>
      </template>
    </div>

    <a-button v-if="!readonly" type="text" size="small" data-testid="arg-add" @click="addItem">
      <template #icon><icon-plus /></template>
      {{ t('configEditors.addArg') }}
    </a-button>

    <div v-if="!items.length && readonly" class="text-xs text-gray-400">
      {{ t('configEditors.empty') }}
    </div>
  </div>
</template>
