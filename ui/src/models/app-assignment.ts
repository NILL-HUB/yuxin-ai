import { type BaseResponse } from '@/models/base'

export type MyApp = {
  id: string
  name: string
  icon: string
  description: string
  created_at: number | null
  source: 'forked'
  status?: string
  can_edit?: boolean
}
export type MyAppListResponse = BaseResponse<{ list: MyApp[] }>
export type MyAppChatRequest = {
  query: string
  image_urls?: string[]
  conversation_id?: string
}
