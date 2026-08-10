import {
  type BasePaginatorRequest,
  type BasePaginatorResponse,
  type BaseResponse,
} from '@/models/base' // 获取应用信息响应结构
import type { SkillBinding, SkillBindingRequest } from '@/models/skill'

// 应用类型枚举：chatbot 对话型 / agent 智能体 / workflow 工作流 / completion 补全型
export type AppType = 'chatbot' | 'agent' | 'workflow' | 'completion'

// 应用类型选项（用于选择器）
export const APP_TYPE_OPTIONS: Array<{
  value: AppType
  label: string
  labelEn: string
  description: string
  descriptionEn: string
  icon: string
}> = [
  {
    value: 'chatbot',
    label: '对话型',
    labelEn: 'Chatbot',
    description: '多轮对话，支持上下文记忆',
    descriptionEn: 'Multi-turn conversation with context memory',
    icon: 'icon-message',
  },
  {
    value: 'agent',
    label: 'Agent 型',
    labelEn: 'Agent',
    description: '带工具调用的智能体',
    descriptionEn: 'Intelligent agent with tool calling',
    icon: 'icon-robot',
  },
  {
    value: 'workflow',
    label: '工作流型',
    labelEn: 'Workflow',
    description: '绑定工作流，对话式调用',
    descriptionEn: 'Bind a workflow, called via conversation',
    icon: 'icon-mind-mapping',
  },
  {
    value: 'completion',
    label: '补全型',
    labelEn: 'Completion',
    description: '单轮文本生成，无对话记忆',
    descriptionEn: 'Single-turn text generation, no memory',
    icon: 'icon-edit',
  },
]

// 应用版本类型
export type AppVersion = {
  id: string
  app_id: string
  version: number
  config_type: string
  config: Record<string, unknown>
  is_current_published: boolean
  label: string
  summary: string
  created_at: number
  updated_at: number
}

export type McpBinding = {
  name: string
  description: string
  transport: string
  url: string
  command: string
  enabled: boolean
  headers: { key: string; value: string }[]
  tool_names: string[]
  timeout_seconds: number
  args: string[]
  env: Record<string, string>
  provider_key?: string
  source_type?: string
  source_key?: string
  source_url?: string
  label?: string
  icon?: string
  category?: string
}

export type McpToolSnapshot = {
  binding_identity: string
  binding_hash: string
  binding: McpBinding
  status: string
  tool_definitions: Record<string, unknown>[]
  tool_names: string[]
  tool_count: number
  schema_hash: string
  last_attempt_at: number
  last_success_at: number | null
  last_error: string
  retry_count: number
  retryable: boolean
}

export type AgentBinding = {
  app_id: string
  invoke_mode?: 'a2a' | 'tool'
  name?: string
  icon?: string
  description?: string
  source_scope?: 'public' | 'own'
  is_public?: boolean
  status?: string
  tool_name?: string
}

export type AgentBindingRequest = {
  app_id: string
}

export type AgentMetadata = {
  primary_pool: string
  secondary_pools: string[]
  capabilities: string[]
  task_types: string[]
  input_modalities: string[]
  output_modalities: string[]
  risk_level: 'safe' | 'medium' | 'high'
  model_tier: 'cheap' | 'standard' | 'strong'
  model_id: string
  key_policy: string
  cost_level: 'low' | 'medium' | 'high'
  routing_priority: number
  allowed_tool_categories: string[]
  quality_score: number
  success_rate: number
  latency_p95: number
  max_context_tokens: number
  enabled: boolean
}

// 获取应用信息响应结构
export type GetAppResponse = BaseResponse<{
  id: string
  debug_conversation_id: string
  name: string
  icon: string
  description: string
  status: string
  app_type: AppType // 应用类型，创建后不可更改
  is_public: boolean
  category: string
  draft_updated_at: number
  updated_at: number
  created_at: number
}>

// 新增应用请求结构
export type CreateAppRequest = {
  name: string
  icon: string
  description: string
  app_type?: AppType // 应用类型，可选，默认 chatbot
}

