// ui/src/services/admin-public-ai-feature.ts
import { get, patch } from '@/utils/request'

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
