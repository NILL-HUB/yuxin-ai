import { type AgentMetadata } from '@/models/app'
import { get, request } from '@/utils/request'

export type ListAdminAppsParams = {
  page: number
  page_size: number
}

export const listAdminApps = (params: ListAdminAppsParams) => {
  const query = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.page_size),
  })
  return get(`/admin/apps?${query.toString()}`)
}

export const updateAdminAppMetadata = (appId: string, metadata: AgentMetadata) => {
  return request(`/admin/apps/${appId}`, {
    method: 'PATCH',
    body: { agent_metadata: metadata },
  })
}
