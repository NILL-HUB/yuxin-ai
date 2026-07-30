<script setup lang="ts">
import { computed } from 'vue'
import { Handle, type NodeProps, Position } from '@vue-flow/core'
import { useI18n } from 'vue-i18n'

// 1.定义自定义组件所需数据
const props = defineProps<NodeProps>()
const { t } = useI18n()

// 当前数据源类型对应的展示文案
const sourceTypeLabel = computed(() => {
  return t('workflowEditor.datasetRetrieval.sourceTypes.knowledgeBase')
})
</script>

<template>
  <div
    :class="[
      'flex w-[360px] flex-col gap-3 overflow-hidden rounded-2xl border-[2px] bg-white p-3 shadow-sm transition-all hover:shadow-md',
      props.selected ? 'border-blue-700' : 'border-transparent',
    ]"
  >
    <!-- 节点标题信息 -->
    <div class="flex items-center gap-2 min-w-0">
      <a-avatar shape="square" :size="24" class="bg-violet-500 rounded-lg flex-shrink-0">
        <icon-storage :size="16" />
      </a-avatar>
      <div class="text-gray-700 font-semibold break-words line-clamp-2">{{ props.data?.title }}</div>
    </div>
    <!-- 输入变量列表 -->
    <div class="flex flex-col items-start bg-gray-100 rounded-lg p-3 min-w-0">
      <!-- 标题 -->
      <div class="flex items-center gap-2 mb-2 text-gray-700">
        <icon-caret-down />
        <div class="text-xs font-semibold">{{ t('workflowEditor.inputData') }}</div>
      </div>
      <!-- 输入变量 -->
      <div class="w-full flex flex-col gap-2 min-w-0">
        <div
          v-for="input in props.data.inputs"
          :key="input.name"
          class="w-full flex flex-col gap-1 text-xs min-w-0"
        >
          <!-- 变量名和类型 -->
          <div class="flex items-center gap-2">
            <div class="flex items-center gap-1">
              <div class="text-gray-700 break-words">{{ input.name }}</div>
              <div v-if="input.required" class="text-red-700 flex-shrink-0">*</div>
            </div>
            <div class="text-gray-500 bg-gray-200 px-1 py-0.5 rounded flex-shrink-0 text-[10px]">
              {{ input.type }}
            </div>
          </div>
          <!-- 变量值 -->
          <div class="w-full min-w-0">
            <div
              v-if="input.value.type == 'ref'"
              class="bg-white text-gray-500 border px-2 py-1 rounded break-words"
            >
              {{ t('workflowEditor.referencePrefix') }} {{ input.value.content.ref_var_name }}
            </div>
            <div v-else class="text-gray-500 px-2 py-1 bg-white rounded break-words">
              {{ input.value.content || '-' }}
            </div>
          </div>
        </div>
      </div>
    </div>
    <!-- 关联知识库 -->
    <div class="flex flex-col items-start bg-gray-100 rounded-lg p-3 min-w-0">
      <!-- 标题 -->
      <div class="flex items-center gap-2 mb-2 text-gray-700">
        <icon-caret-down />
        <div class="text-xs font-semibold">{{ t('workflowEditor.datasetRetrieval.bindDataset') }}</div>
        <!-- 数据源类型标签 -->
        <div class="text-[10px] text-gray-500 bg-gray-200 px-1 py-0.5 rounded flex-shrink-0">
          {{ sourceTypeLabel }}
        </div>
      </div>
      <!-- 关联知识库列表 -->
      <div class="flex flex-col gap-2 w-full min-w-0">
        <div
          v-for="kb in props.data?.meta?.knowledge_bases ?? []"
          :key="kb.id"
          class="flex items-center gap-2 text-xs min-w-0"
        >
          <!-- 左侧知识库图标 -->
          <a-avatar :size="16" shape="square" class="bg-violet-500 flex-shrink-0 rounded">
            <icon-storage :size="10" />
          </a-avatar>
          <!-- 右侧知识库名称 -->
          <div class="text-gray-700 break-words flex-1">{{ kb?.name }}</div>
        </div>
        <div v-if="!props.data?.meta?.knowledge_bases?.length" class="text-gray-500 text-xs px-0.5">-</div>
      </div>
    </div>
    <!-- 输出变量 -->
    <div class="flex flex-col items-start bg-gray-100 rounded-lg p-3 min-w-0">
      <!-- 标题 -->
      <div class="flex items-center gap-2 mb-2 text-gray-700">
        <icon-caret-down />
        <div class="text-xs font-semibold">{{ t('workflowEditor.outputData') }}</div>
      </div>
      <!-- 变量容器 -->
      <div class="flex flex-wrap gap-2 w-full min-w-0">
        <div
          v-for="output in props.data?.outputs"
          :key="output.name"
          class="flex items-center gap-2 text-xs bg-white px-2 py-1 rounded"
        >
          <div class="text-gray-700 break-words">{{ output.name }}</div>
          <div class="text-gray-500 bg-gray-200 px-1 py-0.5 rounded flex-shrink-0 text-[10px]">{{ output.type }}</div>
        </div>
      </div>
    </div>
    <!-- 大模型节点-连接句柄 -->
    <handle
      type="source"
      :position="Position.Right"
      class="!w-4 !h-4 !bg-blue-700 !text-white flex items-center justify-center"
    >
      <icon-plus :size="12" class="pointer-events-none" />
    </handle>
    <handle
      type="target"
      :position="Position.Left"
      class="!w-4 !h-4 !bg-blue-700 !text-white flex items-center justify-center"
    >
      <icon-plus :size="12" class="pointer-events-none" />
    </handle>
  </div>
</template>
