<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import WorkflowBindingAbilityItem from './abilities/WorkflowBindingAbilityItem.vue'
import OpeningAbilityItem from './abilities/OpeningAbilityItem.vue'

const { t } = useI18n()
const props = defineProps({
  app_id: { type: String, default: '', required: true },
  draft_app_config: { type: Object, required: true },
})
const emits = defineEmits(['update:draft_app_config', 'reload-draft-app-config'])
const defaultActivateKeys = ['workflowBinding', 'opening']

const handleUpdateWorkflowId = (workflow_id: string | null) => {
  emits('update:draft_app_config', {
    ...props.draft_app_config,
    workflow_id,
    // 当解绑时同步清空 workflow_detail
    workflow_detail: workflow_id ? props.draft_app_config.workflow_detail : null,
  })
}
</script>

<template>
  <div class="flex flex-col h-full min-w-0 w-full overflow-hidden">
    <!-- 应用能力标题 -->
    <div class="p-4 text-gray-700 font-bold">{{ t('appStudio.abilities.title') }}</div>
    <!-- 应用能力列表 -->
    <div class="flex-1 min-w-0 overflow-y-auto overflow-x-hidden scrollbar-w-none">
      <a-collapse :bordered="false" :default-active-key="defaultActivateKeys" class="w-full min-w-0">
        <template #expand-icon="{ active }">
          <icon-down v-if="active" />
          <icon-right v-else />
        </template>
        <!-- 工作流绑定（核心） -->
        <WorkflowBindingAbilityItem
          :app_id="props.app_id"
          :workflow_id="props.draft_app_config.workflow_id"
          :workflow_detail="props.draft_app_config.workflow_detail"
          @update:workflow_id="handleUpdateWorkflowId"
          @reload-draft-app-config="emits('reload-draft-app-config')"
        />
        <!-- 对话开场白（可选） -->
        <OpeningAbilityItem
          :opening_questions="props.draft_app_config.opening_questions"
          @update:opening_questions="
            (opening_questions) =>
              emits('update:draft_app_config', {
                ...props.draft_app_config,
                opening_questions,
              })
          "
          :opening_statement="props.draft_app_config.opening_statement"
          @update:opening_statement="
            (opening_statement) =>
              emits('update:draft_app_config', {
                ...props.draft_app_config,
                opening_statement,
              })
          "
          :app_id="props.app_id"
        />
      </a-collapse>
    </div>
  </div>
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
