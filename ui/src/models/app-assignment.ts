import { type BaseResponse } from '@/models/base'

export type AssignedApp = {
  id: string
  name: string
  icon: string
  description: string
  status?: string
  is_public?: boolean
}

export type AppAssignment = {
  id: string
  app_id: string
  account_id: string
  assigned_by: string | null
  status: 'active' | 'revoked'
  assigned_at: number | null
  revoked_at: number | null
  app: AssignedApp | null
}

export type AppAssignmentListResponse = BaseResponse<{ list: AppAssignment[] }>
export type AssignAppsResponse = BaseResponse<{ assigned: number; reactivated: number; skipped: number; list: AppAssignment[] }>
export type MyApp = AssignedApp & {
  assignment_id: string
  assigned_at: number | null
}
export type MyAppListResponse = BaseResponse<{ list: MyApp[] }>
export type MyAppChatRequest = {
  query: string
  image_urls?: string[]
  conversation_id?: string
  enable_deep_thinking?: boolean
}
