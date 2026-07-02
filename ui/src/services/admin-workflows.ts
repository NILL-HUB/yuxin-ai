import { get, post } from '@/utils/request'
import type {
  AdminWorkflowData,
  AdminWorkflowOfflineResponse,
  AdminWorkflowPageData,
  AdminWorkflowPageResponse,
  AdminWorkflowResponse,
  GetAdminWorkflowsRequest,
  UpdateAdminWorkflowRequest,
} from '@/models/admin-workflow'

/**
 * 获取后台工作流分页列表，并解包接口返回的 data 字段。
 */
export const listAdminWorkflows = async (
  params: GetAdminWorkflowsRequest,
): Promise<AdminWorkflowPageData> => {
  const response = await get<AdminWorkflowPageResponse>('/admin/workflows', { params })
  return response.data
}

/**
 * 获取单个后台工作流详情，并解包接口返回的 data 字段。
 */
export const getAdminWorkflow = async (workflowId: string): Promise<AdminWorkflowData> => {
  const response = await get<AdminWorkflowResponse>(`/admin/workflows/${workflowId}`)
  return response.data
}

/**
 * 更新后台工作流状态或公开性，并解包接口返回的 data 字段。
 */
export const updateAdminWorkflow = async (
  workflowId: string,
  body: UpdateAdminWorkflowRequest,
): Promise<AdminWorkflowData> => {
  const response = await post<AdminWorkflowResponse>(`/admin/workflows/${workflowId}`, { body })
  return response.data
}

/**
 * 调用后台工作流下架接口，并返回空数据载荷。
 */
export const offlineAdminWorkflow = async (workflowId: string): Promise<Record<string, never>> => {
  const response = await post<AdminWorkflowOfflineResponse>(`/admin/workflows/${workflowId}/offline`)
  return response.data
}
