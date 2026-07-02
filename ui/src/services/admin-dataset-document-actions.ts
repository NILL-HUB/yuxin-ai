import { post } from '@/utils/request'
import type { BaseResponse } from '@/models/base'

/**
 * 调用真实文档接口，更新后台文档名称。
 */
export const renameAdminDatasetDocument = (
  datasetId: string,
  documentId: string,
  name: string,
) => {
  return post<BaseResponse<any>>(`/datasets/${datasetId}/documents/${documentId}/name`, {
    body: { name },
  })
}

/**
 * 调用真实文档接口，切换后台文档启用状态。
 */
export const updateAdminDatasetDocumentEnabled = (
  datasetId: string,
  documentId: string,
  enabled: boolean,
) => {
  return post<BaseResponse<any>>(`/datasets/${datasetId}/documents/${documentId}/enabled`, {
    body: { enabled },
  })
}

/**
 * 调用真实文档接口，删除后台文档。
 */
export const deleteAdminDatasetDocument = (datasetId: string, documentId: string) => {
  return post<BaseResponse<any>>(`/datasets/${datasetId}/documents/${documentId}/delete`)
}
