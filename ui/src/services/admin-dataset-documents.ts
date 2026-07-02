import { get } from '@/utils/request'
import type {
  AdminDatasetDocumentPageData,
  AdminDatasetDocumentPageResponse,
  GetAdminDatasetDocumentsRequest,
} from '@/models/admin-dataset-document'

/**
 * 获取后台知识库文档分页列表，并解包接口返回的 data 字段。
 */
export const listAdminDatasetDocuments = async (
  datasetId: string,
  params: GetAdminDatasetDocumentsRequest,
): Promise<AdminDatasetDocumentPageData> => {
  const response = await get<AdminDatasetDocumentPageResponse>(
    `/admin/datasets/${datasetId}/documents`,
    { params },
  )
  return response.data
}
