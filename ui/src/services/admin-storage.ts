import { get, post } from '@/utils/request'
import type {
  GetStorageMigrationFilesRequest,
  RunStorageMigrationRequest,
  StorageConfigItemResponse,
  StorageConfigListResponse,
  StorageMigrationListResponse,
  StorageMigrationResultResponse,
  StorageOverviewResponse,
} from '@/models/admin-storage'

/**
 * 获取内容存储概览（激活后端 + 各后端配置 + 文件统计）。
 */
export const getStorageOverview = async (): Promise<StorageOverviewResponse> => {
  return get<StorageOverviewResponse>('/admin/storage/overview')
}

/**
 * 获取存储后端配置列表。
 */
export const listStorageConfigs = async (): Promise<StorageConfigListResponse> => {
  return get<StorageConfigListResponse>('/admin/storage/configs')
}

/**
 * 更新指定后端的配置项（仅保存白名单键，密钥不落库）。
 */
export const updateStorageConfig = async (
  backend: string,
  configs: Record<string, unknown>,
): Promise<StorageConfigItemResponse> => {
  return post<StorageConfigItemResponse>(`/admin/storage/configs/${backend}`, {
    body: JSON.stringify({ configs }),
  })
}

/**
 * 激活指定存储后端（仅影响新上传文件）。
 */
export const activateStorageBackend = async (backend: string): Promise<StorageConfigItemResponse> => {
  return post<StorageConfigItemResponse>('/admin/storage/activate', {
    body: JSON.stringify({ backend }),
  })
}

/**
 * 分页列出可迁移文件（按源后端 + 筛选条件）。
 */
export const listStorageMigrationFiles = async (
  req: GetStorageMigrationFilesRequest,
): Promise<StorageMigrationListResponse> => {
  return get<StorageMigrationListResponse>('/admin/storage/migration/files', { params: req })
}

/**
 * 执行文件迁移（勾选或全部）。
 */
export const runStorageMigration = async (
  req: RunStorageMigrationRequest,
): Promise<StorageMigrationResultResponse> => {
  return post<StorageMigrationResultResponse>('/admin/storage/migration/run', {
    body: JSON.stringify(req),
  })
}
