<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
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
import UserRecycleBinDeleteModal from '@/components/recycle-bin/UserRecycleBinDeleteModal.vue'

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

const deleteTarget = ref<ScheduleTaskItem | null>(null)
const deleteLoading = ref(false)
const handleDelete = (task: ScheduleTaskItem) => {
  deleteTarget.value = task
}
const confirmDelete = async (retentionDays: number) => {
  if (!deleteTarget.value) return
  deleteLoading.value = true
  try {
    const resp = await deleteScheduleTask(deleteTarget.value.id, isAdminContext.value, retentionDays)
    Message.success(resp.message || t('space.schedules.deleteSuccess'))
    deleteTarget.value = null
    await loadTasks()
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('space.schedules.loadFailed')))
  } finally {
    deleteLoading.value = false
  }
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
const expandedRows = ref<Record<string, boolean>>({})

const toggleExpand = async (task: ScheduleTaskItem) => {
  const willOpen = !expandedRows.value[task.id]
  expandedRows.value = { ...expandedRows.value, [task.id]: willOpen }
  if (!willOpen) return
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

// 名称列图标（执行器类型 → 图标）
const typeIcon = (task: ScheduleTaskItem) => {
  if (task.task_type === 'app_execution') return 'icon-apps'
  return 'icon-robot'
}

// 短日期（今天/昨天/MM-DD HH:mm）
const formatRunTime = (ts: number | null | undefined) => {
  if (!ts) return '-'
  const ms = ts < 10000000000 ? ts * 1000 : ts
  return formatTimestampLong(ms)
}

onMounted(() => {
  loadTasks()
})
</script>

<template>
  <div class="schedule-page relative h-full w-full overflow-y-auto">
    <div class="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
      <!-- 页头 -->
      <header class="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p class="schedule-kicker text-xs font-medium uppercase tracking-wider text-brand">Schedules</p>
          <h1 class="schedule-title mt-1.5 text-3xl font-semibold sm:text-4xl">{{ t('space.schedules.title') }}</h1>
          <p class="mt-2 max-w-xl text-sm leading-relaxed text-muted">让钰心AI 在固定时间自动整理资讯、生成报表，并把结果准时送到你手中。</p>
        </div>
        <button
          type="button"
          class="schedule-create-btn inline-flex shrink-0 items-center justify-center gap-2 rounded-[var(--aicss-radius)] px-5 py-3 text-sm font-medium text-white shadow-[var(--aicss-shadow-card)] transition hover:-translate-y-0.5 hover:brightness-110 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-brand-soft"
          @click="openCreateWizard"
        >
          <icon-plus class="h-4 w-4" />
          {{ t('space.schedules.create') }}
        </button>
      </header>

      <!-- 任务表 -->
      <section class="mt-6">
        <div class="overflow-hidden rounded-[var(--aicss-radius)] border border-border-c bg-card shadow-[var(--aicss-shadow-card)]">
          <!-- 表头标题区 -->
          <div class="flex flex-col gap-2 border-b border-border-c px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 class="schedule-subtitle text-lg font-semibold">全部任务</h2>
              <p class="mt-0.5 text-xs text-muted">
                共 {{ total }} 个定时任务 · 支持 cron 与间隔两种触发方式
              </p>
            </div>
            <p class="flex items-center gap-1.5 text-xs text-muted">
              <icon-history class="h-3.5 w-3.5" />
              点击任务行查看运行记录
            </p>
          </div>

          <!-- 加载骨架 -->
          <div v-if="loading" class="divide-y divide-border-c">
            <div v-for="i in 5" :key="`skeleton-${i}`" class="flex animate-pulse items-center gap-4 px-5 py-4">
              <div class="h-9 w-9 rounded-[var(--aicss-radius)] bg-surface-2"></div>
              <div class="flex-1 space-y-2">
                <div class="h-4 w-1/4 rounded bg-surface-2"></div>
                <div class="h-3 w-1/3 rounded bg-surface-2"></div>
              </div>
              <div class="h-6 w-20 rounded-[var(--aicss-radius)] bg-surface-2"></div>
            </div>
          </div>

          <!-- 空态 -->
          <div
            v-else-if="tasks.length === 0"
            class="flex flex-col items-center rounded-[var(--aicss-radius)] border-2 border-dashed border-brand-soft bg-surface-2/40 px-6 py-14 text-center"
          >
            <div class="flex h-12 w-12 items-center justify-center rounded-full bg-brand-soft text-brand-text">
              <icon-schedule class="h-5 w-5" />
            </div>
            <p class="schedule-subtitle mt-4 text-lg font-bold">{{ t('space.schedules.empty') }}</p>
          </div>

          <!-- 表格 -->
          <div v-else class="overflow-x-auto">
            <table class="w-full min-w-[1080px] text-sm">
              <thead>
                <tr class="border-b border-border-c bg-surface-2">
                  <th class="schedule-th px-5 py-4 text-left text-xs font-medium uppercase tracking-wider">名称</th>
                  <th class="schedule-th px-5 py-4 text-left text-xs font-medium uppercase tracking-wider">频率</th>
                  <th class="schedule-th px-5 py-4 text-left text-xs font-medium uppercase tracking-wider">执行器</th>
                  <th class="schedule-th px-5 py-4 text-left text-xs font-medium uppercase tracking-wider">启用</th>
                  <th class="schedule-th px-5 py-4 text-left text-xs font-medium uppercase tracking-wider">上次执行</th>
                  <th class="schedule-th px-5 py-4 text-right text-xs font-medium uppercase tracking-wider">运行次数</th>
                  <th class="schedule-th px-5 py-4 text-right text-xs font-medium uppercase tracking-wider">操作</th>
                </tr>
              </thead>
              <tbody>
                <template v-for="task in tasks" :key="task.id">
                  <!-- 任务行 -->
                  <tr
                    class="schedule-row border-b border-border-c transition hover:bg-surface-2"
                    :class="{ 'schedule-row-open': expandedRows[task.id] }"
                    @click="toggleExpand(task)"
                  >
                    <td class="px-5 py-4">
                      <div class="flex items-center gap-3">
                        <span class="schedule-type-icon grid h-9 w-9 shrink-0 place-items-center rounded-[var(--aicss-radius)]">
                          <component :is="typeIcon(task)" class="h-4 w-4" />
                        </span>
                        <div class="min-w-0">
                          <p class="truncate font-medium text-text">{{ task.name }}</p>
                          <p class="mt-0.5 truncate text-xs text-muted">{{ task.description }}</p>
                        </div>
                      </div>
                    </td>
                    <td class="px-5 py-4">
                      <span class="schedule-pill inline-flex rounded-[var(--aicss-radius)] px-3 py-1 text-xs font-medium">
                        {{ task.cron_humanized || (task.trigger_type === 'interval' ? t('space.schedules.triggerInterval') : task.cron_expression) }}
                      </span>
                    </td>
                    <td class="px-5 py-4">
                      <div class="flex flex-wrap items-center gap-2">
                        <span
                          class="schedule-executor inline-flex rounded-[var(--aicss-radius)] px-3 py-1 text-xs font-medium"
                          :class="task.task_type === 'app_execution' ? 'schedule-executor-app' : 'schedule-executor-assistant'"
                        >
                          {{ task.task_type === 'app_execution' ? t('space.schedules.executorApp') : t('space.schedules.executorAssistant') }}
                        </span>
                        <span class="schedule-cron font-mono text-xs text-muted">{{ task.cron_expression }}</span>
                      </div>
                    </td>
                    <td class="px-5 py-4">
                      <button
                        type="button"
                        class="sd-switch"
                        :class="{ 'sd-switch-on': task.enabled }"
                        role="switch"
                        :aria-checked="task.enabled"
                        :aria-label="task.enabled ? t('space.schedules.enabledText') : t('space.schedules.disabledText')"
                        @click.stop="handleToggleEnabled(task, !task.enabled)"
                      >
                        <span class="sd-switch-dot"></span>
                      </button>
                    </td>
                    <td class="px-5 py-4">
                      <div class="flex flex-wrap items-center gap-1.5">
                        <span
                          class="schedule-status inline-flex rounded-[var(--aicss-radius)] px-2.5 py-0.5 text-xs font-medium"
                          :class="`schedule-status-${task.last_run_status || 'never'}`"
                        >
                          {{ getLastRunStatusText(task) }}
                        </span>
                        <span class="font-mono text-xs text-muted">{{ formatRunTime(task.last_run_at) }}</span>
                      </div>
                    </td>
                    <td class="schedule-count px-5 py-4 text-right font-mono text-sm text-text-2">{{ task.run_count }}</td>
                    <td class="px-5 py-4">
                      <div class="flex items-center justify-end gap-1" @click.stop>
                        <button
                          type="button"
                          class="schedule-action grid h-8 w-8 place-items-center rounded-[var(--aicss-radius)] text-muted transition hover:bg-brand hover:text-white"
                          :title="t('space.schedules.viewRuns')"
                          :aria-label="`${t('space.schedules.viewRuns')} ${task.name}`"
                          @click="openRuns(task)"
                        >
                          <icon-history class="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          class="schedule-action grid h-8 w-8 place-items-center rounded-[var(--aicss-radius)] text-muted transition hover:bg-brand hover:text-white"
                          :title="t('space.schedules.edit')"
                          :aria-label="`${t('space.schedules.edit')} ${task.name}`"
                          @click="openEditWizard(task)"
                        >
                          <icon-edit class="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          class="schedule-action grid h-8 w-8 place-items-center rounded-[var(--aicss-radius)] text-muted transition hover:bg-brand hover:text-white"
                          :title="t('space.schedules.runNow')"
                          :aria-label="`${t('space.schedules.runNow')} ${task.name}`"
                          @click="handleRunNow(task)"
                        >
                          <icon-play-arrow class="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          class="schedule-action grid h-8 w-8 place-items-center rounded-[var(--aicss-radius)] text-muted transition hover:bg-destructive hover:text-white"
                          :title="t('space.schedules.delete')"
                          :aria-label="`${t('space.schedules.delete')} ${task.name}`"
                          @click="handleDelete(task)"
                        >
                          <icon-delete class="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>

                  <!-- 展开行：运行记录 -->
                  <tr v-if="expandedRows[task.id]" class="bg-surface-2/60">
                    <td colspan="7" class="px-5 py-4">
                      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                        <div class="flex items-center gap-2 text-xs font-medium text-brand-text">
                          <icon-list class="h-4 w-4" />
                          最近运行记录
                        </div>
                        <div v-if="runsMap[task.id]" class="flex flex-wrap items-center gap-2 text-xs">
                          <span class="inline-flex rounded-[var(--aicss-radius)] bg-card px-2.5 py-1 text-muted">
                            共 {{ runsMap[task.id].length }} 次
                          </span>
                        </div>
                      </div>

                      <div v-if="runsLoading && !runsMap[task.id]" class="mt-3 flex animate-pulse items-center gap-3">
                        <div class="h-4 w-2/3 rounded bg-surface-2"></div>
                      </div>
                      <ul v-else-if="runsMap[task.id] && runsMap[task.id].length > 0" class="mt-3 space-y-2">
                        <li
                          v-for="run in runsMap[task.id]"
                          :key="run.id"
                          class="flex flex-wrap items-center gap-2 text-xs"
                        >
                          <span class="font-mono text-muted">{{ formatRunTime(run.started_at) }}</span>
                          <span class="schedule-status inline-flex rounded-[var(--aicss-radius)] px-2 py-0.5 font-medium" :class="`schedule-status-${run.status || 'never'}`">
                            {{ getRunStatusText(run.status) }}
                          </span>
                          <span class="text-muted">{{ run.result_summary || run.error_message || '-' }}</span>
                        </li>
                      </ul>
                      <p v-else class="mt-3 text-xs text-muted">{{ t('space.schedules.runsEmpty') }}</p>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>

          <!-- 分页 -->
          <div
            v-if="total > pageSize"
            class="flex items-center justify-between flex-wrap gap-3 border-t border-border-c px-5 py-4"
          >
            <span class="text-xs text-muted">{{ t('space.schedules.total', { count: total }) }}</span>
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
      </section>

      <!-- 页脚 -->
      <footer class="mt-8 border-t border-border-c pt-6">
        <p class="text-center text-xs text-muted">© 2026 钰心AI · 让每一次自动执行都准时发生</p>
      </footer>
    </div>

    <CreateScheduleWizard
      :visible="wizardVisible"
      :task="editingTask"
      @success="handleWizardSuccess"
      @cancel="handleWizardCancel"
    />
    <!-- 删除定时任务确认（进入回收站 + 选择销毁时间） -->
    <user-recycle-bin-delete-modal
      :visible="deleteTarget !== null"
      :title="t('space.schedules.deleteConfirmTitle')"
      :resource-name="deleteTarget?.name"
      :loading="deleteLoading"
      :hint="t('userRecycleBin.deleteHint')"
      @update:visible="(v) => !v && (deleteTarget = null)"
      @confirm="confirmDelete"
    >
      <p class="text-sm text-muted">
        {{ t('space.schedules.deleteConfirmContent') }}
      </p>
    </user-recycle-bin-delete-modal>
  </div>
</template>

<style scoped>
.schedule-page {
  height: 100%;
  background: var(--aicss-bg);
}

/* 滚动条微调 */
.schedule-page::-webkit-scrollbar {
  width: 6px;
}
.schedule-page::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: var(--aicss-border-strong);
}
.schedule-page::-webkit-scrollbar-track {
  background: transparent;
}

