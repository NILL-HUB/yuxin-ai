<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

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

const tags = computed<string[]>(() => {
  const value = props.modelValue
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item ?? '').trim()).filter(Boolean)
})

const handleChange = (value: (string | number | Record<string, unknown>)[]) => {
  emits(
    'update:modelValue',
    (value || []).map((item) => String(item ?? '').trim()).filter(Boolean),
  )
}
</script>

<template>
  <a-input-tag
    :model-value="tags"
    :placeholder="placeholder || t('configEditors.addItem')"
    :readonly="readonly"
    :disabled="readonly"
    allow-clear
    @change="handleChange"
  />
</template>
