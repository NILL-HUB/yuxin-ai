import {
  type AgentMetadata,
  type CreateAppRequest,
  type GetDraftAppConfigResponse,
  type GetPublishedConfigResponse,
  type GetVersionsResponse,
  type PromptCompareChatRequest,
  type RegenerateWebAppTokenResponse,
  type UpdateDraftAppConfigRequest,
} from '@/models/app'
import type { GetWechatConfigResponse, UpdateWechatConfigRequest } from '@/models/platform'
import type { GetAppAnalysisResponse } from '@/models/analysis'
import type { BasePaginatorResponse, BaseResponse } from '@/models/base'
import { type AppTag } from '@/services/public-app'
import { del, get, post, request, ssePost } from '@/utils/request'

export type { AppTag }

export type AdminAppRecord = {
  id: string
  name: string
  icon?: string
  description?: string
  status?: string
  app_type?: string
  is_public?: boolean
  account_id?: string
  agent_metadata?: AgentMetadata
  debug_conversation_id?: string
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

/**
 * 获取后台应用单条记录（含 app_type / debug_conversation_id 等字段）。
 */
export const getAdminApp = async (appId: string): Promise<AdminAppRecord> => {
  const response = await get<BaseResponse<AdminAppRecord>>(`/admin/apps/${appId}`)
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

/**
 * 获取后台应用的发布配置信息。
 */
export const getAdminAppPublishedConfig = (appId: string) => {
  return get<GetPublishedConfigResponse>(`/admin/apps/${appId}/published-config`)
}

/**
 * 重新生成后台应用 WebApp 的凭证标识。
 */
export const regenerateAdminAppWebAppToken = (appId: string) => {
  return post<RegenerateWebAppTokenResponse>(
    `/admin/apps/${appId}/published-config/regenerate-web-app-token`,
  )
}

/**
 * 获取后台应用的微信公众号发布配置信息。
 */
export const getAdminAppWechatConfig = (appId: string) => {
  return get<GetWechatConfigResponse>(`/admin/apps/${appId}/wechat-config`)
}

/**
 * 更新后台应用的微信公众号发布配置。
 */
export const updateAdminAppWechatConfig = (
  appId: string,
  body: UpdateWechatConfigRequest,
) => {
  return post<BaseResponse<any>>(`/admin/apps/${appId}/wechat-config`, { body })
}

/**
 * 分享后台应用到广场。
 */
export const shareAdminAppToSquare = (appId: string, tags: string) => {
  return post<BaseResponse<any>>(`/admin/apps/${appId}/share-to-square`, { body: { tags } })
}

/**
 * 取消分享后台应用到广场。
 */
export const unshareAdminAppFromSquare = (appId: string) => {
  return post<BaseResponse<any>>(`/admin/apps/${appId}/unshare-from-square`)
}

/**
 * 获取后台应用标签列表。
 */
export const getAdminAppTags = () => {
  return get<BaseResponse<{ tags: AppTag[] }>>('/admin/apps/tags')
}

/**
 * 后台提示词对比调试，该接口为流式事件输出。
 */
export const adminPromptCompareChat = (
  appId: string,
  req: PromptCompareChatRequest,
  onData: (event_response: Record<string, any>) => void,
) => {
  return ssePost(`/admin/apps/${appId}/prompt-compare/chat`, { body: req }, onData)
}

/**
 * 停止后台某次提示词对比调试会话。
 */
export const stopAdminPromptCompareChat = (appId: string, taskId: string) => {
  return post<BaseResponse<any>>(
    `/admin/apps/${appId}/prompt-compare/tasks/${taskId}/stop`,
  )
}

/**
 * 获取后台应用统计分析数据。
 */
export const getAdminAppAnalysis = (appId: string) => {
  return get<GetAppAnalysisResponse>(`/admin/apps/${appId}/analysis`)
}

/**
 * 获取后台应用版本对比数据（草稿 + 发布历史）。
 */
export const getAdminAppVersions = (appId: string) => {
  return get<GetVersionsResponse>(`/admin/apps/${appId}/versions`)
}
