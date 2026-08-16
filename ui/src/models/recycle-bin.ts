import type { BaseResponse } from '@/models/base'

// 回收站条目
export type RecycleBinItem = {
  id: number
  resource_type: string
  resource_id: string
  resource_key: string
  resource_name: string
  deleted_by: string | null
  deleted_by_name: string | null
  deleted_by_type: 'admin' | 'user' | string
  deleted_at: number | null
  retention_days: number
  expire_at: number | null
  status: string
  remark: string
  // 本机文件（os_file）删除时的设备信息（IP + 系统用户名）
  device_info?: { ip: string; name: string } | null
}

// 回收站列表查询请求
export type GetRecycleBinRequest = {
  page: number
  page_size: number
  resource_type?: string
  deleted_by_type?: string
  status?: string
  search_word?: string
}

// 回收站列表响应的数据部分
export type RecycleBinPageData = {
  items: RecycleBinItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
  total_record: number
}

// 回收站列表响应
export type RecycleBinPageResponse = BaseResponse<RecycleBinPageData>

// 回收站详情响应
export type RecycleBinDetailResponse = BaseResponse<RecycleBinItem>
