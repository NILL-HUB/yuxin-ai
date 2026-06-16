import { get, post } from '@/utils/request'
import type {
  AdminOrchestrationFlag,
  AdminOrchestrationReleaseCheck,
  UpdateAdminOrchestrationFlagRequest,
} from '@/models/admin-orchestration-flag'

export const listAdminOrchestrationFlags = () => {
  return get<AdminOrchestrationFlag[]>('/admin/orchestration-flags')
}

export const updateAdminOrchestrationFlag = (
  code: string,
  data: UpdateAdminOrchestrationFlagRequest,
) => {
  return post<AdminOrchestrationFlag>(`/admin/orchestration-flags/${code}`, {
    body: data,
  })
}

export const getAdminOrchestrationReleaseCheck = () => {
  return get<AdminOrchestrationReleaseCheck>('/admin/orchestration-release-check')
}
