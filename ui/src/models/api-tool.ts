import { type BasePaginatorResponse, type BaseResponse } from '@/models/base'

// 获取自定义API插件响应接口
export type GetApiToolProvidersWithPageResponse = BasePaginatorResponse<{
  id: string
  name: string
  icon: string
  description: string
  headers: Array<Record<string, unknown>>
  tools: Array<Record<string, unknown>>
  creator_name: string
  creator_avatar: string
  updated_at: number
  created_at: number
}>

// 新增自定义API插件提供者请求结构
export type CreateApiToolProviderRequest = {
  name: string
  icon: string
  openapi_schema: string
  headers: Array<Record<string, unknown>>
}

// 更新自定义API工具提供者请求与响应结构
export type UpdateApiToolProviderRequest = {
  name: string
  icon: string
  openapi_schema: string
  headers: Array<Record<string, unknown>>
}

// 获取自定义API工具提供者响应结构体
export type GetApiToolProviderResponse = BaseResponse<{
  id: string
  name: string
  icon: string
  openapi_schema: string
  headers: Array<Record<string, unknown>>
  updated_at: number
  created_at: number
}>

// 获取自定义API工具详情
export type GetApiToolResponse = BaseResponse<{
  id: string
  name: string
  description: string
  provider: {
    id: string
    name: string
    icon: string
    headers: { key: string; value: string }[]
    description: string
  }
  inputs: {
    type: string
    name: string
    required: boolean
    description: string
  }[]
}>
