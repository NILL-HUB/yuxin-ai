<script setup lang="ts">
import { useGetDraftAppConfig } from '@/hooks/use-app'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getAdminAppDraftConfig } from '@/services/admin-apps'
import AgentAppAbility from './components/AgentAppAbility.vue'
import WorkflowAppAbility from './components/WorkflowAppAbility.vue'
import ModelConfig from './components/ModelConfig.vue'
import PresetPromptTextarea from './components/PresetPromptTextarea.vue'
import PreviewDebugChat from './components/PreviewDebugChat.vue'
import PreviewDebugHeader from './components/PreviewDebugHeader.vue'

// 1.页面基础数据定义
const route = useRoute()
const props = defineProps({
  app: {
    type: Object,
    default: () => {
      return {}
    },
    required: true,
  },
})
const { t } = useI18n()
const { draftAppConfigForm, loadDraftAppConfig } = useGetDraftAppConfig()
const isDraftAppConfigRefreshing = ref(false)

// 应用类型：用于在编排区按 app_type 分支渲染（默认 chatbot 兼容旧数据）
const appType = computed(() => (props.app?.app_type ?? 'chatbot') as string)

// admin 上下文检测：route.path 以 /admin/ 开头或 route.meta.realm === 'admin'
const isAdminContext = computed(
  () => route.path.startsWith('/admin/') || route.meta.realm === 'admin',
)

// 包装：加载应用草稿配置（admin/space 上下文自动切换）
const loadDraftAppConfigDetail = async (appId: string) => {
  if (isAdminContext.value) {
    const data = await getAdminAppDraftConfig(appId)
    draftAppConfigForm.value = {
      dialog_round: data.dialog_round,
      model_config: data.model_config,
      capabilities: data.capabilities || {},
      preset_prompt: data.preset_prompt,
      long_term_memory: data.long_term_memory,
      opening_statement: data.opening_statement,
      opening_questions: data.opening_questions,
      suggested_after_answer: data.suggested_after_answer,
      review_config: data.review_config,
      datasets: data.datasets,
      retrieval_config: data.retrieval_config,
      tools: data.tools,
      mcp_bindings: data.mcp_bindings || [],
      mcp_tool_snapshots: data.mcp_tool_snapshots || [],
      agent_bindings: data.agent_bindings || [],
      skills: data.skills,
      workflows: data.workflows,
      speech_to_text: data.speech_to_text,
      text_to_speech: data.text_to_speech,
      workflow_id: data.workflow_id ?? null,
      workflow_detail: data.workflow_detail ?? null,
    }
  } else {
    await loadDraftAppConfig(appId)
  }
}

const refreshDraftAppConfig = async () => {
  const appId = String(route.params?.app_id ?? '')
  if (!appId) return

  try {
    isDraftAppConfigRefreshing.value = true
    await loadDraftAppConfigDetail(appId)
  } finally {
    isDraftAppConfigRefreshing.value = false
  }
}

// 2.页面DOM加载完毕时执行函数
onMounted(async () => {
  await refreshDraftAppConfig()
})

watch(
  () => [draftAppConfigForm.value.model_config?.provider, draftAppConfigForm.value.model_config?.model],
  async (newValue, oldValue) => {
    if (isDraftAppConfigRefreshing.value) return
    if (newValue[0] === oldValue?.[0] && newValue[1] === oldValue?.[1]) return
    await refreshDraftAppConfig()
  },
)
</script>

<template>
  <div class="flex flex-1 min-h-0 w-full flex-col bg-white">
    <div class="grid flex-1 min-h-0 grid-cols-[minmax(0,26fr)_minmax(0,14fr)] w-full overflow-hidden">
      <!-- 左侧应用编排 -->
      <div class="bg-gray-50 flex min-h-0 flex-col min-w-0 overflow-hidden">
        <!-- 顶部标题 -->
        <div class="flex items-center h-16 border-b p-4 gap-4">
          <div class="text-lg text-gray-700">{{ t('appStudio.detail.title') }}</div>
          <!-- LLM模型配置 -->
          <model-config :dialog_round="draftAppConfigForm.dialog_round"
            v-model:model_config="draftAppConfigForm.model_config" :app_id="String(route.params?.app_id)" />
        </div>
        <!-- 底部编排区域 -->
        <div class="grid flex-1 min-h-0 grid-cols-[minmax(0,13fr)_minmax(0,12fr)] overflow-hidden">
          <!-- 左侧人设与回复逻辑 -->
          <div class="border-r py-4 min-w-0 overflow-hidden">
            <preset-prompt-textarea
              class="min-w-0"
              v-model:preset_prompt="draftAppConfigForm.preset_prompt"
              :app_id="String(route.params?.app_id)" />
          </div>
          <!-- 右侧应用能力：按 app_type 分支 -->
          <workflow-app-ability
            v-if="appType === 'workflow'"
            v-model:draft_app_config="draftAppConfigForm"
            :app_id="String(route.params?.app_id)"
            @reload-draft-app-config="refreshDraftAppConfig"
          />
          <agent-app-ability
            v-else
            v-model:draft_app_config="draftAppConfigForm"
            :app_id="String(route.params?.app_id)"
            @reload-draft-app-config="refreshDraftAppConfig"
          />
        </div>
      </div>
      <!-- 右侧调试与会话 -->
      <div class="min-w-[404px] flex min-h-0 flex-col overflow-hidden">
        <!-- 头部信息 -->
        <preview-debug-header :app_id="String(route.params?.app_id)"
          :app_type="String(props.app?.app_type ?? '')"
          :long_term_memory="draftAppConfigForm.long_term_memory"
          :debug_conversation_id="String(props.app?.debug_conversation_id ?? '')" />
        <!-- 对话窗口 -->
        <preview-debug-chat
          class="flex-1 min-h-0"
          :suggested_after_answer="draftAppConfigForm.suggested_after_answer"
          :opening_questions="draftAppConfigForm.opening_questions"
          :opening_statement="draftAppConfigForm.opening_statement"
          :capabilities="draftAppConfigForm.capabilities"
          :text_to_speech="draftAppConfigForm.text_to_speech"
          :app="props.app"
          :app_id="props.app?.id" />
      </div>
    </div>
  </div>
</template>

<style scoped></style>
