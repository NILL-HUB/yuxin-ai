import { get, post } from '@/utils/request'
import { type AppAssignmentListResponse, type AssignAppsResponse } from '@/models/app-assignment'

export const listUserAppAssignments = async (userId: string) => {
  const response = await get<AppAssignmentListResponse>(`/admin/users/${userId}/app-assignments`)
  return response.data
}

export const assignAppsToUser = async (userId: string, appIds: string[]) => {
  const response = await post<AssignAppsResponse>(`/admin/users/${userId}/app-assignments`, { body: { app_ids: appIds } })
  return response.data
}

export const revokeUserAppAssignment = (userId: string, assignmentId: string) => {
  return post(`/admin/users/${userId}/app-assignments/${assignmentId}/revoke`)
}
