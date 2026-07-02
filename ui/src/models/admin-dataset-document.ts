import type { BasePaginatorResponse } from '@/models/base'

export type AdminDatasetDocumentRecord = {
  id: string
  name: string
  status: string
  error?: string | null
  enabled: boolean
  character_count: number
  hit_count: number
  segment_count: number
  created_at: number | null
  updated_at: number | null
}

export type GetAdminDatasetDocumentsRequest = {
  search_word: string
  current_page: number
  page_size: number
}

export type AdminDatasetDocumentPageResponse = BasePaginatorResponse<AdminDatasetDocumentRecord>
export type AdminDatasetDocumentPageData = AdminDatasetDocumentPageResponse['data']

export type AdminDatasetSegmentRecord = {
  id: string
  content: string
  enabled: boolean
  position: number
  character_count: number
  hit_count: number
  status: string
  created_at: number | null
  updated_at: number | null
}

export type GetAdminDatasetSegmentsRequest = {
  search_word: string
  current_page: number
  page_size: number
}

export type AdminDatasetSegmentPageResponse = BasePaginatorResponse<AdminDatasetSegmentRecord>
export type AdminDatasetSegmentPageData = AdminDatasetSegmentPageResponse['data']