// 更新应用请求结构
export type UpdateAppRequest = {
  name: string
  icon: string
  description: string
  agent_metadata?: Partial<AgentMetadata>
}

// 获取应用分页列表数据请求
export type GetAppsWithPageRequest = BasePaginatorRequest & {
  search_word: string
  published_only?: boolean
}

// 获取应用分页列表数据响应
export type GetAppsWithPageResponse = BasePaginatorResponse<{
  id: string
  name: string
  icon: string
  description: string
  preset_prompt: string
  model_config: {
    provider: string
    model: string
  }
  status: string
  app_type?: AppType // 应用类型，向后兼容（旧数据可能为空，前端按 chatbot 兜底）
  is_public: boolean
  creator_name: string
  creator_avatar: string
  draft_updated_at: number
  updated_at: number
  created_at: number
}>

// 获取特定应用的草稿配置响应结构
export type GetDraftAppConfigResponse = BaseResponse<{
  id: string
  model_config: { provider: string; model: string; parameters: Record<string, unknown> }
  capabilities?: {
    requested_model: { provider: string; model: string }
    effective_model: { provider: string; model: string }
    features: string[]
    requested_features: string[]
    image_input: {
      enabled: boolean
      via_fallback: boolean
      policy: string
      requested_model_supports: boolean
      effective_model_supports: boolean
      fallback_model: { provider: string; model: string } | null
      fallback_model_supports: boolean
      reason_code: string
      message: string
    }
    image_output: { enabled: boolean; reason_code: string }
    artifact_output: { enabled: boolean; reason_code: string }
  }
  dialog_round: number
  preset_prompt: string
  tools: {
    type: string
    provider: { id: string; name: string; label: string; icon: string; description: string }
    tool: {
      id: string
      name: string
      label: string
      description: string
      params: Record<string, unknown>
    }
  }[]
  mcp_bindings: McpBinding[]
  mcp_tool_snapshots: McpToolSnapshot[]
  agent_bindings: AgentBinding[]
  skills: SkillBinding[]
  workflows: { id: string; name: string; icon: string; description: string }[]
  datasets: { id: string; name: string; icon: string; description: string }[]
  // 新版知识库 id 列表，与 datasets 同级，二者可共存（向后兼容：旧配置无该字段）
  knowledge_base_ids?: string[]
  // 新版知识库展示信息列表（后端 _process_and_validate_knowledge_base_ids 返回，含 id/name/description）
  knowledge_bases?: { id: string; name: string; description: string }[]
  retrieval_config: { retrieval_strategy: string; k: number; score: number }
  // App 级别 embedding 模型 ID（决定用户记忆向量存储维度，为空则使用系统默认）
  embedding_model_id?: string
  long_term_memory: { enable: boolean }
  opening_statement: string
  opening_questions: string[]
  speech_to_text: { enable: boolean }
  text_to_speech: { enable: boolean; voice: string; auto_play: boolean }
  suggested_after_answer: { enable: boolean }
  review_config: {
    enable: boolean
    keywords: string[]
    inputs_config: { enable: boolean; preset_response: string }
    outputs_config: { enable: boolean }
  }
  workflow_id: string | null // Workflow 应用绑定的主工作流 ID（仅 app_type=workflow 时有效）
  workflow_detail?: { id: string; name: string; icon: string; description: string } | null // 绑定的工作流详情
  updated_at: number
  created_at: number
}>

