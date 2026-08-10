<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  useDeleteAllConversationVariables,
  useDeleteConversationVariable,
  useGetConversationVariables,
  useSetConversationVariable,
} from '@/hooks/use-conversation-variable'
import type {
  ConversationVariable,
  ConversationVariableValueType,
  SetVariableReq,
} from '@/models/conversation-variable'

// 1.定义组件所需要使用的数据
const props = defineProps({
  visible: { type: Boolean, required: true },
  conversation_id: { type: String, required: true },
})
const emits = defineEmits(['update:visible'])
const { t } = useI18n()

const {
  loading,
  variables,
  loadVariables,
} = useGetConversationVariables()
const { loading: setSubmitting, handleSetVariable } = useSetConversationVariable()
const { handleDeleteVariable } = useDeleteConversationVariable()
const { loading: deleteAllLoading, handleDeleteAll } = useDeleteAllConversationVariables()

// 2.内嵌模态窗：新增/编辑表单
const formVisible = ref(false)
const isEdit = ref(false)
const formModel = ref<{
  name: string
  value_type: ConversationVariableValueType
  raw_value: string
  bool_value: boolean
  number_value: number | undefined
  string_value: string
}>({
  name: '',
  value_type: 'string',
  raw_value: '',
  bool_value: false,
  number_value: undefined,
  string_value: '',
})

// 类型选项
const valueTypeOptions = computed(() => {
  const types: ConversationVariableValueType[] = ['string', 'int', 'float', 'boolean', 'json']
  return types.map((value) => ({
    value,
    label: t(`appStudio.debug.conversationVariables.types.${value}`),
  }))
})

// 3.格式化值展示
const formatValue = (variable: ConversationVariable): string => {
  if (variable.value_type === 'json') {
    try {
      return typeof variable.value === 'string'
        ? variable.value
        : JSON.stringify(variable.value, null, 2)
    } catch {
      return String(variable.value)
    }
  }
  if (variable.value_type === 'boolean') {
    return variable.value ? 'true' : 'false'
  }
  return String(variable.value)
}

// 4.打开新增表单
const openAddForm = () => {
  isEdit.value = false
  formModel.value = {
    name: '',
    value_type: 'string',
    raw_value: '',
    bool_value: false,
    number_value: undefined,
    string_value: '',
  }
  formVisible.value = true
}

// 5.打开编辑表单
const openEditForm = (variable: ConversationVariable) => {
  isEdit.value = true
  formModel.value = {
    name: variable.name,
    value_type: variable.value_type,
    raw_value:
      variable.value_type === 'json'
        ? typeof variable.value === 'string'
          ? variable.value
          : JSON.stringify(variable.value, null, 2)
        : '',
    bool_value: variable.value_type === 'boolean' ? Boolean(variable.value) : false,
    number_value:
      variable.value_type === 'int' || variable.value_type === 'float'
        ? Number(variable.value)
        : undefined,
    string_value: variable.value_type === 'string' ? String(variable.value ?? '') : '',
  }
  formVisible.value = true
}

// 6.提交表单
const handleSubmit = async () => {
  if (!props.conversation_id) return
  const name = formModel.value.name.trim()
  if (!name) {
    Message.warning(t('appStudio.debug.conversationVariables.nameRequired'))
    return
  }

  // 根据类型构造 value
  let value: unknown
  const value_type: ConversationVariableValueType = formModel.value.value_type
  switch (formModel.value.value_type) {
    case 'string':
      value = formModel.value.string_value
      break
    case 'int':
      value = Number(formModel.value.number_value ?? 0)
      break
    case 'float':
      value = Number(formModel.value.number_value ?? 0)
      break
    case 'boolean':
      value = Boolean(formModel.value.bool_value)
      break
    case 'json': {
      const raw = formModel.value.raw_value.trim()
      if (!raw) {
        value = null
        break
      }
      try {
        value = JSON.parse(raw)
      } catch {
        Message.error(t('appStudio.debug.conversationVariables.jsonInvalid'))
        return
      }
      break
    }
    default:
      value = formModel.value.string_value
  }

  const req: SetVariableReq = {
    name,
    value,
    value_type,
  }

  await handleSetVariable(props.conversation_id, req, isEdit.value)
  formVisible.value = false
  await loadVariables(props.conversation_id)
}

// 7.删除单个变量
const onDeleteVariable = (variable: ConversationVariable) => {
  if (!props.conversation_id) return
  handleDeleteVariable(props.conversation_id, variable.name, async () => {
    await loadVariables(props.conversation_id)
  })
}

// 8.清空全部变量
const onDeleteAll = () => {
  if (!props.conversation_id) return
  handleDeleteAll(props.conversation_id, async () => {
    await loadVariables(props.conversation_id)
  })
}

// 9.监听 visible 属性
watch(
  () => props.visible,
  async (newValue) => {
    if (newValue) {
      if (props.conversation_id) {
        await loadVariables(props.conversation_id)
      } else {
        variables.value = []
      }
    } else {
      variables.value = []
      formVisible.value = false
    }
  },
)

// 10.监听 conversation_id 变化
watch(
  () => props.conversation_id,
  async (newValue) => {
    if (props.visible && newValue) {
      await loadVariables(newValue)
    } else if (!newValue) {
      variables.value = []
    }
  },
)

const hasConversation = computed(() => Boolean(props.conversation_id))
</script>

