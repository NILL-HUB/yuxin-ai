<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Modal, Message } from '@arco-design/web-vue'
import { useUpdateDraftAppConfig } from '@/hooks/use-app'
import WorkflowBindingPickerModal from './WorkflowBindingPickerModal.vue'
import { getErrorMessage } from '@/utils/error'

type WorkflowDetail = {
  id: string
  name: string
  icon: string
  description: string
}

const props = defineProps({
  app_id: { type: String, required: true },
  workflow_id: { type: String as () => string | null, default: null },
  workflow_detail: {
    type: Object as () => WorkflowDetail | null,
    default: null,
  },
})
const emits = defineEmits(['update:workflow_id', 'reload-draft-app-config'])
const { t } = useI18n()
const { loading, handleUpdateDraftAppConfig } = useUpdateDraftAppConfig()
const pickerVisible = ref(false)

const handleSelect = async (workflow: WorkflowDetail) => {
  try {
    await handleUpdateDraftAppConfig(props.app_id, { workflow_id: workflow.id })
    emits('update:workflow_id', workflow.id)
    emits('reload-draft-app-config')
    Message.success(t('appStudio.abilities.workflowBinding.bindSuccess'))
  } catch (error) {
    Message.error(getErrorMessage(error, t('appStudio.shell.updateDraftFailed')))
  }
  pickerVisible.value = false
}

const handleUnbind = () => {
  Modal.warning({
    title: t('appStudio.abilities.workflowBinding.unbindConfirmTitle'),
    content: t('appStudio.abilities.workflowBinding.unbindConfirmContent'),
    hideCancel: false,
    onOk: async () => {
      try {
        await handleUpdateDraftAppConfig(props.app_id, { workflow_id: null })
        emits('update:workflow_id', null)
        emits('reload-draft-app-config')
        Message.success(t('appStudio.abilities.workflowBinding.unbindSuccess'))
      } catch (error) {
        Message.error(getErrorMessage(error, t('appStudio.shell.updateDraftFailed')))
      }
    },
  })
}
</script>

<template>
  <a-collapse-item key="workflowBinding" class="app-ability-item">
    <template #header>
      <div class="text-gray-700 font-bold">{{ t('appStudio.abilities.workflowBinding.title') }}</div>
    </template>
    <template #extra>
      <a-button
        size="mini"
        type="text"
        class="!text-gray-700"
        @click.stop="pickerVisible = true"
      >
        <template #icon>
          <icon-plus />
        </template>
      </a-button>
    </template>
    <div class="text-xs text-gray-500 leading-[22px] mb-2">
      {{ t('appStudio.abilities.workflowBinding.description') }}
    </div>
    <!-- 已绑定工作流：展示卡片 -->
    <div
      v-if="props.workflow_detail"
      class="flex items-center justify-between bg-white p-3 rounded-lg group"
    >
      <div class="flex items-center gap-2 min-w-0 flex-1">
        <a-avatar
          :size="36"
          shape="square"
          class="rounded flex-shrink-0"
          :image-url="props.workflow_detail.icon"
        />
        <div class="flex flex-col flex-1 min-w-0 gap-1 h-9">
          <div class="text-gray-700 font-bold leading-[18px] line-clamp-1 min-w-0">
            {{ props.workflow_detail.name }}
          </div>
          <div class="text-gray-500 text-xs line-clamp-1 min-w-0">
            {{ props.workflow_detail.description }}
          </div>
        </div>
      </div>
      <a-button
        size="mini"
        type="text"
        class="opacity-0 group-hover:opacity-100 flex-shrink-0 ml-2 !text-red-700 rounded"
        :loading="loading"
        @click="handleUnbind"
      >
        {{ t('appStudio.abilities.workflowBinding.unbind') }}
      </a-button>
    </div>
    <!-- 已绑定 workflow_id 但 detail 缺失：展示 id 与解绑按钮 -->
    <div
      v-else-if="props.workflow_id"
      class="flex items-center justify-between bg-white p-3 rounded-lg group"
    >
      <div class="flex items-center gap-2 min-w-0 flex-1">
        <a-avatar :size="36" shape="square" class="rounded flex-shrink-0 bg-gray-100">
          <icon-mind-mapping />
        </a-avatar>
        <div class="flex flex-col flex-1 min-w-0 gap-1 h-9">
          <div class="text-gray-700 font-bold leading-[18px] line-clamp-1 min-w-0">
            {{ props.workflow_id }}
          </div>
          <div class="text-gray-500 text-xs line-clamp-1 min-w-0">
            {{ t('appStudio.abilities.workflowBinding.title') }}
          </div>
        </div>
      </div>
      <a-button
        size="mini"
        type="text"
        class="opacity-0 group-hover:opacity-100 flex-shrink-0 ml-2 !text-red-700 rounded"
        :loading="loading"
        @click="handleUnbind"
      >
        {{ t('appStudio.abilities.workflowBinding.unbind') }}
      </a-button>
    </div>
    <!-- 未绑定：空状态 -->
    <div v-else class="text-xs text-gray-500 leading-[22px]">
      {{ t('appStudio.abilities.workflowBinding.empty') }}
    </div>
    <!-- 选择工作流弹窗 -->
    <WorkflowBindingPickerModal
      :visible="pickerVisible"
      :selected_workflow_id="props.workflow_id"
      @update:visible="pickerVisible = $event"
      @select="handleSelect"
    />
  </a-collapse-item>
</template>

<style>
.app-ability-item {
  width: 100%;
  min-width: 0;

  .arco-collapse-item-header {
    background-color: transparent;
    border: none;
  }

  .arco-collapse-item-content {
    padding-left: 16px;
  }
}
</style>
