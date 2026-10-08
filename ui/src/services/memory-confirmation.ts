// 用户侧机密记忆读取确认 API（首页助手 SSE 的 memory_confirmation_required 卡片）。
// 管理端对应端点位于 services/admin-agents.ts（/admin/agents/<id>/memory/confirmations/*）。
import { type BaseResponse } from '@/models/base'
import { type MemoryConfirmation } from '@/models/memory-confirmation'
import { get, post } from '@/utils/request'

export const getMemoryConfirmation = (id: string) => {
  return get<BaseResponse<MemoryConfirmation>>(`/memory/confirmations/${id}`)
}

export const confirmMemoryConfirmation = (id: string) => {
  return post<BaseResponse<MemoryConfirmation>>(`/memory/confirmations/${id}/confirm`)
}

export const cancelMemoryConfirmation = (id: string) => {
  return post<BaseResponse<MemoryConfirmation>>(`/memory/confirmations/${id}/cancel`)
}
