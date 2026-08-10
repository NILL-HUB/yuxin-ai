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
