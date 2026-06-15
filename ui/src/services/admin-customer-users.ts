import { get, post } from '@/utils/request'
import {
  type CustomerUserDetailResponse,
  type CustomerUserListRequest,
  type CustomerUserListResponse,
  type CustomerUserResponse,
  type RevokeCustomerUserSessionsResponse,
} from '@/models/admin-customer-user'

export const listCustomerUsers = (params: CustomerUserListRequest) => {
  return get<CustomerUserListResponse['data']>('/admin/users', { params })
}

export const getCustomerUser = (id: string) => {
  return get<CustomerUserDetailResponse['data']>(`/admin/users/${id}`)
}

export const disableCustomerUser = (id: string, reason: string) => {
  return post<CustomerUserResponse['data']>(`/admin/users/${id}/disable`, { body: { reason } })
}

export const enableCustomerUser = (id: string) => {
  return post<CustomerUserResponse['data']>(`/admin/users/${id}/enable`)
}

export const revokeCustomerUserSessions = (id: string) => {
  return post<RevokeCustomerUserSessionsResponse['data']>(`/admin/users/${id}/sessions/revoke`)
}
