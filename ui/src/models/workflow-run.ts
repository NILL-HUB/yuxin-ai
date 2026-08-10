export type WorkflowRunStatus = 'running' | 'succeeded' | 'failed' | 'stopped'
export type WorkflowTriggerSource = 'debug' | 'app' | 'schedule' | 'api'

export type WorkflowRun = {
  id: string
  workflow_id: string
  app_id: string | null
  account_id: string
  trigger_source: WorkflowTriggerSource
  inputs: Record<string, unknown>
  outputs: Record<string, unknown>
  status: WorkflowRunStatus
  error: string
  total_steps: number
  elapsed_time: number
  total_tokens: number
  created_at: string | null
  updated_at: string | null
}

export type WorkflowNodeExecutionStatus = 'running' | 'succeeded' | 'failed' | 'skipped'

export type WorkflowNodeExecution = {
  id: string
  workflow_run_id: string
  node_id: string
  node_type: string
  title: string
  inputs: Record<string, unknown>
  outputs: Record<string, unknown>
  status: WorkflowNodeExecutionStatus
  error: string
  elapsed_time: number
  execution_metadata: Record<string, unknown>
  created_at: string | null
  updated_at: string | null
}
