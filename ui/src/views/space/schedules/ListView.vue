<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Message, Modal } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import { formatTimestampLong } from '@/utils/time-formatter'
import {
  deleteScheduleTask,
  enableScheduleTask,
  listScheduleTaskRuns,
  listScheduleTasks,
  runScheduleTaskNow,
  type ScheduleTaskItem,
  type ScheduleTaskRunItem,
} from '@/services/schedule-task'
import CreateScheduleWizard from './CreateScheduleWizard.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

// admin 上下文检测：admin 路由带 realm: 'admin' 且路径以 /admin/ 开头
const isAdminContext = computed(() => route.path.startsWith('/admin') || route.meta.realm === 'admin')

const loading = ref(false)
const tasks = ref<ScheduleTaskItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const loadTasks = async () => {
  loading.value = true
  try {
    const res = await listScheduleTasks(page.value, pageSize.value, isAdminContext.value)
    tasks.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('space.schedules.loadFailed')))
  } finally {
    loading.value = false
  }
}

const onPageChange = (next: number) => {
  page.value = next
  loadTasks()
}

const onPageSizeChange = (size: number) => {
  pageSize.value = size
  page.value = 1
  loadTasks()
}

// 创建/编辑向导：三步创建向导（编辑模式复用同一组件）
const wizardVisible = ref(false)
const editingTask = ref<ScheduleTaskItem | null>(null)
const openCreateWizard = () => {
  editingTask.value = null
  wizardVisible.value = true
}

const handleWizardCancel = () => {
  wizardVisible.value = false
}

const handleWizardSuccess = () => {
  wizardVisible.value = false
  loadTasks()
}

// 编辑任务：回填已有数据到向导
const openEditWizard = (task: ScheduleTaskItem) => {
  editingTask.value = task
  wizardVisible.value = true
}

// 执行结果：跳转到独立列表页查看每次执行的详细报告
const openRuns = (task: ScheduleTaskItem) => {
  router.push({
    name: isAdminContext.value ? 'admin-schedules-runs' : 'user-schedules-runs',
    params: { task_id: task.id },
    query: {
      name: task.name,
      cron: task.cron_expression,
      cron_humanized: task.cron_humanized,
    },
  })
}

const handleToggleEnabled = async (task: ScheduleTaskItem, enabled: boolean) => {
  try {
    const res = await enableScheduleTask(task.id, enabled, isAdminContext.value)
    task.enabled = res.data.enabled
    Message.success(enabled ? t('space.schedules.enableSuccess') : t('space.schedules.disableSuccess'))
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('space.schedules.loadFailed')))
  }
}

const handleDelete = (task: ScheduleTaskItem) => {
  Modal.warning({
    title: t('space.schedules.deleteConfirmTitle'),
    content: t('space.schedules.deleteConfirmContent'),
    onOk: async () => {
      try {
        const resp = await deleteScheduleTask(task.id, isAdminContext.value)
        Message.success(resp.message || t('space.schedules.deleteSuccess'))
        await loadTasks()
      } catch (error: unknown) {
        Message.error(getErrorMessage(error, t('space.schedules.loadFailed')))
      }
    },
  })
}

const handleRunNow = async (task: ScheduleTaskItem) => {
  try {
    await runScheduleTaskNow(task.id, isAdminContext.value)
    Message.success(t('space.schedules.runNowSuccess'))
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('space.schedules.loadFailed')))
  }
}

// 运行记录（表格展开行，惰性加载）
const runsLoading = ref(false)
const runsMap = ref<Record<string, ScheduleTaskRunItem[]>>({})

const loadRuns = async (task: ScheduleTaskItem) => {
  if (runsMap.value[task.id]) return
  runsLoading.value = true
  try {
    const res = await listScheduleTaskRuns(task.id, 1, 10, isAdminContext.value)
    runsMap.value[task.id] = res.data.items || []
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('space.schedules.loadFailed')))
  } finally {
    runsLoading.value = false
  }
}

const getLastRunStatusColor = (status: string | null) => {
  if (status === 'success') return 'green'
  if (status === 'failed') return 'red'
  if (status === 'running') return 'arcoblue'
  return 'gray'
}

