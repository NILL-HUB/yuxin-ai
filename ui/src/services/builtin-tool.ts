import { get } from '@/utils/request'
import {
  type GetBuiltinToolResponse,
  type GetBuiltinToolsResponse,
  type GetCategoriesResponse,
} from '@/models/builtin-tool'

const storePrefix = (admin: boolean) => (admin ? '/admin/store' : '')

// 获取内置分类列表信息
export const getCategories = (admin = false) => {
  return get<GetCategoriesResponse>(`${storePrefix(admin)}/builtin-tools/categories`)
}

// 获取所有内置工具提供者列表
export const getBuiltinTools = (admin = false) => {
  return get<GetBuiltinToolsResponse>(`${storePrefix(admin)}/builtin-tools`)
}

// 获取内置工具详情
export const getBuiltinTool = (provider_name: string, tool_name: string, admin = false) => {
  return get<GetBuiltinToolResponse>(
    `${storePrefix(admin)}/builtin-tools/${provider_name}/tools/${tool_name}`,
  )
}