<template>
  <!-- 会话变量抽屉 -->
  <a-drawer
    :visible="props.visible"
    :title="t('appStudio.debug.conversationVariables.title')"
    :width="520"
    :footer="false"
    :drawer-style="{ backgroundColor: '#f9fafb' }"
    @cancel="() => emits('update:visible', false)"
  >
    <!-- 顶部操作区 -->
    <div class="flex items-center justify-between mb-4">
      <div class="text-xs text-gray-500">
        <span v-if="hasConversation">
          {{ t('appStudio.debug.conversationVariables.title') }}
          ({{ variables.length }})
        </span>
        <span v-else>
          {{ t('appStudio.debug.conversationVariables.noDebugConversation') }}
        </span>
      </div>
      <a-space :size="8">
        <a-button
          size="mini"
          type="primary"
          :disabled="!hasConversation"
          @click="openAddForm"
        >
          <template #icon><icon-plus /></template>
          {{ t('appStudio.debug.conversationVariables.addVariable') }}
        </a-button>
        <a-button
          size="mini"
          :disabled="!hasConversation || variables.length === 0"
          :loading="deleteAllLoading"
          @click="onDeleteAll"
        >
          {{ t('appStudio.debug.conversationVariables.deleteAllConfirmTitle') }}
        </a-button>
      </a-space>
    </div>

    <!-- 变量列表 -->
    <a-spin :loading="loading" class="block w-full">
      <a-empty
        v-if="variables.length === 0"
        :description="hasConversation
          ? t('appStudio.debug.conversationVariables.empty')
          : t('appStudio.debug.conversationVariables.noDebugConversation')"
        class="my-12"
      />
      <div v-else class="flex flex-col gap-3">
        <a-card
          v-for="variable in variables"
          :key="variable.id"
          hoverable
          class="rounded-lg group"
          :body-style="{ padding: '12px 14px' }"
        >
          <div class="flex flex-col gap-2">
            <!-- 顶部：变量名 + 类型 + 操作 -->
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2 min-w-0">
                <div class="font-bold text-gray-900 truncate">{{ variable.name }}</div>
                <a-tag size="small" color="arcoblue">
                  {{ t(`appStudio.debug.conversationVariables.types.${variable.value_type}`) }}
                </a-tag>
              </div>
              <a-space :size="4" class="shrink-0">
                <a-button
                  size="mini"
                  type="text"
                  class="!text-blue-700"
                  @click="openEditForm(variable)"
                >
                  <template #icon><icon-edit /></template>
                </a-button>
                <a-button
                  size="mini"
                  type="text"
                  class="!text-red-600"
                  @click="onDeleteVariable(variable)"
                >
                  <template #icon><icon-delete /></template>
                </a-button>
              </a-space>
            </div>
            <!-- 值展示 -->
            <div class="text-gray-700 text-sm break-all">
              <pre
                v-if="variable.value_type === 'json'"
                class="bg-gray-50 rounded p-2 text-xs whitespace-pre-wrap break-all m-0 max-h-48 overflow-auto"
              >{{ formatValue(variable) }}</pre>
              <span v-else class="font-mono">{{ formatValue(variable) }}</span>
            </div>
          </div>
        </a-card>
      </div>
    </a-spin>

    <!-- 内嵌新增/编辑模态窗 -->
    <a-modal
      :visible="formVisible"
      :width="480"
      :title="isEdit
        ? t('appStudio.debug.conversationVariables.editVariable')
        : t('appStudio.debug.conversationVariables.addVariable')"
      :ok-loading="setSubmitting"
      :mask-closable="false"
      @cancel="formVisible = false"
      @ok="handleSubmit"
    >
      <a-form :model="formModel" layout="vertical" class="pt-2">
        <a-form-item
          :label="t('appStudio.debug.conversationVariables.nameLabel')"
          field="name"
          required
        >
          <a-input
            v-model="formModel.name"
            :placeholder="t('appStudio.debug.conversationVariables.namePlaceholder')"
            :disabled="isEdit"
            allow-clear
          />
        </a-form-item>
        <a-form-item field="value_type" :label="t('appStudio.debug.conversationVariables.typeLabel')">
          <a-select v-model="formModel.value_type" :options="valueTypeOptions" />
        </a-form-item>
        <a-form-item
          v-if="formModel.value_type === 'string'"
          field="string_value"
          :label="t('appStudio.debug.conversationVariables.valueLabel')"
        >
          <a-input
            v-model="formModel.string_value"
            :placeholder="t('appStudio.debug.conversationVariables.valuePlaceholder')"
            allow-clear
          />
        </a-form-item>
        <a-form-item
          v-else-if="formModel.value_type === 'int' || formModel.value_type === 'float'"
          field="number_value"
          :label="t('appStudio.debug.conversationVariables.valueLabel')"
        >
          <a-input-number
            v-model="formModel.number_value"
            :placeholder="t('appStudio.debug.conversationVariables.valuePlaceholder')"
            :step="formModel.value_type === 'float' ? 0.1 : 1"
            :precision="formModel.value_type === 'float' ? undefined : 0"
            class="!w-full"
          />
        </a-form-item>
        <a-form-item
          v-else-if="formModel.value_type === 'boolean'"
          field="bool_value"
          :label="t('appStudio.debug.conversationVariables.valueLabel')"
        >
          <a-switch v-model="formModel.bool_value" />
        </a-form-item>
        <a-form-item
          v-else
          field="raw_value"
          :label="t('appStudio.debug.conversationVariables.valueLabel')"
        >
          <a-textarea
            v-model="formModel.raw_value"
            :placeholder="t('appStudio.debug.conversationVariables.valuePlaceholder')"
            :auto-size="{ minRows: 4, maxRows: 10 }"
            class="font-mono"
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </a-drawer>
</template>

<style scoped></style>
