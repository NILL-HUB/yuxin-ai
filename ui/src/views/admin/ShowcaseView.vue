<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  adminListShowcaseCases,
  approveShowcaseCase,
  rejectShowcaseCase,
  offlineShowcaseCase,
  type ShowcaseCase,
} from '@/services/showcase'
import { getErrorMessage } from '@/utils/error'
import { formatTimestampLong } from '@/utils/time-formatter'

const loading = ref(false)
const actionLoading = ref(false)
const cases = ref<ShowcaseCase[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const statusFilter = ref('')

const STATUS_TABS = [
  { label: '全部', value: '' },
  { label: '待审核', value: 'pending' },
  { label: '已通过', value: 'approved' },
  { label: '已拒绝', value: 'rejected' },
  { label: '已下架', value: 'offline' },
]

const STATUS_COLOR: Record<string, string> = {
  pending: 'orange',
  approved: 'green',
  rejected: 'red',
  offline: 'gray',
}

const STATUS_LABEL: Record<string, string> = {
  pending: '待审核',
  approved: '已通过',
  rejected: '已拒绝',
  offline: '已下架',
}

const statusLabel = (status: string) => STATUS_LABEL[status] || status
const statusColor = (status: string) => STATUS_COLOR[status] || 'gray'

const renderStars = (rating: number) => {
  const score = Math.max(0, Math.min(5, Math.round(Number(rating) || 0)))
  return '★'.repeat(score) + '☆'.repeat(5 - score)
}

const maskContributor = (name?: string) => {
  const value = String(name || '').trim()
  if (!value) return '匿名用户'
  if (value.length <= 1) return `${value}*`
  return `${value.slice(0, 1)}***`
}

const loadCases = async () => {
  loading.value = true
  try {
    const res = await adminListShowcaseCases({
      page: page.value,
      per_page: pageSize.value,
      status: statusFilter.value || undefined,
    })
    cases.value = res.data.data || []
    total.value = res.data.total || 0
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, '加载案例列表失败'))
  } finally {
    loading.value = false
  }
}

const handleTabChange = (value: string | number | boolean) => {
  statusFilter.value = String(value)
  page.value = 1
  loadCases()
}

const onPageChange = (next: number) => {
  page.value = next
  loadCases()
}

const detailVisible = ref(false)
const activeCase = ref<ShowcaseCase | null>(null)
const openDetail = (item: ShowcaseCase) => {
  activeCase.value = item
  detailVisible.value = true
}

const rejectVisible = ref(false)
const rejectTarget = ref<ShowcaseCase | null>(null)
const rejectReason = ref('')

const openReject = (item: ShowcaseCase) => {
  rejectTarget.value = item
  rejectReason.value = ''
  rejectVisible.value = true
}

const handleApprove = async (item: ShowcaseCase) => {
  actionLoading.value = true
  try {
    await approveShowcaseCase(item.id)
    Message.success('已通过审核')
    await loadCases()
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, '操作失败'))
  } finally {
    actionLoading.value = false
  }
}

const handleRejectConfirm = async () => {
  if (!rejectTarget.value) return
  actionLoading.value = true
  try {
    await rejectShowcaseCase(rejectTarget.value.id, rejectReason.value.trim() || undefined)
    Message.success('已拒绝该案例')
    rejectVisible.value = false
    await loadCases()
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, '操作失败'))
  } finally {
    actionLoading.value = false
  }
}

const handleOffline = async (item: ShowcaseCase) => {
  actionLoading.value = true
  try {
    await offlineShowcaseCase(item.id)
    Message.success('已下架该案例')
    await loadCases()
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, '操作失败'))
  } finally {
    actionLoading.value = false
  }
}

const columns = computed(() => [
  { title: '标题', slotName: 'title', minWidth: 200 },
  { title: '贡献者', slotName: 'contributor', width: 140 },
  { title: '状态', slotName: 'status', width: 110 },
  { title: '评分', slotName: 'rating', width: 120 },
  { title: '创建时间', slotName: 'created_at', width: 180 },
  { title: '操作', slotName: 'actions', width: 200, fixed: 'right' as const },
])

onMounted(loadCases)
</script>

