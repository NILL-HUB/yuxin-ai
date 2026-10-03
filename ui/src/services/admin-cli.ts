import { get, post, put, del } from '@/utils/request'
import type { BaseResponse } from '@/models/base'

/** 能力说明书单条：{ 工具ID: { description, parameters } } */
export interface CliToolSpec {
  description?: string
  parameters?: Record<string, unknown>
}

export interface CliProvider {
  id: string
  name: string
  label: string
  description: string
  category: string
  command: string
  args: string[]
  tool_schema: Record<string, CliToolSpec>
  task_keywords: string[]
  timeout_seconds: number
  enabled: boolean
  is_public: boolean
  tool_count: number
}

/** POST/PUT 请求体；PUT 仅处理传入字段（env 未传即保持原值） */
export interface CliProviderPayload {
  name?: string
  label?: string
  description?: string
  category?: string
  command?: string
  args?: string[]
  env?: Record<string, string>
  tool_schema?: Record<string, CliToolSpec>
  task_keywords?: string[]
  timeout_seconds?: number
  enabled?: boolean
}

export const listCliProviders = async (): Promise<CliProvider[]> => {
  const response = await get<BaseResponse<{ items: CliProvider[] }>>('/admin/cli')
  return response.data.items
}

export const createCliProvider = async (payload: CliProviderPayload): Promise<string> => {
  const response = await post<BaseResponse<{ id: string }>>('/admin/cli', { body: payload })
  return response.data.id
}

export const updateCliProvider = async (id: string, payload: CliProviderPayload): Promise<void> => {
  await put<BaseResponse<unknown>>(`/admin/cli/${id}`, { body: payload })
}

export const deleteCliProvider = async (id: string): Promise<void> => {
  await del<BaseResponse<unknown>>(`/admin/cli/${id}`)
}
