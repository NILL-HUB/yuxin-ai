<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { IconPlus, IconDelete, IconEdit } from '@arco-design/web-vue/es/icon'
import type { KeyValueItem } from './types'

const props = withDefaults(
  defineProps<{
    modelValue: KeyValueItem[]
    secret?: boolean
    keyPlaceholder?: string
    valuePlaceholder?: string
    readonly?: boolean
  }>(),
  {
    secret: false,
    keyPlaceholder: '',
    valuePlaceholder: '',
    readonly: false,
  },
)

const emits = defineEmits<{
  (e: 'update:modelValue', value: KeyValueItem[]): void
}>()

const { t } = useI18n()

const editingIndex = ref<number>(-1)
const draft = ref<KeyValueItem>({ key: '', value: '' })

const items = computed<KeyValueItem[]>(() => (Array.isArray(props.modelValue) ? props.modelValue : []))

const commit = (next: KeyValueItem[]) => {
  emits('update:modelValue', next.map((item) => ({ key: item.key, value: item.value })))
}

const startEdit = (index: number) => {
  if (props.readonly) return
  editingIndex.value = index
  const item = items.value[index]
  draft.value = { key: item?.key ?? '', value: props.secret ? '' : item?.value ?? '' }
}

const cancelEdit = () => {
  editingIndex.value = -1
  draft.value = { key: '', value: '' }
}

const confirmEdit = () => {
  const index = editingIndex.value
  if (index < 0) return
  const key = draft.value.key.trim()
  if (!key) return
  const isNewRow = index >= items.value.length
  let next: KeyValueItem[]
  if (isNewRow) {
    next = [...items.value, { key, value: draft.value.value }]
  } else {
    next = items.value.map((item, idx) => (idx === index ? { ...item } : item))
    const target = next[index]
    target.key = key
    if (!props.secret || draft.value.value) {
      target.value = draft.value.value
    }
  }
  commit(next)
  cancelEdit()
}

const addItem = () => {
  if (props.readonly) return
  editingIndex.value = items.value.length
  draft.value = { key: '', value: '' }
}

const removeItem = (index: number) => {
  if (props.readonly) return
  commit(items.value.filter((_, idx) => idx !== index))
  if (editingIndex.value === index) cancelEdit()
}

const isEditingRow = (index: number) => editingIndex.value === index
const isNewRow = computed(() => editingIndex.value === items.value.length)
</script>

<template>
  <div class="space-y-2">
    <div
      v-for="(item, index) in items"
      :key="`${item.key}-${index}`"
      class="flex items-center gap-2"
    >
      <template v-if="isEditingRow(index)">
        <a-input
          v-model="draft.key"
          class="flex-1"
          :placeholder="keyPlaceholder || t('configEditors.keyPlaceholder')"
          allow-clear
        />
        <a-input
          v-model="draft.value"
          class="flex-1"
          :placeholder="secret ? t('configEditors.secretKeepPlaceholder') : valuePlaceholder || t('configEditors.valuePlaceholder')"
          allow-clear
        />
        <a-button type="text" size="small" data-testid="kv-confirm" @click="confirmEdit">
          {{ t('common.actions.confirm') }}
        </a-button>
        <a-button type="text" size="small" data-testid="kv-cancel" @click="cancelEdit">
          {{ t('common.actions.cancel') }}
        </a-button>
      </template>
      <template v-else>
        <div class="flex h-8 flex-1 items-center rounded border border-gray-200 bg-gray-50 px-3 text-sm text-gray-700">
          {{ item.key }}
        </div>
        <div class="flex h-8 flex-1 items-center rounded border border-gray-200 bg-gray-50 px-3 text-sm text-gray-500">
          <span v-if="secret && item.value">{{ t('configEditors.secretSetPlaceholder') }}</span>
          <span v-else>{{ item.value }}</span>
        </div>
        <template v-if="!readonly">
          <a-button type="text" size="small" data-testid="kv-edit" @click="startEdit(index)">
            <template #icon><icon-edit /></template>
          </a-button>
          <a-button type="text" size="small" status="danger" data-testid="kv-delete" @click="removeItem(index)">
            <template #icon><icon-delete /></template>
          </a-button>
        </template>
      </template>
    </div>

    <div v-if="isNewRow && !readonly" class="flex items-center gap-2">
      <a-input
        v-model="draft.key"
        class="flex-1"
        :placeholder="keyPlaceholder || t('configEditors.keyPlaceholder')"
        allow-clear
      />
      <a-input
        v-model="draft.value"
        class="flex-1"
        :placeholder="valuePlaceholder || t('configEditors.valuePlaceholder')"
        allow-clear
      />
      <a-button type="text" size="small" @click="confirmEdit">
        {{ t('common.actions.confirm') }}
      </a-button>
      <a-button type="text" size="small" @click="cancelEdit">
        {{ t('common.actions.cancel') }}
      </a-button>
    </div>

    <a-button v-if="!readonly && !isNewRow" type="text" size="small" @click="addItem">
      <template #icon><icon-plus /></template>
      {{ t('configEditors.addItem') }}
    </a-button>

    <div v-if="!items.length && readonly" class="text-xs text-gray-400">
      {{ t('configEditors.empty') }}
    </div>
  </div>
</template>