/* 衬线标题族 */
.schedule-kicker {
  font-family: var(--aicss-font-sans, inherit);
  letter-spacing: 0.14em;
}
.schedule-title,
.schedule-subtitle {
  font-family: Georgia, 'Songti SC', 'SimSun', serif;
  letter-spacing: -0.02em;
  color: var(--aicss-text);
}

/* 新建任务按钮 */
.schedule-create-btn {
  background: var(--aicss-accent);
}
.schedule-create-btn:hover {
  background: var(--aicss-accent-text);
}

/* 表头 */
.schedule-th {
  color: var(--aicss-muted);
  font-weight: 600;
}

/* 行 hover + 展开态 */
.schedule-row {
  cursor: pointer;
}
.schedule-row-open {
  background: var(--aicss-surface-2);
}

/* 名称图标块 */
.schedule-type-icon {
  background: var(--aicss-surface-2);
  color: var(--aicss-brand-text, var(--aicss-accent-text));
}

/* 频率 / 状态胶囊 */
.schedule-pill {
  background: var(--aicss-surface-2);
  color: var(--aicss-text-2);
}

/* 执行器徽标 */
.schedule-executor {
  background: var(--aicss-surface-2);
  color: var(--aicss-text-2);
}
.schedule-executor-app {
  background: var(--aicss-accent-soft);
  color: var(--aicss-brand-text, var(--aicss-accent-text));
}
.schedule-executor-assistant {
  background: var(--aicss-bg-subtle);
  color: var(--aicss-muted);
}

