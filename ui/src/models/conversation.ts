import { type BasePaginatorRequest, type BasePaginatorResponse, type BaseResponse } from '@/models/base'

// 获取指定会话消息列表请求结构
export type GetConversationMessagesWithPageRequest = BasePaginatorRequest & {
  created_at: number
}

// 获取指定会话消息列表响应结构
/** 会话算力消耗汇总：每条消息的实扣额 + 会话累计（服务端权威口径）。 */
export type ConversationCreditsSummary = {
  total_credits: number
  message_credits: Record<string, number>
}

export type GetConversationMessagesWithPageResponse = BasePaginatorResponse<{
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

export type RecentConversation = {
  id: string
  name: string
  source_type: 'assistant_agent' | 'app_debugger' | 'public_app' | 'schedule'
  invoke_from?: string
  app_id: string
  app_name: string
  agent_name: string
  message_id: string
  is_active: boolean
  latest_message_at: number
  created_at: number
  human_message: string
  ai_message: string
}

export type GetRecentConversationsResponse = BaseResponse<RecentConversation[]>
