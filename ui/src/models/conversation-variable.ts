// 会话变量类型定义
import type { BaseResponse } from '@/models/base'

// 会话变量值类型
export type ConversationVariableValueType =
  | 'string'
  | 'int'
  | 'float'
  | 'boolean'
  | 'json'

// 会话变量值类型（含 auto 推断）
export type ConversationVariableRequestValueType =
  | ConversationVariableValueType
  | 'auto'

// 会话变量实体
export type ConversationVariable = {
  id: string
  conversation_id: string
  name: string
  value_type: ConversationVariableValueType
  value: unknown
  updated_at: string | null
  created_at: string | null
}

// 设置会话变量请求
export type SetVariableReq = {
  name: string
  value: unknown
  value_type: ConversationVariableRequestValueType
}

// 批量设置会话变量请求
export type BatchSetVariablesReq = {
  variables: Record<string, unknown>
}

// 获取会话变量列表响应
export type GetConversationVariablesResponse = BaseResponse<{
  list: ConversationVariable[]
}>

// 设置会话变量响应
export type SetConversationVariableResponse = BaseResponse<ConversationVariable>

// 批量设置会话变量响应
export type BatchSetConversationVariablesResponse = BaseResponse<{
  list: ConversationVariable[]
}>
