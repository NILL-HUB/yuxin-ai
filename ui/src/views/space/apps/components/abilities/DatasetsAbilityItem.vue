<script setup lang="ts">
import { computed, onMounted, ref, watch, type PropType } from 'vue'
import { useUpdateDraftAppConfig } from '@/hooks/use-app'
import { listReadableSystemKnowledgeBases } from '@/services/knowledge-base'
import { useGetLanguageModels } from '@/hooks/use-language-model'
import { cloneDeep } from 'lodash'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'

// 新版 KnowledgeBase 展示项结构（用于已选列表回显）
type KnowledgeBaseItem = {
  id: string
  name: string
  description: string
}

type RetrievalConfigForm = {
  retrieval_strategy: string
  k: number
  score: number
}

// 1.定义自定义组件所需数据
const { t } = useI18n()
const props = defineProps({
  app_id: { type: String, default: '', required: true },
  retrieval_config: {
    type: Object as PropType<RetrievalConfigForm>,
    default: () => ({
      retrieval_strategy: 'semantic',
      k: 4,
      score: 0,
    }),
    required: true,
  },
  // 新版知识库 id 列表
  knowledge_base_ids: {
    type: Array as PropType<string[]>,
    default: () => [],
    required: true,
  },
  // App 级别 embedding 模型 ID（决定用户记忆向量存储维度）
  embedding_model_id: {
    type: String,
    default: '',
  },
})
const emits = defineEmits([
  'update:retrieval_config',
  'update:knowledge_base_ids',
  'update:embedding_model_id',
])
const { loading: updateDraftAppConfigLoading, handleUpdateDraftAppConfig } =
  useUpdateDraftAppConfig()
const { language_models, loadLanguageModels } = useGetLanguageModels()

// 新版系统知识库列表状态（系统级知识库全局可见）
const knowledgeBasesLoading = ref(false)
const knowledgeBases = ref<KnowledgeBaseItem[]>([])

/**
 * 加载对 Agent 可读的系统知识库列表（enabled=True）。
 * 调用用户端接口 /space/system-knowledge-bases，无需 admin 权限。
 * admin 通过 enabled 开关控制系统知识库是否对 Agent 生效。
 */
const loadKnowledgeBases = async () => {
  try {
    knowledgeBasesLoading.value = true
    const response = await listReadableSystemKnowledgeBases()
    knowledgeBases.value = (response.data?.list || []).map((item) => ({
      id: item.id,
      name: item.name,
      description: item.description || '',
    }))
  } catch {
    // 接口不可用时降级为空列表，不阻断组件配置
    knowledgeBases.value = []
  } finally {
    knowledgeBasesLoading.value = false
  }
}

// 系统知识库多选可选项（供 a-select 使用）
const knowledgeBaseOptions = computed(() =>
  knowledgeBases.value.map((kb) => ({
    label: kb.name,
    value: kb.id,
  })),
)

// 已选知识库展示列表（根据当前选中 id 从已加载列表回填展示信息）
const selectedKnowledgeBases = computed(() =>
  knowledgeBaseIds.value
    .map((id) => knowledgeBases.value.find((kb) => kb.id === id))
    .filter((kb): kb is KnowledgeBaseItem => !!kb),
)

// 提取所有 embedding 类型模型，扁平化为 {model_id, label, provider_name, dimension} 列表
const embeddingModelOptions = computed(() => {
  const options: Array<{ model_id: string; label: string; provider_name: string; dimension: number }> = []
  for (const provider of language_models.value || []) {
    for (const model of provider.models || []) {
      if (model.model_type === 'embedding') {
        const dimension = Number(model.metadata?.embedding_dimension || 0)
        options.push({
          model_id: model.model_id,
          label: model.label || model.model_name,
          provider_name: provider.name,
          dimension,
        })
      }
    }
  }
  return options
})

const retrievalConfigModalVisible = ref(false)
const retrievalConfigForm = ref<RetrievalConfigForm>({
  retrieval_strategy: 'semantic',
  k: 4,
  score: 0,
})
const originRetrievalConfigForm = ref<RetrievalConfigForm>({
  retrieval_strategy: 'semantic',
  k: 4,
  score: 0,
})
const isRetrievalConfigInit = ref(false)

// 新版知识库 id 列表（本地工作副本）与原始备份
const knowledgeBaseIds = ref<string[]>([])
const originKnowledgeBaseIds = ref<string[]>([])

// embedding 模型 id 本地工作副本
const embeddingModelId = ref<string>('')
const originEmbeddingModelId = ref<string>('')

const getRetrievalStrategyLabel = (strategy: string) => {
  if (strategy === 'semantic') return t('appStudio.abilities.datasets.retrievalStrategies.semantic')
  if (strategy === 'full_text') return t('appStudio.abilities.datasets.retrievalStrategies.fullText')
  return t('appStudio.abilities.datasets.retrievalStrategies.hybrid')
}

