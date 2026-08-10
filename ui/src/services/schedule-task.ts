import { del, get, post, put } from '@/utils/request'
import type { BaseResponse } from '@/models/base'

export type IntervalConfig = {
  unit: 'month' | 'week' | 'day' | 'hour' | 'minute'
  every: number
  day_of_month?: number
  day_of_week?: number
  hours?: number
  minutes?: number
}

export type ScheduleTaskItem = {
  id: string
  name: string
  prompt: string
  trigger_type: 'cron' | 'interval'
  cron_expression: string
  cron_humanized: string
  interval_config: IntervalConfig | Record<string, never>
  enabled: boolean
  status: string
  description: string
  run_count: number
  last_run_at: number | null
  last_run_status: string | null
  last_result: string | null
  next_run_at: number | null
  created_at: number
  updated_at: number
}

export type ScheduleTaskRunItem = {
  id: string
  schedule_task_id: string
  status: string
  trigger_source: string
  started_at: number
  finished_at: number | null
  duration_seconds: number
  result_summary: string | null
  result_data: Record<string, unknown>
  error_message: string | null
}

export type ScheduleParseResult = {
  cron_expression: string
  cron_humanized: string
  task_name: string
  prompt: string
  missing_fields: string[]
}

const scheduleTaskBasePath = (admin: boolean) => (admin ? '/admin/schedule-tasks' : '/schedule-tasks')

export const listScheduleTasks = (page = 1, pageSize = 20, admin = false) =>
  get<BaseResponse<{ items: ScheduleTaskItem[]; total: number }>>(scheduleTaskBasePath(admin), {
    params: { page, page_size: pageSize },
  })

export const createScheduleTask = (
  body: {
    name: string
    prompt: string
    cron_expression?: string
    cron_humanized?: string
    description?: string
    trigger_type?: 'cron' | 'interval'
    interval_config?: IntervalConfig | Record<string, never>
  },
  admin = false,
) => post<BaseResponse<ScheduleTaskItem>>(scheduleTaskBasePath(admin), { body })

export const updateScheduleTask = (
  id: string,
  body: Partial<{ name: string; prompt: string; cron_expression: string; cron_humanized: string; description: string; enabled: boolean; trigger_type: 'cron' | 'interval'; interval_config: IntervalConfig | Record<string, never> }>,
  admin = false,
) => put<BaseResponse<ScheduleTaskItem>>(`${scheduleTaskBasePath(admin)}/${id}`, { body })

export const deleteScheduleTask = (id: string, admin = false) => del<BaseResponse<{ id: string }>>(`${scheduleTaskBasePath(admin)}/${id}`)

export const enableScheduleTask = (id: string, enabled: boolean, admin = false) =>
  post<BaseResponse<ScheduleTaskItem>>(`${scheduleTaskBasePath(admin)}/${id}/enable`, { body: { enabled } })

export const runScheduleTaskNow = (id: string, admin = false) =>
  post<BaseResponse<ScheduleTaskRunItem>>(`${scheduleTaskBasePath(admin)}/${id}/run-now`, { body: {} })

export const listScheduleTaskRuns = (id: string, page = 1, pageSize = 20, admin = false) =>
  get<BaseResponse<{ items: ScheduleTaskRunItem[]; total: number }>>(`${scheduleTaskBasePath(admin)}/${id}/runs`, {
    params: { page, page_size: pageSize },
  })

export const parseScheduleIntent = (input: string, history?: Array<{ user: string; assistant: string }>, admin = false) =>
  post<BaseResponse<ScheduleParseResult>>(`${scheduleTaskBasePath(admin)}/parse`, { body: { input, history: history || [] } })

export const rejectScheduleSuggestion = (fingerprint: string, admin = false) =>
  post<BaseResponse<{ fingerprint: string }>>(`${scheduleTaskBasePath(admin)}/reject-suggestion`, { body: { fingerprint } })

export const humanizeScheduleCron = (cronExpression: string, admin = false) =>
  post<BaseResponse<{ cron_humanized: string }>>(`${scheduleTaskBasePath(admin)}/humanize`, {
    body: { cron_expression: cronExpression },
  })
