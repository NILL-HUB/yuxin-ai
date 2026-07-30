import { del, get, patch, post } from '@/utils/request'
import type {
  AdminWorkflowData,
  AdminWorkflowOfflineResponse,
  AdminWorkflowPageData,
  AdminWorkflowPageResponse,
  AdminWorkflowResponse,
  GetAdminWorkflowsRequest,
  PublishAdminWorkflowRequest,
  RollbackWorkflowVersionRequest,
  UpdateAdminWorkflowRequest,
  WorkflowVersionListResponse,
  WorkflowVersionRecord,
} from '@/models/admin-workflow'
import type {
  CreateWorkflowRequest,
  GetDraftGraphResponse,
  UpdateDraftGraphRequest,
} from '@/models/workflow'
import type { BaseResponse } from '@/models/base'

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
  const response = await patch<AdminWorkflowResponse>(`/admin/workflows/${workflowId}`, { body })
  return response.data
}

/**
 * 调用后台工作流下架接口，并返回空数据载荷。
 */
export const offlineAdminWorkflow = async (workflowId: string): Promise<Record<string, never>> => {
  const response = await post<AdminWorkflowOfflineResponse>(`/admin/workflows/${workflowId}/offline`)
  return response.data
}

/**
 * 创建后台工作流。注意：admin 创建仅需要 name 与 description，tool_call_name 由后端自动生成。
 */
export const createAdminWorkflow = async (
  body: CreateWorkflowRequest,
): Promise<AdminWorkflowData> => {
  const response = await post<AdminWorkflowResponse>('/admin/workflows', { body })
  return response.data
}

/**
 * 删除后台工作流。
 */
export const deleteAdminWorkflow = async (workflowId: string): Promise<Record<string, never>> => {
  const response = await del<BaseResponse<Record<string, never>>>(`/admin/workflows/${workflowId}`)
  return response.data
}

/**
 * 获取后台工作流图草稿配置。
 */
export const getAdminWorkflowDraftGraph = async (
  workflowId: string,
): Promise<GetDraftGraphResponse['data']> => {
  const response = await get<GetDraftGraphResponse>(`/admin/workflows/${workflowId}/draft-graph`)
  return response.data
}

/**
 * 更新后台工作流图草稿配置。
 */
export const updateAdminWorkflowDraftGraph = async (
  workflowId: string,
  body: UpdateDraftGraphRequest,
): Promise<GetDraftGraphResponse['data']> => {
  const response = await post<GetDraftGraphResponse>(
    `/admin/workflows/${workflowId}/draft-graph`,
    { body },
  )
  return response.data
}

/**
 * 发布后台工作流。
 */
export const publishAdminWorkflow = async (
  workflowId: string,
  body?: PublishAdminWorkflowRequest,
): Promise<AdminWorkflowData> => {
  const response = await post<AdminWorkflowResponse>(
    `/admin/workflows/${workflowId}/publish`,
    { body },
  )
  return response.data
}

/**
 * 获取后台工作流版本历史列表。
 */
export const listAdminWorkflowVersions = async (
  workflowId: string,
): Promise<WorkflowVersionRecord[]> => {
  const response = await get<WorkflowVersionListResponse>(
    `/admin/workflows/${workflowId}/versions`,
  )
  return response.data.list
}

/**
 * 回滚后台工作流到指定历史版本。
 */
export const rollbackAdminWorkflowVersion = async (
  workflowId: string,
  versionId: string,
  body?: RollbackWorkflowVersionRequest,
): Promise<Record<string, never>> => {
  const response = await post<BaseResponse<Record<string, never>>>(
    `/admin/workflows/${workflowId}/versions/${versionId}/rollback`,
    { body },
  )
  return response.data
}

export type BatchOperationResult = {
  succeeded: string[]
  failed: { id: string; reason: string }[]
}

/**
 * 批量发布工作流。
 */
export const batchPublishAdminWorkflows = async (
  workflowIds: string[],
): Promise<BatchOperationResult> => {
  const response = await post<BaseResponse<BatchOperationResult>>(
    '/admin/workflows/batch/publish',
    { body: { workflow_ids: workflowIds } },
  )
  return response.data
}

/**
 * 批量下架工作流。
 */
export const batchOfflineAdminWorkflows = async (
  workflowIds: string[],
): Promise<BatchOperationResult> => {
  const response = await post<BaseResponse<BatchOperationResult>>(
    '/admin/workflows/batch/offline',
    { body: { workflow_ids: workflowIds } },
  )
  return response.data
}

/**
 * 导出指定后台工作流为可迁移 JSON 数据，并解包接口返回的 data 字段。
 */
export const exportAdminWorkflow = async (
  workflowId: string,
  includeVersions = false,
): Promise<Record<string, any>> => {
  const response = await get<BaseResponse<Record<string, any>>>(
    `/admin/workflows/${workflowId}/export`,
    { params: { include_versions: includeVersions } },
  )
  return response.data
}

/**
 * 导入后台工作流，返回新创建的工作流详情，并解包接口返回的 data 字段。
 */
export const importAdminWorkflow = async (
  jsonData: Record<string, any>,
  overwriteName = false,
): Promise<AdminWorkflowData> => {
  const response = await post<AdminWorkflowResponse>('/admin/workflows/import', {
    body: { json_data: jsonData, overwrite_name: overwriteName },
  })
  return response.data
}
