import { type BaseResponse } from '@/models/base'
import { get, post } from '@/utils/request'

export type Suggestion = {
  id: string
  target_type: string
  target_id: string
  suggestion_type: string
  severity: string
  reason: string
  evidence: Record<string, unknown>
  status: string
  dismiss_reason?: string
  applied_by?: string
  applied_at?: string
  policy_change_draft_id?: string
}

export type PolicyChangePreview = {
  suggestion_id: string
  policy_type: string
  target_id: string
  before_config: Record<string, unknown>
  after_config: Record<string, unknown>
  diff: Record<string, unknown>
  impact: Record<string, unknown>
  status: string
}

export type PolicyChangeDraft = {
  id: string
  suggestion_id: string
  policy_type: string
  target_id: string
  before_config: Record<string, unknown>
  after_config: Record<string, unknown>
  diff: Record<string, unknown>
  impact: Record<string, unknown>
  status: string
  applied_by?: string
  applied_at?: string
  rolled_back_at?: string
  rollback_reason?: string
}

export const getSuggestions = (status?: string) => {
  return get<BaseResponse<Array<Suggestion>>>(`/admin/routing-quality/suggestions`, {
    params: status ? { status } : undefined,
  })
}

export const acceptSuggestion = (id: string) => {
  return post<BaseResponse<Suggestion>>(`/admin/routing-quality/suggestions/${id}/accept`)
}

export const dismissSuggestion = (id: string, reason: string) => {
  return post<BaseResponse<Suggestion>>(`/admin/routing-quality/suggestions/${id}/dismiss`, {
    body: { reason },
  })
}

export const previewPolicyChange = (id: string) => {
  return get<BaseResponse<PolicyChangePreview>>(
    `/admin/routing-quality/suggestions/${id}/preview`,
  )
}

export const applyPolicyChange = (id: string, previewData: PolicyChangePreview) => {
  return post<BaseResponse<PolicyChangeDraft>>(`/admin/routing-quality/suggestions/${id}/apply`, {
    body: previewData,
  })
}

export const listPolicyChanges = (status?: string) => {
  return get<BaseResponse<Array<PolicyChangeDraft>>>(`/admin/routing-quality/policy-changes`, {
    params: status ? { status } : undefined,
  })
}

export const rollbackPolicyChange = (draftId: string, reason: string) => {
  return post<BaseResponse<PolicyChangeDraft>>(
    `/admin/routing-quality/policy-changes/${draftId}/rollback`,
    {
      body: { reason },
    },
  )
}
