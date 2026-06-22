<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { listAuditLogs, type AuditLog } from '@/services/admin-audit-logs'
import { getErrorMessage } from '@/utils/error'

const loading = ref(false)
const logs = ref<AuditLog[]>([])
const total = ref(0)
const detailTarget = ref<AuditLog | null>(null)

const actionOptions = [
  { label: '全部操作', value: '' },
  { label: '创建', value: 'create' },
  { label: '更新', value: 'update' },
  { label: '禁用', value: 'disable' },
  { label: '删除', value: 'delete' },
]

const filters = ref({
  action: '',
  resource_type: '',
  start: '',
  end: '',
  current_page: 1,
  page_size: 20,
})

const formatTime = (value: number | null | undefined) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const toUnix = (value: string) => {
  if (!value) return undefined
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return undefined
  return Math.floor(time / 1000)
}

const loadLogs = async () => {
  loading.value = true
  try {
    const res = await listAuditLogs({
      action: filters.value.action || undefined,
      resource_type: filters.value.resource_type || undefined,
      start_time: toUnix(filters.value.start),
      end_time: toUnix(filters.value.end),
      current_page: filters.value.current_page,
      page_size: filters.value.page_size,
    })
    logs.value = res.data.list || []
    total.value = res.data.paginator.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, '加载审计日志失败'))
  } finally {
    loading.value = false
  }
}

const handleSearch = async () => {
  filters.value.current_page = 1
  await loadLogs()
}

const onPageChange = async (page: number) => {
  filters.value.current_page = page
  await loadLogs()
}

const onPageSizeChange = async (size: number) => {
  filters.value.page_size = size
  filters.value.current_page = 1
  await loadLogs()
}

const openDetail = (log: AuditLog) => {
  detailTarget.value = log
}

const stringify = (value: Record<string, unknown> | undefined) => {
  if (!value) return '-'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return '-'
  }
}

onMounted(loadLogs)
</script>

<template>
  <section class="space-y-6 p-6">
    <header>
      <h1 class="text-2xl font-semibold text-gray-900">审计日志</h1>
      <p class="mt-1 text-sm text-gray-500">查看后台管理操作的完整审计记录与变更详情。</p>
    </header>

    <div class="rounded-lg border bg-white p-4">
      <div class="grid gap-3 md:grid-cols-4">
        <a-select v-model="filters.action" :options="actionOptions" placeholder="操作类型" />
        <a-input v-model="filters.resource_type" placeholder="资源类型" allow-clear />
        <input
          v-model="filters.start"
          type="datetime-local"
          class="h-8 w-full rounded border border-gray-300 px-2 text-sm"
          placeholder="开始时间"
        />
        <input
          v-model="filters.end"
          type="datetime-local"
          class="h-8 w-full rounded border border-gray-300 px-2 text-sm"
          placeholder="结束时间"
        />
      </div>
      <a-button class="mt-3" type="primary" :loading="loading" @click="handleSearch">查询</a-button>
    </div>

    <a-spin :loading="loading" class="block">
      <div class="overflow-hidden rounded-lg border bg-white">
        <table class="w-full text-left text-sm">
          <thead class="bg-gray-50 text-gray-500">
            <tr>
              <th class="p-3">时间</th>
              <th class="p-3">管理员</th>
              <th class="p-3">操作</th>
              <th class="p-3">资源类型</th>
              <th class="p-3">资源ID</th>
              <th class="p-3">IP</th>
              <th class="p-3">详情</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!logs.length">
              <td class="p-6 text-center text-gray-400" colspan="7">暂无审计日志</td>
            </tr>
            <tr v-for="log in logs" :key="log.id" class="border-t">
              <td class="p-3 whitespace-nowrap">{{ formatTime(log.created_at) }}</td>
              <td class="p-3 font-mono text-xs">{{ log.admin_user_id || '-' }}</td>
              <td class="p-3">
                <a-tag size="small">{{ log.action }}</a-tag>
              </td>
              <td class="p-3">{{ log.resource_type || '-' }}</td>
              <td class="p-3 font-mono text-xs">{{ log.resource_id || '-' }}</td>
              <td class="p-3 text-xs">{{ log.ip || '-' }}</td>
              <td class="p-3">
                <a-button size="mini" @click="openDetail(log)">查看</a-button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </a-spin>

    <div class="flex justify-end">
      <a-pagination
        :total="total"
        :current="filters.current_page"
        :page-size="filters.page_size"
        show-total
        show-page-size
        @change="onPageChange"
        @page-size-change="onPageSizeChange"
      />
    </div>

    <a-modal :visible="!!detailTarget" :width="640" :footer="false" @cancel="detailTarget = null">
      <template #title>审计详情</template>
      <div v-if="detailTarget" class="space-y-4">
        <div class="grid grid-cols-2 gap-3 text-sm">
          <div><span class="text-gray-500">操作：</span>{{ detailTarget.action }}</div>
          <div><span class="text-gray-500">资源类型：</span>{{ detailTarget.resource_type || '-' }}</div>
          <div><span class="text-gray-500">资源ID：</span>{{ detailTarget.resource_id || '-' }}</div>
          <div><span class="text-gray-500">IP：</span>{{ detailTarget.ip || '-' }}</div>
          <div class="col-span-2"><span class="text-gray-500">User-Agent：</span>{{ detailTarget.user_agent || '-' }}</div>
        </div>
        <div>
          <p class="mb-1 text-sm font-medium text-gray-700">变更前</p>
          <pre class="max-h-48 overflow-auto rounded bg-gray-50 p-3 text-xs">{{ stringify(detailTarget.before_data) }}</pre>
        </div>
        <div>
          <p class="mb-1 text-sm font-medium text-gray-700">变更后</p>
          <pre class="max-h-48 overflow-auto rounded bg-gray-50 p-3 text-xs">{{ stringify(detailTarget.after_data) }}</pre>
        </div>
      </div>
    </a-modal>
  </section>
</template>