.schedule-cron {
  letter-spacing: 0;
}

/* 状态 */
.schedule-status-success {
  background: var(--aicss-accent-soft);
  color: var(--aicss-brand-text, var(--aicss-accent-text));
}
.schedule-status-failed {
  background: rgba(220, 38, 38, 0.1);
  color: #dc2626;
}
.schedule-status-running {
  background: var(--aicss-accent-soft);
  color: var(--aicss-brand-text, var(--aicss-accent-text));
}
.schedule-status-never {
  background: var(--aicss-bg-subtle);
  color: var(--aicss-muted);
}

.schedule-count {
  color: var(--aicss-text-2);
}

/* 操作图标 */
.schedule-action {
  background: transparent;
  border: none;
  cursor: pointer;
}
.schedule-action:hover {
  background: var(--aicss-accent);
  color: #fff;
}

/* 自绘启用开关（粉色主题，替代 Arco 蓝色 switch） */
.sd-switch {
  position: relative;
  display: inline-flex;
  align-items: center;
  width: 38px;
  height: 22px;
  padding: 0;
  border: 1px solid var(--aicss-border-strong);
  border-radius: 999px;
  background: var(--aicss-bg-subtle);
  cursor: pointer;
  transition:
    background 0.2s ease,
    border-color 0.2s ease;
}
.sd-switch-dot {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  transition: transform 0.2s ease;
}
.sd-switch-on {
  background: linear-gradient(135deg, var(--aicss-accent), #ff5c8d);
  border-color: transparent;
}
.sd-switch-on .sd-switch-dot {
  transform: translateX(16px);
}
</style>
