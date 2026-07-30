// ui/src/services/admin-prompt-template.ts
import { get, patch, post } from '@/utils/request'

export interface PromptTemplateItem {
  prompt_key: string
  name: string
  category: string
  description: string
  content: string
  variables: Record<string, unknown>
  source: string
  version: number
  updated_at: number
}

export interface PromptTemplateDetail extends PromptTemplateItem {
  source_path: string | null
  content_hash: string
  enabled: boolean
  created_at: number
}

export interface PromptTemplateListResponse {
  items: PromptTemplateItem[]
}

type Envelope<T> = { code: string; message: string; data: T }

export async function listPromptTemplates(params?: {
  category?: string
}): Promise<PromptTemplateListResponse> {
  const res = await get<Envelope<PromptTemplateListResponse>>('/admin/prompt-templates', { params })
  return res.data
}

export async function getPromptTemplate(promptKey: string): Promise<PromptTemplateDetail> {
  const res = await get<Envelope<PromptTemplateDetail>>(`/admin/prompt-templates/${promptKey}`)
  return res.data
}

export type UpdatePromptTemplatePayload = {
  content?: string
  description?: string
  enabled?: boolean
}

export async function updatePromptTemplate(
  promptKey: string,
  payload: UpdatePromptTemplatePayload
): Promise<PromptTemplateDetail> {
  const res = await patch<Envelope<PromptTemplateDetail>>(`/admin/prompt-templates/${promptKey}`, { body: payload })
  return res.data
}

export async function resetPromptTemplate(promptKey: string): Promise<PromptTemplateDetail> {
  const res = await post<Envelope<PromptTemplateDetail>>(`/admin/prompt-templates/${promptKey}/reset`)
  return res.data
}
