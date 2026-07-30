import { get, post } from '@/utils/request'
import {
  type CustomerUserDetailResponse,
  type CustomerUserListRequest,
  type CustomerUserListResponse,
  type CustomerUserResponse,
  type RevokeCustomerUserSessionsResponse,
} from '@/models/admin-customer-user'

export const listCustomerUsers = async (params: CustomerUserListRequest) => {
  const response = await get<CustomerUserListResponse>('/admin/users', { params })
  return response.data
}

export const getCustomerUser = async (id: string) => {
  const response = await get<CustomerUserDetailResponse>(`/admin/users/${id}`)
  return response.data
}

export const disableCustomerUser = async (id: string, reason: string) => {
  const response = await post<CustomerUserResponse>(`/admin/users/${id}/disable`, { body: { reason } })
  return response.data
}

export const enableCustomerUser = async (id: string) => {
  const response = await post<CustomerUserResponse>(`/admin/users/${id}/enable`)
  return response.data
}

export const revokeCustomerUserSessions = async (id: string) => {
  const response = await post<RevokeCustomerUserSessionsResponse>(`/admin/users/${id}/sessions/revoke`)
  return response.data
}
