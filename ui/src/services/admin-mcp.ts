import { del, get, post, request } from '@/utils/request'
import type {
  CreateMcpProviderRequest,
  GetMcpCategoriesResponse,
  GetMcpProviderResponse,
  GetMcpProvidersWithPageRequest,
  GetMcpProvidersWithPageResponse,
  UpdateMcpProviderRequest,
} from '@/models/mcp'
import type { BaseResponse } from '@/models/base'

/**
 * 获取后台 MCP 分类列表（管理员视角）。
 */
export const getAdminMcpCategories = () => {
  return get<GetMcpCategoriesResponse>('/admin/mcp/categories')
}

/**
 * 获取后台 MCP Provider 分页列表，并解包接口返回的 data 字段。
 */
export const listAdminMcpProviders = async (
  params: GetMcpProvidersWithPageRequest,
): Promise<GetMcpProvidersWithPageResponse['data']> => {
  const response = await get<GetMcpProvidersWithPageResponse>('/admin/mcp', { params })
  return response.data
}

/**
 * 创建后台 MCP Provider。
 */
export const createAdminMcp = async (
  body: CreateMcpProviderRequest,
): Promise<GetMcpProviderResponse['data']> => {
  const response = await post<GetMcpProviderResponse>('/admin/mcp', { body })
  return response.data
}

/**
 * 获取后台 MCP Provider 详情（管理员视角，不校验账号归属）。
 * 返回结构与 mcp.ts 的 getMcpProvider 保持一致，便于复用模态框。
 */
export const getAdminMcp = (id: string) => {
  return get<GetMcpProviderResponse>(`/admin/mcp/${id}`)
}

/**
 * 更新后台 MCP Provider（管理员视角，不校验账号归属）。
 * 返回结构与 mcp.ts 的 updateMcpProvider 保持一致。
 */
export const updateAdminMcp = (id: string, body: UpdateMcpProviderRequest) => {
  return request<BaseResponse<any>>(`/admin/mcp/${id}`, {
    method: 'PATCH',
    body,
  })
}

/**
 * 重新生成后台 MCP Provider 图标（管理员视角，不校验账号归属）。
 * 返回结构与 mcp.ts 的 regenerateMcpIcon 保持一致。
 */
export const regenerateAdminMcpIcon = (id: string) => {
  return post<BaseResponse<{ icon: string }>>(`/admin/mcp/${id}/regenerate-icon`)
}

/**
 * 发布后台 MCP Provider 到广场（管理员视角，不校验账号归属）。
 */
export const publishAdminMcp = (id: string) => {
  return post<BaseResponse<null>>(`/admin/mcp/${id}/publish`)
}

/**
 * 取消发布 / 强制下架后台 MCP Provider（管理员视角，不校验账号归属）。
 */
export const unpublishAdminMcp = (id: string) => {
  return post<BaseResponse<null>>(`/admin/mcp/${id}/unpublish`)
}

/**
 * 删除后台 MCP Provider。
 */
export const deleteAdminMcp = async (id: string): Promise<Record<string, never>> => {
  const response = await del<BaseResponse<Record<string, never>>>(`/admin/mcp/${id}`)
  return response.data
}

/**
 * 批量导入结果条目。
 */
export type McpImportResultItem = {
  name: string
  provider_key?: string
  reason?: string
}

/**
 * 批量导入结果汇总。
 */
export type McpImportBatchResult = {
  imported: McpImportResultItem[]
  skipped: McpImportResultItem[]
  failed: McpImportResultItem[]
}

/**
 * URL 预览返回的单个工具信息。
 */
export type McpUrlPreviewTool = {
  name: string
  label?: string
  description?: string
  inputs?: Array<{
    name: string
    type?: string
    description?: string
    required?: boolean
  }>
}

/**
 * URL 预览结果。
 */
export type McpUrlPreviewResult = {
  tools: McpUrlPreviewTool[]
}

/**
 * 通过标准 mcp.json 批量导入 MCP 服务器，并解包接口返回的 data 字段。
 */
export const importAdminMcpJson = async (
  config_json: string,
  overwrite = false,
): Promise<McpImportBatchResult> => {
  const response = await post<BaseResponse<McpImportBatchResult>>(
    '/admin/mcp/import-mcp-json',
    { body: { config_json, overwrite } },
  )
  return response.data
}

/**
 * 预览指定 URL 下的 MCP 工具列表，并解包接口返回的 data 字段。
 */
export const previewAdminMcpUrl = async (
  url: string,
  transport = 'http',
  headers: Array<{ key: string; value: string }> = [],
): Promise<McpUrlPreviewResult> => {
  const response = await post<BaseResponse<McpUrlPreviewResult>>(
    '/admin/mcp/preview-url',
    { body: { url, transport, headers } },
  )
  return response.data
}

/**
 * 通过 URL 一键导入 MCP 服务器，并解包接口返回的 data 字段。
 */
export const importAdminMcpUrl = async (body: {
  url: string
  name: string
  description?: string
  transport?: string
  headers?: Array<{ key: string; value: string }>
  category?: string
  icon?: string
}): Promise<GetMcpProviderResponse['data']> => {
  const response = await post<GetMcpProviderResponse>('/admin/mcp/import-url', { body })
  return response.data
}

/**
 * 通过单 server JSON 配置导入 MCP 服务器，并解包接口返回的 data 字段。
 */
export const importAdminMcpJsonConfig = async (
  config_json: string,
  overwrite = false,
): Promise<McpImportBatchResult> => {
  const response = await post<BaseResponse<McpImportBatchResult>>(
    '/admin/mcp/import-json',
    { body: { config_json, overwrite } },
  )
  return response.data
}
