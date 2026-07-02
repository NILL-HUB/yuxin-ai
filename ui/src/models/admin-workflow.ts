import type { BasePaginatorResponse, BaseResponse } from '@/models/base'

export type AdminWorkflowRecord = {
  id: string
  name: string
  tool_call_name: string
  icon: string
  description: string
  status: string
  is_public: boolean
  created_at: number
  updated_at: number
}

export type GetAdminWorkflowsRequest = {
  search: string
  status: string
  current_page: number
  page_size: number
}

export type UpdateAdminWorkflowRequest = {
  status?: string
  is_public?: boolean
}

export type AdminWorkflowPageResponse = BasePaginatorResponse<AdminWorkflowRecord>
export type AdminWorkflowResponse = BaseResponse<AdminWorkflowRecord>
export type AdminWorkflowPageData = AdminWorkflowPageResponse['data']
export type AdminWorkflowData = AdminWorkflowResponse['data']
export type AdminWorkflowOfflineResponse = BaseResponse<Record<string, never>>