// App 草稿配置编辑表单结构（编排区各组件 v-model 绑定的最小字段集）
export type DraftAppConfigForm = {
  dialog_round: number
  model_config: { provider: string; model: string; parameters: Record<string, unknown> }
  capabilities?: GetDraftAppConfigResponse['data']['capabilities']
  preset_prompt: string
  long_term_memory: { enable: boolean }
  opening_statement: string
  opening_questions: string[]
  suggested_after_answer: { enable: boolean }
  review_config: {
    enable: boolean
    keywords: string[]
    inputs_config: { enable: boolean; preset_response: string }
    outputs_config: { enable: boolean }
  }
  knowledge_base_ids: string[]
  retrieval_config: { retrieval_strategy: string; k: number; score: number }
  embedding_model_id?: string
  tools: GetDraftAppConfigResponse['data']['tools']
  mcp_bindings: McpBinding[]
  mcp_tool_snapshots: McpToolSnapshot[]
  agent_bindings: AgentBinding[]
  skills: SkillBinding[]
  workflows: { id: string; name: string; icon: string; description: string }[]
  workflow_id: string | null
  workflow_detail: { id: string; name: string; icon: string; description: string } | null
  speech_to_text: { enable: boolean }
  text_to_speech: { enable: boolean; voice: string; auto_play: boolean }
}

// 更新特定应用的草稿配置请求结构
export type UpdateDraftAppConfigRequest = {
  model_config?: { provider: string; model: string; parameters: Record<string, unknown> }
  dialog_round?: number
  preset_prompt?: string
  tools?: { type: string; provider_id: string; tool_id: string; params: Record<string, unknown> }[]
  mcp_bindings?: McpBinding[]
  agent_bindings?: AgentBindingRequest[]
  skills?: SkillBindingRequest[]
  workflows?: string[]
  datasets?: string[]
  // 新版知识库 id 列表，与 datasets 同级，二者可共存
  knowledge_base_ids?: string[]
  retrieval_config?: { retrieval_strategy: string; k: number; score: number }
  // App 级别 embedding 模型 ID（决定用户记忆向量存储维度，为空则使用系统默认）
  embedding_model_id?: string
  long_term_memory?: { enable: boolean }
  opening_statement?: string
  opening_questions?: string[]
  speech_to_text?: { enable: boolean }
  text_to_speech?: { enable: boolean; voice: string; auto_play: boolean }
  suggested_after_answer?: { enable: boolean }
  review_config?: {
    enable: boolean
    keywords: string[]
    inputs_config: { enable: boolean; preset_response: string }
    outputs_config: { enable: boolean }
  }
  workflow_id?: string | null
}

export type PromptCompareHistoryItem = {
  query: string
  answer: string
}

export type PromptCompareChatRequest = {
  lane_id: string
  query: string
  preset_prompt: string
  model_config: { provider: string; model: string; parameters: Record<string, unknown> }
  history: PromptCompareHistoryItem[]
}

// 获取应用的调试会话消息列表响应结构
export type GetDebugConversationMessagesWithPageResponse = BasePaginatorResponse<{
  id: string
  conversation_id: string
  query: string
  image_urls: string[]
  input_parts: Array<Record<string, unknown>>
  answer: string
  answer_parts: Array<Record<string, unknown>>
  artifacts: Array<Record<string, unknown>>
  total_token_count: number
  latency: number
  agent_thoughts: {
    id: string
    position: number
    event: string
    thought: string
    observation: string
    tool: string
    tool_input: Record<string, unknown>
    latency: number
    created_at: number
  }[]
  suggested_questions: string[]
  created_at: number
}>

// 获取应用的发布历史配置列表分页响应结构
export type GetPublishHistoriesWithPageResponse = BasePaginatorResponse<{
  id: string
  app_id: string
  version: number
  config_type: string
  config: Record<string, unknown>
  updated_at: number
  created_at: number
  is_current_published: boolean
  label: string
  summary: string
}>

export type GetVersionsResponse = BaseResponse<{
  list: AppVersion[]
}>

// 获取应用的调试会话消息列表请求结构
export type GetDebugConversationMessagesWithPageRequest = BasePaginatorRequest & {
  created_at?: number
  conversation_id?: string
}

// 获取应用发布配置响应结构
export type GetPublishedConfigResponse = BaseResponse<{
  web_app: {
    token: string
    status: string
  }
  is_public: boolean
  category: string
}>

// 重新生成WebApp凭证标识响应结构
export type RegenerateWebAppTokenResponse = BaseResponse<{
  token: string
}>