const getLastRunStatusText = (task: ScheduleTaskItem) => {
  if (!task.last_run_status) return t('space.schedules.lastRunStatus.never')
  if (task.last_run_status === 'success') return t('space.schedules.lastRunStatus.success')
  if (task.last_run_status === 'failed') return t('space.schedules.lastRunStatus.failed')
  if (task.last_run_status === 'running') return t('space.schedules.lastRunStatus.running')
  return task.last_run_status
}

const getRunStatusText = (status: string) => {
  if (status === 'success') return t('space.schedules.lastRunStatus.success')
  if (status === 'failed') return t('space.schedules.lastRunStatus.failed')
  if (status === 'running') return t('space.schedules.lastRunStatus.running')
  return status
}

onMounted(() => {
  loadTasks()
})
</script>

<template>
  <div class="flex h-full w-full flex-col overflow-hidden">
    <!-- 顶部工具栏（固定不滚动） -->
    <div class="flex items-center justify-between flex-shrink-0 px-6 py-4 bg-white border-b border-gray-100">
      <div class="text-lg font-semibold text-gray-900">{{ t('space.schedules.title') }}</div>
      <a-button type="primary" class="rounded-lg" @click="openCreateWizard">
        <template #icon>
          <icon-plus />
        </template>
        {{ t('space.schedules.create') }}
      </a-button>
    </div>
    <!-- 列表区域 -->
    <div class="flex-1 min-h-0 overflow-auto p-6">
      <a-spin :loading="loading" class="block w-full">
        <!-- 空状态 -->
        <div
          v-if="!loading && tasks.length === 0"
          class="bg-white rounded-lg border border-gray-200 h-[400px] flex items-center justify-center"
        >
          <a-empty :description="t('space.schedules.empty')" />
        </div>
        <!-- 表格 -->
        <div v-else class="bg-white rounded-lg border border-gray-200">
          <a-table
            row-key="id"
            :data="tasks"
            :loading="loading"
            :bordered="false"
            :hoverable="true"
            :pagination="false"
            :expandable="{ width: 40 }"
            @expand="(rowKey, record) => loadRuns(record as ScheduleTaskItem)"
          >
            <template #columns>
              <a-table-column
                :title="t('space.schedules.columns.name')"
                data-index="name"
                :width="220"
                header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
                cell-class="!py-4"
              >
                <template #cell="{ record }">
                  <div class="text-sm text-gray-900 font-medium truncate" :title="record.name">
                    {{ record.name }}
                  </div>
                </template>
              </a-table-column>
              <a-table-column
                :title="t('space.schedules.columns.cronHumanized')"
                data-index="cron_humanized"
                :width="200"
                header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
                cell-class="!py-4"
              >
                <template #cell="{ record }">
                  <div class="text-sm text-gray-700 truncate" :title="record.cron_humanized">
                    {{ record.cron_humanized || record.cron_expression }}
                  </div>
                </template>
              </a-table-column>
              <a-table-column
                :title="t('space.schedules.columns.cron')"
                data-index="cron_expression"
                :width="170"
                header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
                cell-class="!py-4"
              >
                <template #cell="{ record }">
                  <a-tag v-if="record.trigger_type === 'interval'" color="green" size="small">{{ t('space.schedules.triggerInterval') }}</a-tag>
                  <a-tag v-else color="arcoblue" size="small">{{ record.cron_expression }}</a-tag>
                </template>
              </a-table-column>
              <a-table-column
                :title="t('space.schedules.columns.enabled')"
                data-index="enabled"
                :width="100"
                header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
                cell-class="!py-4"
              >
                <template #cell="{ record }">
                  <a-tooltip :content="record.enabled ? t('space.schedules.enabledText') : t('space.schedules.disabledText')">
                    <a-switch
                      size="small"
                      :model-value="record.enabled"
                      @change="
                        (value: string | number | boolean) => {
                          handleToggleEnabled(record, Boolean(value))
                        }
                      "
                    />
                  </a-tooltip>
                </template>
              </a-table-column>
              <a-table-column
                :title="t('space.schedules.columns.lastRun')"
                data-index="last_run_status"
                :width="130"
                header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
                cell-class="!py-4"
              >
                <template #cell="{ record }">
                  <a-tag :color="getLastRunStatusColor(record.last_run_status)" size="small">
                    {{ getLastRunStatusText(record) }}
                  </a-tag>
                </template>
              </a-table-column>
              <a-table-column
                :title="t('space.schedules.columns.runCount')"
                data-index="run_count"
                :width="100"
                header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
                cell-class="!py-4"
              >
                <template #cell="{ record }">
                  <span class="text-sm text-gray-700">{{ record.run_count }}</span>
                </template>
              </a-table-column>
              <a-table-column
                :title="t('space.schedules.columns.actions')"
                :width="290"
                header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold !border-b !border-gray-200"
                cell-class="!py-4"
              >
                <template #cell="{ record }">
                  <a-space :size="8">
                    <a-button size="small" class="!rounded !text-blue-600" @click="openRuns(record)">
                      {{ t('space.schedules.viewRuns') }}
                    </a-button>
                    <a-button size="small" class="!rounded !text-gray-600" @click="openEditWizard(record)">
                      {{ t('space.schedules.edit') }}
                    </a-button>
                    <a-button size="small" class="!rounded !text-gray-600" @click="handleRunNow(record)">
                      {{ t('space.schedules.runNow') }}
                    </a-button>
                    <a-button size="small" class="!rounded !text-red-500" @click="handleDelete(record)">
                      {{ t('space.schedules.delete') }}
                    </a-button>
                  </a-space>
                </template>
              </a-table-column>
            </template>
            <!-- 展开行：运行记录 -->
            <template #expand-row="{ record }">
              <div class="px-6 py-3">
                <a-spin :loading="runsLoading && !runsMap[record.id]">
                  <a-table
                    v-if="runsMap[record.id] && runsMap[record.id].length > 0"
                    :data="runsMap[record.id]"
                    :pagination="false"
                    :bordered="false"
                    size="small"
                  >
                    <template #columns>
                      <a-table-column
                        :title="t('space.schedules.startedAt')"
                        data-index="started_at"
                        header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold"
                      >
                        <template #cell="{ record: run }">
                          <span class="text-xs text-gray-600">{{ formatTimestampLong(run.started_at) }}</span>
                        </template>
                      </a-table-column>
                      <a-table-column
                        :title="t('space.schedules.finishedAt')"
                        data-index="finished_at"
                        header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold"
                      >
                        <template #cell="{ record: run }">
                          <span class="text-xs text-gray-600">
                            {{ run.finished_at ? formatTimestampLong(run.finished_at) : '-' }}
                          </span>
                        </template>
                      </a-table-column>
                      <a-table-column
                        :title="t('space.schedules.columns.lastRun')"
                        data-index="status"
                        :width="100"
                        header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold"
                      >
                        <template #cell="{ record: run }">
                          <a-tag :color="getLastRunStatusColor(run.status)" size="small">
                            {{ getRunStatusText(run.status) }}
                          </a-tag>
                        </template>
                      </a-table-column>
                      <a-table-column
                        :title="t('space.schedules.resultSummary')"
                        data-index="result_summary"
                        header-cell-class="!bg-gray-50 !text-gray-900 !font-semibold"
                      >
                        <template #cell="{ record: run }">
                          <div class="text-xs text-gray-600 whitespace-pre-wrap break-all">
                            {{ run.result_summary || run.error_message || '-' }}
                          </div>
                        </template>
                      </a-table-column>
                    </template>
                  </a-table>
                  <a-empty v-else-if="!runsLoading" :description="t('space.schedules.runsEmpty')" class="py-4" />
                </a-spin>
              </div>
            </template>
          </a-table>
          <!-- 分页 -->
          <div
            v-if="total > pageSize"
            class="flex items-center justify-between px-6 py-4 border-t border-gray-100"
          >
            <span class="text-xs text-gray-400">{{ t('space.schedules.total', { count: total }) }}</span>
            <a-pagination
              :total="total"
              :current="page"
              :page-size="pageSize"
              show-total
              show-page-size
              @change="onPageChange"
              @page-size-change="onPageSizeChange"
            />
          </div>
        </div>
      </a-spin>
    </div>
    <CreateScheduleWizard
      :visible="wizardVisible"
      :task="editingTask"
      @success="handleWizardSuccess"
      @cancel="handleWizardCancel"
    />
  </div>
</template>

<style scoped></style>
