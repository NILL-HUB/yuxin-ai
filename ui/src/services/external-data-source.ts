import { type BaseResponse } from '@/models/base'
import { del, get, post } from '@/utils/request'

export type ExternalDataSource = {
  id: string
  knowledge_base_id: string
  source_type: string
  source_name: string
  authorization_status: string
  sync_status: string
  sync_cursor: string
  last_synced_at: string
  last_error: string
  config: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type ExternalDataSourceSyncResult = {
  sync_status: string
  document_count: number
  segment_count: number
  last_error: string
}

export type CreateExternalDataSourceRequest = {
  knowledge_base_id: string
  source_type: string
  source_name: string
  config: Record<string, unknown>
}

export const getExternalDataSources = (status?: string) => {
  return get<BaseResponse<Array<ExternalDataSource>>>(`/external-data-sources`, {
    params: status ? { status } : undefined,
  })
}

export const getExternalDataSource = (id: string) => {
  return get<BaseResponse<ExternalDataSource>>(`/external-data-sources/${id}`)
}

export const createExternalDataSource = (data: CreateExternalDataSourceRequest) => {
  return post<BaseResponse<ExternalDataSource>>(`/external-data-sources`, { body: data })
}

export const authorizeExternalDataSource = (
  id: string,
  auth_config: Record<string, unknown>,
) => {
  return post<BaseResponse<ExternalDataSource>>(`/external-data-sources/${id}/authorize`, {
    body: auth_config,
  })
}

export const syncExternalDataSource = (id: string) => {
  return post<BaseResponse<ExternalDataSourceSyncResult>>(
    `/external-data-sources/${id}/sync`,
  )
}

export const deleteExternalDataSource = (id: string) => {
  return del<BaseResponse<null>>(`/external-data-sources/${id}`)
}
