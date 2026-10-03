/** 用户文件中心（虚拟目录树）类型定义。 */

export interface FileCenterEntry {
  id: string
  parent_id: string | null
  name: string
  is_folder: boolean
  upload_file_id: string | null
  source: string
  origin: string | null
  /** 文件的后端访问 URL（目录为 null） */
  url: string | null
}

export interface FileCenterChildren {
  items: FileCenterEntry[]
  parent_id: string | null
}

/** 「全部文件」平铺视图条目（已入树的文件节点） */
export interface FileCenterAllFile {
  entry_id: string
  upload_file_id: string | null
  name: string
  source: string
  origin: string | null
  organized: boolean
  /** 文件的后端访问 URL */
  url: string | null
}

export interface FileCenterAllFilesPage {
  items: FileCenterAllFile[]
  total: number
  page: number
  page_size: number
  total_pages: number
  total_record: number
}