<template>
  <section class="flex flex-col gap-4">
    <header class="flex items-center justify-between">
      <div>
        <h2 class="text-xl font-bold text-gray-900">案例展示管理</h2>
        <p class="mt-1 text-sm text-gray-500">审核用户提交的公开展示案例，维护案例质量。</p>
      </div>
    </header>

    <div class="flex items-center justify-between gap-3 flex-wrap">
      <a-radio-group
        :model-value="statusFilter"
        type="button"
        @change="handleTabChange"
      >
        <a-radio v-for="tab in STATUS_TABS" :key="tab.value" :value="tab.value">
          {{ tab.label }}
        </a-radio>
      </a-radio-group>
      <a-button :loading="loading" @click="loadCases">刷新</a-button>
    </div>

    <a-spin :loading="loading" class="block">
      <div class="overflow-hidden rounded-lg border bg-white">
        <a-table
          :data="cases"
          :columns="columns"
          :row-key="(record: ShowcaseCase) => record.id"
          :pagination="false"
          :bordered="{ wrapper: true, cell: true }"
          :scroll="{ x: 960 }"
        >
          <template #empty>暂无案例数据</template>
          <template #title="{ record }">
            <a-button type="text" size="small" @click="openDetail(record)">
              <span class="font-medium text-gray-900">{{ record.title || '未命名案例' }}</span>
            </a-button>
          </template>
          <template #contributor="{ record }">
            <span class="text-sm text-gray-600">{{ maskContributor(record.contributor) }}</span>
          </template>
          <template #status="{ record }">
            <a-tag :color="statusColor(record.status)" size="small">{{ statusLabel(record.status) }}</a-tag>
          </template>
          <template #rating="{ record }">
            <span class="text-amber-500 text-sm">{{ renderStars(record.rating) }}</span>
          </template>
          <template #created_at="{ record }">
            <span class="text-sm text-gray-500">{{ formatTimestampLong(record.created_at) }}</span>
          </template>
          <template #actions="{ record }">
            <a-space>
              <a-button
                v-if="record.status === 'pending'"
                size="mini"
                type="primary"
                :loading="actionLoading"
                @click="handleApprove(record)"
              >
                通过
              </a-button>
              <a-button
                v-if="record.status === 'pending'"
                size="mini"
                status="danger"
                :loading="actionLoading"
                @click="openReject(record)"
              >
                拒绝
              </a-button>
              <a-button
                v-if="record.status === 'approved'"
                size="mini"
                status="warning"
                :loading="actionLoading"
                @click="handleOffline(record)"
              >
                下架
              </a-button>
              <a-button size="mini" @click="openDetail(record)">详情</a-button>
            </a-space>
          </template>
        </a-table>
      </div>
    </a-spin>

    <div v-if="total > pageSize" class="flex justify-center">
      <a-pagination
        :total="total"
        :current="page"
        :page-size="pageSize"
        show-total
        @change="onPageChange"
      />
    </div>

    <a-modal
      v-model:visible="detailVisible"
      :title="activeCase?.title || '案例详情'"
      :width="680"
      :footer="false"
      unmount-on-close
    >
      <template v-if="activeCase">
        <div class="flex items-center gap-2 mb-4 flex-wrap">
          <a-tag :color="statusColor(activeCase.status)" size="small">{{ statusLabel(activeCase.status) }}</a-tag>
          <span class="text-amber-500">{{ renderStars(activeCase.rating) }}</span>
          <a-tag v-for="tag in (activeCase.tags || [])" :key="tag" size="small">{{ tag }}</a-tag>
          <span class="text-xs text-gray-400 ml-auto">
            {{ maskContributor(activeCase.contributor) }} · {{ formatTimestampLong(activeCase.created_at) }}
          </span>
        </div>
        <p v-if="activeCase.summary" class="text-sm text-gray-600 mb-4">{{ activeCase.summary }}</p>
        <div class="rounded-md bg-gray-50 px-4 py-3 mb-4">
          <div class="text-xs text-gray-400 mb-1">用户提问</div>
          <div class="text-sm text-gray-800 whitespace-pre-wrap break-words">{{ activeCase.query }}</div>
        </div>
        <div class="rounded-md bg-blue-50/40 px-4 py-3">
          <div class="text-xs text-gray-400 mb-1">AI 回答</div>
          <div class="text-sm text-gray-800 whitespace-pre-wrap break-words">{{ activeCase.answer }}</div>
        </div>
      </template>
    </a-modal>

    <a-modal
      v-model:visible="rejectVisible"
      title="拒绝案例"
      :confirm-loading="actionLoading"
      @ok="handleRejectConfirm"
      @cancel="rejectVisible = false"
    >
      <a-form layout="vertical">
        <a-form-item label="拒绝原因（可选）">
          <a-textarea
            v-model="rejectReason"
            placeholder="请输入拒绝原因，将反馈给贡献者"
            :auto-size="{ minRows: 3, maxRows: 6 }"
            allow-clear
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
