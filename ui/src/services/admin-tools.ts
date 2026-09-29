import { del, get, post, request } from '@/utils/request'
import type {
  CreateApiToolProviderRequest,
  GetApiToolProviderResponse,
  GetApiToolProvidersWithPageResponse,
  UpdateApiToolProviderRequest,
} from '@/models/api-tool'
import type {
  GetBuiltinToolsResponse,
  GetCategoriesResponse,
} from '@/models/builtin-tool'
import type { UploadImageResponse } from '@/models/upload-file'
import type { BaseResponse } from '@/models/base'

export type GetAdminApiToolsParams = {
  current_page: number
  page_size: number
  search_word?: string
}

export type AdminApiToolPageData = GetApiToolProvidersWithPageResponse['data']

/**
 * 获取后台 API 工具分页列表，并解包接口返回的 data 字段。
 */
export const listAdminApiTools = async (
  params: GetAdminApiToolsParams,
): Promise<AdminApiToolPageData> => {
  const response = await get<GetApiToolProvidersWithPageResponse>('/admin/api-tools', { params })
  return response.data
}

/**
 * 创建后台 API 工具 Provider。
 */
export const createAdminApiTool = async (
  body: CreateApiToolProviderRequest,
): Promise<GetApiToolProviderResponse['data']> => {
  const response = await post<GetApiToolProviderResponse>('/admin/api-tools', { body })
  return response.data
}

/**
 * 获取单个后台 API 工具 Provider 详情。
 */
export const getAdminApiTool = async (
  id: string,
): Promise<GetApiToolProviderResponse['data']> => {
  const response = await get<GetApiToolProviderResponse>(`/admin/api-tools/${id}`)
  return response.data
}

/**
 * 更新后台 API 工具 Provider。
 */
export const updateAdminApiTool = async (
  id: string,
  body: UpdateApiToolProviderRequest,
): Promise<GetApiToolProviderResponse['data']> => {
  const response = await request<GetApiToolProviderResponse>(`/admin/api-tools/${id}`, {
    method: 'PATCH',
    body,
  })
  return response.data
}

/**
 * 删除后台 API 工具 Provider（进入回收站，可指定留存天数）。
 */
export const deleteAdminApiTool = async (
  id: string,
  retentionDays?: number,
): Promise<Record<string, never>> => {
  const response = await del<BaseResponse<Record<string, never>>>(`/admin/api-tools/${id}`, {
    body: retentionDays ? { retention_days: retentionDays } : undefined,
  })
  return response.data
}

/**
 * 生成后台插件图标预览（不保存到插件）。
 */
export const generateAdminIconPreview = (name: string, description: string) => {
  return post<BaseResponse<{ icon: string }>>('/admin/api-tools/generate-icon-preview', {
    body: { name, description },
  })
}

/**
 * 校验后台 OpenAPI Schema 数据。
 */
export const validateAdminOpenAPISchema = (openapi_schema: string) => {
  return post<BaseResponse<Record<string, unknown>>>('/admin/api-tools/validate-openapi-schema', {
    body: { openapi_schema },
  })
}

/**
 * 后台上传图片服务（multipart/form-data，由浏览器自动设置 Content-Type 边界）。
 */
export const adminUploadImage = (image: File) => {
  const formData = new FormData()
  formData.append('file', image)
  return post<UploadImageResponse>('/admin/upload-files/image', { body: formData })
}

/**
 * 获取后台所有内置工具提供者列表。
 */
export const getAdminBuiltinTools = () => {
  return get<GetBuiltinToolsResponse>('/admin/builtin-tools')
}

/**
 * 获取后台内置分类列表信息。
 */
export const getAdminBuiltinCategories = () => {
  return get<GetCategoriesResponse>('/admin/builtin-tools/categories')
}

/**
 * 内置工具凭证键的配置状态（admin 凭证页签）。
 * - source: 'db'=admin 已配置、'env'=env 兜底、''=未配置
 */
export type BuiltinCredentialKey = {
  key: string
  configured: boolean
  source: '' | 'db' | 'env'
  masked: string
}

export type BuiltinCredentialProvider = {
  provider: string
  label: string
  keys: BuiltinCredentialKey[]
}

/**
 * 列出"有凭证需求"的内置工具 provider 及其各键配置状态（掩码，不回明文）。
 */
export const listBuiltinToolCredentialProviders = () => {
  return get<BaseResponse<{ list: BuiltinCredentialProvider[] }>>(
    '/admin/builtin-tools/credential-providers',
  )
}

/**
 * 设置/更新某内置工具 provider 的凭证（加密入库）；空字符串表示清除该键。
 */
export const updateBuiltinToolCredential = (
  provider: string,
  credentials: Record<string, string>,
) => {
  return request<BaseResponse<{ provider: string; credentials: Record<string, string> }>>(
    `/admin/builtin-tools/credential-providers/${encodeURIComponent(provider)}`,
    { method: 'PUT', body: { credentials } },
  )
}

/**
 * 凭证齐备性检查（不发起外网调用）；返回缺失的凭证键清单。
 */
export const probeBuiltinToolCredential = (provider: string) => {
  return post<BaseResponse<{ ok: boolean; provider: string; missing: string[]; note: string }>>(
    `/admin/builtin-tools/credential-providers/${encodeURIComponent(provider)}/probe`,
  )
}
