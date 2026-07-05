import { get } from '@/utils/request'
import type { BasePaginatorResponse, BaseResponse } from '@/models/base'
import type { WorkflowRun, WorkflowNodeExecution } from '@/models/workflow-run'

// 分页获取指定工作流的执行历史记录
export const getWorkflowRuns = (
  workflow_id: string,
  params: { page?: number; page_size?: number; status?: string; trigger_source?: string },
) => get<BasePaginatorResponse<WorkflowRun>>(`/workflows/${workflow_id}/runs`, { params })

// 获取单次工作流执行详情
export const getWorkflowRun = (workflow_id: string, run_id: string) =>
  get<BaseResponse<WorkflowRun>>(`/workflows/${workflow_id}/runs/${run_id}`)

// 获取指定执行下的节点执行明细列表
export const getWorkflowNodeExecutions = (workflow_id: string, run_id: string) =>
  get<BaseResponse<{ list: WorkflowNodeExecution[] }>>(
    `/workflows/${workflow_id}/runs/${run_id}/node-executions`,
  )
