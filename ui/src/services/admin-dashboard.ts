import { listAdminWorkflows } from '@/services/admin-workflows'

export type AdminDashboardSummary = {
  workflow_total: number
  workflow_published: number
  workflow_draft: number
}

/**
 * 通过后台工作流列表接口聚合首页的轻量概览数据。
 */
export const getAdminDashboardSummary = async (): Promise<AdminDashboardSummary> => {
  const [all, published, draft] = await Promise.all([
    listAdminWorkflows({ search: '', status: 'all', current_page: 1, page_size: 1 }),
    listAdminWorkflows({ search: '', status: 'published', current_page: 1, page_size: 1 }),
    listAdminWorkflows({ search: '', status: 'draft', current_page: 1, page_size: 1 }),
  ])

  return {
    workflow_total: all.paginator.total_record,
    workflow_published: published.paginator.total_record,
    workflow_draft: draft.paginator.total_record,
  }
}
