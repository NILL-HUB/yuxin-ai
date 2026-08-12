import type { BaseResponse } from '@/models/base'

// 存储后端配置项
export type StorageConfigItem = {
  id: string
  backend: string
  configs: Record<string, unknown>
  is_active: boolean
  created_at: number | null
  updated_at: number | null
}

// 存储概览
export type StorageOverviewData = {
  active_backend: string
  backend_items: StorageConfigItem[]
  stats: Record<string, { count: number; size: number }>
}

// 可迁移文件条目
export type StorageMigrationFile = {
  id: string
  name: string
  key: string
  size: number
  extension: string
  mime_type: string
  hash: string
  storage_backend: string | null
  resolved_backend: string | null
  url: string | null
  kkfileview_url: string | null
  source_type: string
  source_label: string
  duplicate_count: number
  is_latest: boolean
  is_valid: boolean
  in_use: boolean
  created_at: number | null
}

// 迁移文件列表查询请求
export type GetStorageMigrationFilesRequest = {
  source_backend: string
  page: number
  page_size: number
  extension?: string
  search_word?: string
}

// 迁移文件列表响应的数据部分
export type StorageMigrationListData = {
  items: StorageMigrationFile[]
  total: number
  page: number
  page_size: number
  total_pages: number
  total_record: number
  extensions: string[]
  summary: {
    total: number
    distinct_content: number
    duplicate_records: number
  }
}

// 迁移执行请求
export type RunStorageMigrationRequest = {
  source_backend: string
  target_backend: string
  file_ids?: string[]
  extension?: string
  search_word?: string
  delete_source?: boolean
}

// 迁移执行结果
export type StorageMigrationResult = {
  total: number
  succeeded: number
  failed: number
  failures: Array<{ id: string; name: string; reason: string }>
}

export type DeleteStorageFilesRequest = {
  file_ids: string[]
  retention_days?: number
  force?: boolean
}

export type StorageDeleteResult = {
  total: number
  succeeded: number
  failed: number
  in_use: Array<{ id: string; name: string; reason: string }>
  failures: Array<{ id: string; name: string; reason: string }>
}

export type StorageOverviewResponse = BaseResponse<StorageOverviewData>
export type StorageConfigListResponse = BaseResponse<{ items: StorageConfigItem[] }>
export type StorageConfigItemResponse = BaseResponse<StorageConfigItem>
export type StorageMigrationListResponse = BaseResponse<StorageMigrationListData>
export type StorageMigrationResultResponse = BaseResponse<StorageMigrationResult>
export type StorageDeleteResultResponse = BaseResponse<StorageDeleteResult>
