import { ref } from 'vue'
import type { WorkflowNodeExecution, WorkflowRun } from '@/models/workflow-run'
import {
  getWorkflowNodeExecutions,
  getWorkflowRun,
  getWorkflowRuns,
} from '@/services/workflow-run'

// 加载工作流执行历史列表（分页）
export const useGetWorkflowRuns = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const defaultPaginator = {
    current_page: 1,
    page_size: 20,
    total_page: 0,
    total_record: 0,
  }
  const paginator = ref({ ...defaultPaginator })
  const runs = ref<WorkflowRun[]>([])

  // 2.定义加载数据函数
  const loadRuns = async (
    workflow_id: string,
    options: { status?: string; trigger_source?: string } = {},
    init: boolean = false,
  ) => {
    // 2.1 判断是否是初始化，并检查分页器
    if (init) {
      paginator.value = { ...defaultPaginator }
    } else if (paginator.value.current_page > paginator.value.total_page) {
      return
    }

    try {
      // 2.2 调用接口获取响应数据
      loading.value = true
      const resp = await getWorkflowRuns(workflow_id, {
        page: paginator.value.current_page,
        page_size: paginator.value.page_size,
        status: options.status,
        trigger_source: options.trigger_source,
      })
      const data = resp.data

      // 2.3 更新分页器
      paginator.value = data.paginator

      // 2.4 判断是否存在更多数据
      if (paginator.value.current_page <= paginator.value.total_page) {
        paginator.value.current_page += 1
      }

      // 2.5 判断是追加或者是覆盖数据
      if (init) {
        runs.value = data.list
      } else {
        runs.value.push(...data.list)
      }
    } finally {
      loading.value = false
    }
  }

  return { loading, runs, paginator, loadRuns }
}

// 加载单次工作流执行详情
export const useGetWorkflowRun = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const run = ref<WorkflowRun | null>(null)

  // 2.定义加载函数
  const loadRun = async (workflow_id: string, run_id: string) => {
    try {
      loading.value = true
      const resp = await getWorkflowRun(workflow_id, run_id)
      run.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, run, loadRun }
}

// 加载节点执行明细
export const useGetWorkflowNodeExecutions = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const nodeExecutions = ref<WorkflowNodeExecution[]>([])

  // 2.定义加载函数
  const loadNodeExecutions = async (workflow_id: string, run_id: string) => {
    try {
      loading.value = true
      const resp = await getWorkflowNodeExecutions(workflow_id, run_id)
      nodeExecutions.value = resp.data.list || []
    } finally {
      loading.value = false
    }
  }

  return { loading, nodeExecutions, loadNodeExecutions }
}
