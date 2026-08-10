import { ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  getAdminAppDraftConfig,
  getAdminAppPublishedConfig,
  getAdminAppVersions,
  regenerateAdminAppWebAppToken,
  updateAdminAppDraftConfig,
} from '@/services/admin-apps'
import type {
  AppVersion,
  DraftAppConfigForm,
  GetPublishedConfigResponse,
  UpdateDraftAppConfigRequest,
} from '@/models/app'
import { getErrorMessage } from '@/utils/error'
import { i18n } from '@/i18n'

const t = (key: string, params?: Record<string, unknown>) =>
  params ? i18n.global.t(key, params) : i18n.global.t(key)

export const useGetAdminPublishedConfig = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const published_config = ref<GetPublishedConfigResponse['data']>({} as GetPublishedConfigResponse['data'])

  // 2.定义加载数据函数
  const loadPublishedConfig = async (appId: string) => {
    try {
      loading.value = true
      const resp = await getAdminAppPublishedConfig(appId)
      published_config.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, published_config, loadPublishedConfig }
}

export const useRegenerateAdminWebAppToken = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const token = ref<string>('')

  // 2.定义重生成WebAppToken函数
  const handleRegenerateWebAppToken = async (appId: string) => {
    try {
      loading.value = true
      const resp = await regenerateAdminAppWebAppToken(appId)
      Message.success(t('appStudio.published.web.regenerateSuccess'))
      token.value = resp.data.token
    } finally {
      loading.value = false
    }
  }

  return { loading, token, handleRegenerateWebAppToken }
}

export const useGetAdminDraftAppConfig = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const draftAppConfigForm = ref<DraftAppConfigForm>({} as DraftAppConfigForm)

  // 2.定义加载数据函数
  const loadDraftAppConfig = async (appId: string) => {
    try {
      // 2.1 修改loading状态并获取数据
      loading.value = true
      const data = await getAdminAppDraftConfig(appId)

      // 2.2 将数据同步到表单中（字段映射与用户端保持一致）
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
        knowledge_base_ids: data.knowledge_base_ids || [],
        retrieval_config: data.retrieval_config,
        tools: data.tools,
        mcp_bindings: data.mcp_bindings || [],
        mcp_tool_snapshots: data.mcp_tool_snapshots || [],
        agent_bindings: data.agent_bindings || [],
        skills: data.skills,
        workflows: data.workflows,
        workflow_id: data.workflow_id ?? null,
        workflow_detail: data.workflow_detail ?? null,
        speech_to_text: data.speech_to_text,
        text_to_speech: data.text_to_speech,
      } as DraftAppConfigForm
    } finally {
      loading.value = false
    }
  }

  return { loading, draftAppConfigForm, loadDraftAppConfig }
}

export const useUpdateAdminDraftAppConfig = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)

  // 2.定义更新草稿配置处理器
  const handleUpdateDraftAppConfig = async (
    appId: string,
    draftAppConfig: UpdateDraftAppConfigRequest,
  ) => {
    try {
      loading.value = true
      await updateAdminAppDraftConfig(appId, draftAppConfig)
    } catch (error: unknown) {
      const msg = getErrorMessage(error, t('appStudio.shell.updateDraftFailed'))
      Message.error(msg)
      throw error
    } finally {
      loading.value = false
    }
  }

  return { loading, handleUpdateDraftAppConfig }
}

export const useGetAdminVersions = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const versions = ref<AppVersion[]>([])

  // 2.定义加载版本数据函数
  const loadVersions = async (appId: string) => {
    try {
      loading.value = true
      const resp = await getAdminAppVersions(appId)
      versions.value = resp.data.list
    } finally {
      loading.value = false
    }
  }

  return { loading, versions, loadVersions }
}
