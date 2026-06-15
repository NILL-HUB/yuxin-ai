import { get, post } from '@/utils/request'
import { type AppAssignmentListResponse, type AssignAppsResponse } from '@/models/app-assignment'

export const listUserAppAssignments = (userId: string) => {
  return get<AppAssignmentListResponse['data']>(`/admin/users/${userId}/app-assignments`)
}

export const assignAppsToUser = (userId: string, appIds: string[]) => {
  return post<AssignAppsResponse['data']>(`/admin/users/${userId}/app-assignments`, { body: { app_ids: appIds } })
}

export const revokeUserAppAssignment = (userId: string, assignmentId: string) => {
  return post(`/admin/users/${userId}/app-assignments/${assignmentId}/revoke`)
}
