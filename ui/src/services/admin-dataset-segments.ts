import { get } from '@/utils/request'
import type {
  AdminDatasetSegmentPageData,
  AdminDatasetSegmentPageResponse,
  GetAdminDatasetSegmentsRequest,
} from '@/models/admin-dataset-document'

/**
 * 获取后台知识库文档片段分页列表，并解包接口返回的 data 字段。
 */
export const listAdminDatasetSegments = async (
  datasetId: string,
  documentId: string,
  params: GetAdminDatasetSegmentsRequest,
): Promise<AdminDatasetSegmentPageData> => {
  const response = await get<AdminDatasetSegmentPageResponse>(
    `/admin/datasets/${datasetId}/documents/${documentId}/segments`,
    { params },
  )
  return response.data
}
