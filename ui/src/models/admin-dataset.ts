import type { BasePaginatorResponse } from '@/models/base'

export type AdminDatasetRecord = {
  id: string
  name: string
  icon: string
  description: string
  document_count: number
  related_app_count: number
  character_count: number
  creator_name: string
  creator_avatar: string
  upload_at: number | null
  updated_at: number | null
  created_at: number | null
}

export type GetAdminDatasetsRequest = {
  search_word: string
  current_page: number
  page_size: number
}

export type AdminDatasetPageResponse = BasePaginatorResponse<AdminDatasetRecord>
export type AdminDatasetPageData = AdminDatasetPageResponse['data']