// 2.定义取消检索设置模态窗处理器
const handleCancelRetrievalConfigModal = () => {
  // 2.1 隐藏模态窗
  retrievalConfigModalVisible.value = false

  // 2.2 还原初始值
  retrievalConfigForm.value = originRetrievalConfigForm.value
  isRetrievalConfigInit.value = false
}

// 3.提交更新检索配置
const handleSubmitRetrievalConfig = async () => {
  const retrievalConfig = {
    retrieval_strategy: String(retrievalConfigForm.value.retrieval_strategy || 'semantic'),
    k: Number(retrievalConfigForm.value.k ?? 4),
    score: Number(retrievalConfigForm.value.score ?? 0),
  }

  // 3.1 处理数据并完成API接口提交
  await handleUpdateDraftAppConfig(props.app_id, {
    retrieval_config: retrievalConfig,
  })

  // 3.2 接口更新更新成功，同步表单信息
  originRetrievalConfigForm.value = retrievalConfig

  // 3.3 双向同步更新props中的数据
  emits('update:retrieval_config', retrievalConfig)

  // 3.4 隐藏模态窗
  handleCancelRetrievalConfigModal()
}

/**
 * 新版知识库多选变更处理器：限制最多 5 个，立即持久化到草稿配置。
 */
const handleKnowledgeBaseChange = async (ids: (string | number)[]) => {
  // 限制最多 5 个
  const stringIds = ids.map((id) => String(id))
  if (stringIds.length > 5) {
    Message.warning(t('appStudio.abilities.datasets.limitExceeded'))
    knowledgeBaseIds.value = stringIds.slice(0, 5)
  } else {
    knowledgeBaseIds.value = stringIds
  }

  // 持久化到草稿配置
  await handleUpdateDraftAppConfig(props.app_id, {
    knowledge_base_ids: knowledgeBaseIds.value,
  })
  originKnowledgeBaseIds.value = cloneDeep(knowledgeBaseIds.value)

  // 双向同步更新props中的数据
  emits('update:knowledge_base_ids', knowledgeBaseIds.value)
}

/**
 * embedding 模型变更处理器：立即持久化到草稿配置。
 */
const handleEmbeddingModelChange = async (modelId: string | number | undefined) => {
  const value = modelId ? String(modelId) : ''
  embeddingModelId.value = value

  await handleUpdateDraftAppConfig(props.app_id, {
    embedding_model_id: value,
  })
  originEmbeddingModelId.value = value

  emits('update:embedding_model_id', value)
}

// 4.监听检索配置
watch(
  () => props.retrieval_config,
  (newValue) => {
    // 4.1 检测是否是否更新并且未初始化
    if (!isRetrievalConfigInit.value || retrievalConfigForm.value === originRetrievalConfigForm.value) {
      if (newValue && Object.keys(newValue).length > 0) {
        // 4.2 更新表单数据和备份数据
        retrievalConfigForm.value = { ...newValue }
        originRetrievalConfigForm.value = { ...newValue }

        // 4.3 标记为已初始化
        isRetrievalConfigInit.value = true
      }
    }
  },
  { immediate: true, deep: true },
)

// 5.监听新版知识库 id 列表（编辑回填）
watch(
  () => props.knowledge_base_ids,
  (newValue) => {
    const ids = Array.isArray(newValue) ? [...newValue] : []
    knowledgeBaseIds.value = ids
    originKnowledgeBaseIds.value = cloneDeep(ids)
  },
  { immediate: true, deep: true },
)

// 6.监听 embedding 模型 id（编辑回填）
watch(
  () => props.embedding_model_id,
  (newValue) => {
    const val = newValue || ''
    embeddingModelId.value = val
    originEmbeddingModelId.value = val
  },
  { immediate: true },
)

onMounted(() => {
  loadKnowledgeBases()
  loadLanguageModels()
})
</script>

