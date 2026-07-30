import { get, post } from '@/utils/request'
import type { BaseResponse } from '@/models/base'
import type {
  AdminOrchestrationFlag,
  AdminOrchestrationReleaseCheck,
  UpdateAdminOrchestrationFlagRequest,
} from '@/models/admin-orchestration-flag'

export const listAdminOrchestrationFlags = async (): Promise<AdminOrchestrationFlag[]> => {
  const response = await get<BaseResponse<AdminOrchestrationFlag[]>>('/admin/orchestration-flags')
  return response.data
}

export const updateAdminOrchestrationFlag = async (
  code: string,
  data: UpdateAdminOrchestrationFlagRequest,
): Promise<AdminOrchestrationFlag> => {
  const response = await post<BaseResponse<AdminOrchestrationFlag>>(`/admin/orchestration-flags/${code}`, {
    body: data,
  })
  return response.data
}

export const getAdminOrchestrationReleaseCheck = async (): Promise<AdminOrchestrationReleaseCheck> => {
  const response = await get<BaseResponse<AdminOrchestrationReleaseCheck>>('/admin/orchestration-release-check')
  return response.data
}
