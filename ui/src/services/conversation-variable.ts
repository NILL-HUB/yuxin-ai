import { get, post } from '@/utils/request'
import type { BaseResponse } from '@/models/base'
import type {
  BatchSetConversationVariablesResponse,
  BatchSetVariablesReq,
  ConversationVariable,
  GetConversationVariablesResponse,
  SetConversationVariableResponse,
  SetVariableReq,
} from '@/models/conversation-variable'

// 获取指定会话的所有变量列表
export const getConversationVariables = (conversation_id: string) =>
  get<GetConversationVariablesResponse>(`/conversations/${conversation_id}/variables`)

// 设置（新增/更新）指定会话的变量
export const setConversationVariable = (conversation_id: string, req: SetVariableReq) =>
  post<SetConversationVariableResponse>(`/conversations/${conversation_id}/variables`, { body: req })

// 批量设置指定会话的变量
export const batchSetConversationVariables = (
  conversation_id: string,
  req: BatchSetVariablesReq,
) =>
  post<BatchSetConversationVariablesResponse>(`/conversations/${conversation_id}/variables/batch`, {
    body: req,
  })

// 删除指定会话的单个变量
export const deleteConversationVariable = (conversation_id: string, name: string) =>
  post<BaseResponse<any>>(
    `/conversations/${conversation_id}/variables/${encodeURIComponent(name)}/delete`,
  )

// 清空指定会话的所有变量
export const deleteAllConversationVariables = (conversation_id: string) =>
  post<BaseResponse<{ count: number }>>(
    `/conversations/${conversation_id}/variables/delete-all`,
  )

// 重新导出类型，方便调用方统一从 service 引入
export type {
  BatchSetVariablesReq,
  ConversationVariable,
  SetVariableReq,
}
