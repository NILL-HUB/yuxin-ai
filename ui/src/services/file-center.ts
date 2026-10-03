import { del, get, patch, post } from '@/utils/request'
import type { BaseResponse } from '@/models/base'
import type {
  FileCenterAllFilesPage,
  FileCenterChildren,
  FileCenterEntry,
} from '@/models/file-center'

/**
 * 列出某目录下的直接子节点（parentId 为空表示账号根）。
 */
export const listFileCenterEntries = async (
  parentId: string | null = null,
): Promise<FileCenterChildren> => {
  const response = await get<BaseResponse<FileCenterChildren>>('/space/files', {
    params: parentId ? { parent_id: parentId } : {},
  })
  return response.data
}

/**
 * 「全部文件」平铺视图：账号下已入树的文件（分页，按创建时间倒序）。
 */
export const listAllFileCenterFiles = async (
  page = 1,
  pageSize = 20,
): Promise<FileCenterAllFilesPage> => {
  const response = await get<BaseResponse<FileCenterAllFilesPage>>('/space/files/all', {
    params: { page, page_size: pageSize },
  })
  return response.data
}

/**
 * 新建目录。
 */
export const createFileCenterFolder = async (
  parentId: string | null,
  name: string,
): Promise<FileCenterEntry> => {
  const response = await post<BaseResponse<FileCenterEntry>>('/space/files/folders', {
    body: JSON.stringify({ parent_id: parentId, name }),
  })
  return response.data
}

/**
 * 重命名 / 移动（传 name 为改名；传 parent_id 为移动）。
 */
export const updateFileCenterEntry = async (
  entryId: string,
  payload: { name?: string; parent_id?: string | null },
): Promise<FileCenterEntry> => {
  const response = await patch<BaseResponse<FileCenterEntry>>(`/space/files/${entryId}`, {
    body: JSON.stringify(payload),
  })
  return response.data
}

/**
 * 删除节点（文件入回收站可恢复；目录递归）。
 */
export const deleteFileCenterEntry = async (entryId: string): Promise<void> => {
  await del<BaseResponse<unknown>>(`/space/files/${entryId}`)
}

/**
 * 把已上传的 upload_file 挂入指定目录（配合既有上传接口使用）。
 */
export const importFileCenterUpload = async (
  uploadFileId: string,
  parentId: string | null,
  name: string,
): Promise<FileCenterEntry> => {
  const response = await post<BaseResponse<FileCenterEntry>>('/space/files/import', {
    body: JSON.stringify({ upload_file_id: uploadFileId, parent_id: parentId, name }),
  })
  return response.data
}