<template>
  <div class="">
    <a-collapse-item key="datasets" class="app-ability-item">
      <template #header>
        <div class="text-gray-700 font-bold">{{ t('appStudio.abilities.datasets.title') }}</div>
      </template>
      <template #extra>
        <a-space>
          <a-button
            size="mini"
            class="rounded-lg px-2"
            @click.stop="retrievalConfigModalVisible = true"
          >
            <template #icon>
              <icon-language />
            </template>
            <div class="">{{ getRetrievalStrategyLabel(retrieval_config?.retrieval_strategy || 'hybrid') }}</div>
          </a-button>
        </a-space>
      </template>
      <!-- 新版 knowledge_base 配置 -->
      <div class="flex flex-col gap-2">
        <!-- 多选选择器 -->
        <a-select
          multiple
          allow-search
          :loading="knowledgeBasesLoading"
          :model-value="knowledgeBaseIds"
          :options="knowledgeBaseOptions"
          :placeholder="t('appStudio.abilities.datasets.knowledgeBasePlaceholder')"
          @change="handleKnowledgeBaseChange"
        />
        <!-- 已选知识库列表（展示名称与描述） -->
        <div v-if="selectedKnowledgeBases.length > 0" class="flex flex-col gap-1">
          <div
            v-for="kb in selectedKnowledgeBases"
            :key="kb.id"
            class="flex items-center justify-between bg-white p-3 rounded-lg border"
          >
            <div class="flex flex-col flex-1 min-w-0 gap-1">
              <div class="text-gray-700 font-bold leading-[18px] line-clamp-1 min-w-0">
                {{ kb.name }}
              </div>
              <div class="text-gray-500 text-xs line-clamp-1 min-w-0">
                {{ kb.description || '-' }}
              </div>
            </div>
          </div>
        </div>
        <div v-else class="text-xs text-gray-500 leading-[22px]">
          {{ t('appStudio.abilities.datasets.empty') }}
        </div>
        <!-- 最多选择提示 -->
        <div class="text-xs text-gray-400">
          {{ t('appStudio.abilities.datasets.knowledgeBaseMaxHint') }}
        </div>
        <!-- App 级别 embedding 模型选择（决定用户记忆向量存储维度） -->
        <div class="mt-2 pt-3 border-t border-gray-100">
          <div class="text-sm text-gray-700 font-bold mb-2">
            {{ t('appStudio.abilities.datasets.embeddingModelLabel') }}
          </div>
          <a-select
            :model-value="embeddingModelId || undefined"
            allow-search
            allow-clear
            :placeholder="t('appStudio.abilities.datasets.embeddingModelPlaceholder')"
            @change="handleEmbeddingModelChange"
          >
            <a-option
              v-for="opt in embeddingModelOptions"
              :key="opt.model_id"
              :value="opt.model_id"
            >
              {{ opt.label }} ({{ opt.provider_name }}{{ opt.dimension ? ` · ${opt.dimension}d` : '' }})
            </a-option>
            <template #empty>
              <div class="text-center text-gray-400 py-2">
                {{ t('appStudio.abilities.datasets.noEmbeddingModels') }}
              </div>
            </template>
          </a-select>
          <div class="text-xs text-gray-400 mt-1">
            {{ t('appStudio.abilities.datasets.embeddingModelHint') }}
          </div>
        </div>
      </div>
    </a-collapse-item>
    <!-- 检索设置模态窗 -->
    <a-modal
      :visible="retrievalConfigModalVisible"
      hide-title
      :footer="false"
      modal-class="rounded-xl"
      @cancel="handleCancelRetrievalConfigModal"
    >
      <!-- 顶部标题 -->
      <div class="flex items-center justify-between">
        <div class="text-lg font-bold text-gray-700">
          {{ t('appStudio.abilities.datasets.retrievalTitle') }}
        </div>
        <a-button
          type="text"
          class="!text-gray-700"
          size="small"
          @click="handleCancelRetrievalConfigModal"
        >
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>
      <!-- 中间表单内容 -->
      <a-form :model="retrievalConfigForm" @submit="handleSubmitRetrievalConfig" class="pt-6">
        <a-form-item
          field="retrieval_strategy"
          :label="t('appStudio.abilities.datasets.retrievalStrategy')"
          label-align="left"
        >
          <a-radio-group
            v-model:model-value="retrievalConfigForm.retrieval_strategy"
            default-value="semantic"
            :options="[
              { label: t('appStudio.abilities.datasets.retrievalStrategies.hybrid'), value: 'hybrid' },
              { label: t('appStudio.abilities.datasets.retrievalStrategies.fullText'), value: 'full_text' },
              { label: t('appStudio.abilities.datasets.retrievalStrategies.semantic'), value: 'semantic' },
            ]"
          />
        </a-form-item>
        <a-form-item field="k" :label="t('appStudio.abilities.datasets.maxRecall')">
          <div class="flex items-center gap-4 w-full pl-3">
            <a-slider v-model:model-value="retrievalConfigForm.k" :step="1" :min="1" :max="10" />
            <a-input-number
              v-model:model-value="retrievalConfigForm.k"
              class="w-[80px]"
              :default-value="4"
            />
          </div>
        </a-form-item>
        <a-form-item field="score" :label="t('appStudio.abilities.datasets.minScore')">
          <div class="flex items-center gap-4 w-full pl-3">
            <a-slider
              v-model:model-value="retrievalConfigForm.score"
              :step="0.01"
              :min="0"
              :max="0.99"
            />
            <a-input-number
              v-model:model-value="retrievalConfigForm.score"
              class="w-[80px]"
              :min="0"
              :max="0.99"
              :step="0.01"
              :precision="2"
              :default-value="0.5"
            />
          </div>
        </a-form-item>
        <!-- 底部按钮 -->
        <div class="flex items-center justify-between">
          <div class=""></div>
          <a-space :size="16">
            <a-button class="rounded-lg" @click="handleCancelRetrievalConfigModal">
              {{ t('common.actions.cancel') }}
            </a-button>
            <a-button
              :loading="updateDraftAppConfigLoading"
              type="primary"
              html-type="submit"
              class="rounded-lg"
            >
              {{ t('common.actions.save') }}
            </a-button>
          </a-space>
        </div>
      </a-form>
    </a-modal>
  </div>
</template>
