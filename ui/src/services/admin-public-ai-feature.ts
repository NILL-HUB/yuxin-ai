// ui/src/services/admin-public-ai-feature.ts
import { get, patch, post } from '@/utils/request'

export interface PublicAIFeature {
  feature_key: string
  feature_name: string
  feature_category: string
  feature_description: string | null
  model_config_id: string | null
  model_type: string
  billable: boolean
  enabled: boolean
  fallback_tier: string
  extra_config: Record<string, unknown>
  last_called_at: string | null
  updated_at: string
  created_at: string
}

export interface AvailableModel {
  id: string
  label: string
  provider: string
  model_name: string
  model_type: string
  tier: string
}

export interface PublicAIFeatureListResponse {
  items: PublicAIFeature[]
  total: number
}

export interface AvailableModelsResponse {
  items: AvailableModel[]
}

type Envelope<T> = { code: string; message: string; data: T }

export async function listPublicAIFeatures(params?: {
  category?: string
  enabled?: string
}): Promise<PublicAIFeatureListResponse> {
  const res = await get<Envelope<PublicAIFeatureListResponse>>('/admin/public-ai-features', { params })
  return res.data
}

export async function getPublicAIFeature(featureKey: string): Promise<PublicAIFeature> {
  const res = await get<Envelope<PublicAIFeature>>(`/admin/public-ai-features/${featureKey}`)
  return res.data
}

export type UpdatePublicAIFeaturePayload = {
  model_config_id?: string
  enabled?: boolean
  fallback_tier?: string
  billable?: boolean
}

export async function updatePublicAIFeature(
  featureKey: string,
  payload: UpdatePublicAIFeaturePayload
): Promise<PublicAIFeature> {
  const res = await patch<Envelope<PublicAIFeature>>(`/admin/public-ai-features/${featureKey}`, { body: payload })
  return res.data
}

export async function listAvailableModels(modelType?: string): Promise<AvailableModelsResponse> {
  const params: Record<string, string> = {}
  if (modelType) {
    params.model_type = modelType
  }
  const res = await get<Envelope<AvailableModelsResponse>>('/admin/public-ai-features/models', { params })
  return res.data
}

export interface BatchBindResultItem {
  feature_key: string
  feature_name: string
  feature_category: string
  model_type: string
  model_config_id: string | null
  fallback_tier: string
  enabled: boolean
}

export interface BatchBindModelInfo {
  id: string
  provider: string
  model_name: string
  model_type: string
  tier: string
}

export interface BatchBindResult {
  updated: number
  skipped: number
  items: BatchBindResultItem[]
  model: BatchBindModelInfo
}

export type BatchBindPayload = {
  model_type?: string
  model_config_id: string
  fallback_tier?: string
}

/** 预览一键配置：返回将受影响的功能清单（不写库）。 */
export async function previewBatchBind(payload: BatchBindPayload): Promise<BatchBindResult> {
  const res = await post<Envelope<BatchBindResult>>('/admin/public-ai-features/batch-bind/preview', { body: payload })
  return res.data
}

/** 一键配置：把某模型类型下所有启用的功能批量绑定到目标模型。 */
export async function batchBind(payload: BatchBindPayload): Promise<BatchBindResult> {
  const res = await post<Envelope<BatchBindResult>>('/admin/public-ai-features/batch-bind', { body: payload })
  return res.data
}
