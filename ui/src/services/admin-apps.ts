import { type AgentMetadata, type CreateAppRequest, type GetDraftAppConfigResponse, type UpdateDraftAppConfigRequest } from '@/models/app'
import type { BasePaginatorResponse, BaseResponse } from '@/models/base'
import { del, get, post, request } from '@/utils/request'

export type AdminAppRecord = {
  id: string
  name: string
  icon?: string
  description?: string
  status?: string
  is_public?: boolean
  account_id?: string
  agent_metadata?: AgentMetadata
  created_at?: number
  updated_at?: number
}

export type AdminAppPaginator = {
  total_record: number
  total_page: number
  current_page: number
  page_size: number
}

export type AdminAppPageData = {
  list: AdminAppRecord[]
  paginator: AdminAppPaginator
}

type AdminAppPageResponse = BasePaginatorResponse<AdminAppRecord>

export type ListAdminAppsParams = {
  current_page: number
  page_size: number
  search?: string
  status?: string
}

export type UpdateAdminAppBasicInfoRequest = {
  name: string
  description: string
  icon: string
}

/**
 * 获取后台应用分页列表，并解包接口返回的 data 字段。
 */
export const listAdminApps = async (
  params: ListAdminAppsParams,
): Promise<AdminAppPageData> => {
  const query = new URLSearchParams({
    current_page: String(params.current_page),
    page_size: String(params.page_size),
  })
  if (params.search) query.set('search', params.search)
  if (params.status && params.status !== 'all') query.set('status', params.status)
  const response = await get<AdminAppPageResponse>(`/admin/apps?${query.toString()}`)
  return response.data
}

export const updateAdminAppMetadata = (appId: string, metadata: AgentMetadata) => {
  return request(`/admin/apps/${appId}`, {
    method: 'PATCH',
    body: { agent_metadata: metadata },
  })
}

/**
 * 更新应用基本信息（名称/描述/图标）。
 */
export const updateAdminAppBasicInfo = (
  appId: string,
  payload: UpdateAdminAppBasicInfoRequest,
) => {
  return request(`/admin/apps/${appId}`, {
    method: 'PATCH',
    body: payload,
  })
}

/**
 * 更新应用公开状态（上架/下架）。
 */
export const updateAdminAppIsPublic = async (
  appId: string,
  isPublic: boolean,
): Promise<AdminAppRecord> => {
  const response = await request<BaseResponse<AdminAppRecord>>(`/admin/apps/${appId}`, {
    method: 'PATCH',
    body: { is_public: isPublic },
  })
  return response.data
}

/**
 * 下架应用。
 */
export const offlineAdminApp = async (appId: string): Promise<Record<string, never>> => {
  const response = await post<BaseResponse<Record<string, never>>>(`/admin/apps/${appId}/offline`)
  return response.data
}

/**
 * 创建后台应用。admin 创建仅需要 name/icon/description。
 */
export const createAdminApp = async (
  body: CreateAppRequest,
): Promise<AdminAppRecord> => {
  const response = await post<BaseResponse<AdminAppRecord>>('/admin/apps', { body })
  return response.data
}

/**
 * 删除后台应用。
 */
export const deleteAdminApp = async (appId: string): Promise<Record<string, never>> => {
  const response = await del<BaseResponse<Record<string, never>>>(`/admin/apps/${appId}`)
  return response.data
}

export type BatchOperationResult = {
  succeeded: string[]
  failed: { id: string; reason: string }[]
}

/**
 * 批量下架应用。
 */
export const batchOfflineAdminApps = async (appIds: string[]): Promise<BatchOperationResult> => {
  const response = await post<BaseResponse<BatchOperationResult>>('/admin/apps/batch/offline', {
    body: { app_ids: appIds },
  })
  return response.data
}

/**
 * 批量删除应用。
 */
export const batchDeleteAdminApps = async (appIds: string[]): Promise<BatchOperationResult> => {
  const response = await post<BaseResponse<BatchOperationResult>>('/admin/apps/batch/delete', {
    body: { app_ids: appIds },
  })
  return response.data
}

/**
 * 获取后台应用草稿配置。
 */
export const getAdminAppDraftConfig = async (
  appId: string,
): Promise<GetDraftAppConfigResponse['data']> => {
  const response = await get<GetDraftAppConfigResponse>(`/admin/apps/${appId}/draft-app-config`)
  return response.data
}

/**
 * 更新后台应用草稿配置。
 */
export const updateAdminAppDraftConfig = async (
  appId: string,
  body: UpdateDraftAppConfigRequest,
): Promise<GetDraftAppConfigResponse['data']> => {
  const response = await post<GetDraftAppConfigResponse>(
    `/admin/apps/${appId}/draft-app-config`,
    { body },
  )
  return response.data
}
