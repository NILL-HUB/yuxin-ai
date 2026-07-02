import { get } from '@/utils/request'
import type {
  AdminDatasetPageData,
  AdminDatasetPageResponse,
  GetAdminDatasetsRequest,
} from '@/models/admin-dataset'

/**
 * 获取后台知识库分页列表，并解包接口返回的 data 字段。
 */
export const listAdminDatasets = async (
  params: GetAdminDatasetsRequest,
): Promise<AdminDatasetPageData> => {
  const response = await get<AdminDatasetPageResponse>('/admin/datasets', { params })
  return response.data
}
