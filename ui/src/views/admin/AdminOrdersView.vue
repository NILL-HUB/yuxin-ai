<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useAdminStore } from '@/stores/admin'
import { closeAdminOrder, getAdminOrderDetail, listAdminOrders } from '@/services/admin-commerce'
import { type AdminPurchaseOrder } from '@/models/commerce'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()
const adminStore = useAdminStore()
const canManageOrder = computed(() => adminStore.hasPermission('order:manage'))

const loading = ref(false)
const actionLoading = ref(false)
const orders = ref<AdminPurchaseOrder[]>([])
const total = ref(0)
const filters = ref({
  status: '' as string,
  order_source: '' as string,
  account_id: '',
  current_page: 1,
  page_size: 20,
})

const currentOrder = ref<AdminPurchaseOrder | null>(null)
const detailVisible = ref(false)

const statusOptions = computed(() => [
  { label: t('admin.orders.allStatus'), value: '' },
  { label: t('membership.status.order.pending'), value: 'pending' },
  { label: t('membership.status.order.paid'), value: 'paid' },
  { label: t('membership.status.order.closed'), value: 'closed' },
  { label: t('membership.status.order.failed'), value: 'failed' },
  { label: t('membership.status.order.refunded'), value: 'refunded' },
])

const sourceOptions = computed(() => [
  { label: t('admin.orders.allSource'), value: '' },
  { label: t('membership.status.orderSource.normal'), value: 'normal' },
  { label: t('membership.status.orderSource.auto_renew'), value: 'auto_renew' },
])

const loadOrders = async () => {
  loading.value = true
  try {
    const result = await listAdminOrders(filters.value)
    orders.value = result.list || []
    total.value = result.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.orders.loadFailed')))
  } finally {
    loading.value = false
  }
}

const handleSearch = async () => {
  filters.value.current_page = 1
  await loadOrders()
}

const onPageChange = async (page: number) => {
  filters.value.current_page = page
  await loadOrders()
}

const openDetail = async (order: AdminPurchaseOrder) => {
  currentOrder.value = order
  detailVisible.value = true
  try {
    const detail = await getAdminOrderDetail(order.id)
    currentOrder.value = detail
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.orders.loadDetailFailed')))
  }
}

const closeDetail = () => {
  detailVisible.value = false
  currentOrder.value = null
}

const handleClose = async (order: AdminPurchaseOrder) => {
  actionLoading.value = true
  try {
    await closeAdminOrder(order.id)
    Message.success(t('admin.orders.closed'))
    await loadOrders()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.orders.closeFailed')))
  } finally {
    actionLoading.value = false
  }
}

const formatTime = (value: number | null) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const formatStatus = (status: string) => {
  return t(`membership.status.order.${status}`) || status
}

const formatPlanType = (planType: string) => {
  return t(`membership.status.planType.${planType}`) || planType
}

const formatPayMethod = (payMethod: string) => {
  return t(`membership.status.payMethod.${payMethod}`) || payMethod
}

const formatOrderSource = (source: string) => {
  return t(`membership.status.orderSource.${source}`) || source
}

const formatUser = (record: { user_name?: string | null; user_email?: string | null; account_id: string }) => {
  const name = record.user_name || record.user_email || '-'
  return { name, email: record.user_email || '' }
}

const copyId = async (id: string) => {
  try {
    await navigator.clipboard.writeText(id)
    Message.success(t('admin.orders.idCopied'))
  } catch {
    Message.error(t('admin.orders.copyFailed'))
  }
}

onMounted(loadOrders)
</script>

<template>
  <section class="orders-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Orders</p>
        <h2>{{ t('admin.orders.title') }}</h2>
        <p>{{ t('admin.orders.description') }}</p>
      </div>
    </header>

    <section class="filter-panel">
      <a-input v-model="filters.account_id" :placeholder="t('admin.orders.accountIdPlaceholder')" allow-clear />
      <a-select v-model="filters.status" :options="statusOptions" :placeholder="t('admin.orders.statusPlaceholder')" />
      <a-select v-model="filters.order_source" :options="sourceOptions" :placeholder="t('admin.orders.sourcePlaceholder')" />
      <a-button type="primary" :loading="loading" @click="handleSearch">{{ t('admin.orders.search') }}</a-button>
    </section>

    <section class="panel">
      <a-table :loading="loading" :data="orders" :pagination="false" :bordered="{ wrapper: true, cell: true }" row-key="id">
        <template #columns>
          <a-table-column :title="t('admin.orders.orderNo')" data-index="order_no" />
          <a-table-column :title="t('admin.orders.user')" data-index="account_id">
            <template #cell="{ record }">
              <div class="cell-stack">
                <span>{{ formatUser(record).name }}</span>
                <span v-if="formatUser(record).email" class="cell-sub">{{ formatUser(record).email }}</span>
                <div class="cell-id-row">
                  <code class="cell-id">{{ record.account_id }}</code>
                  <a-button size="mini" type="text" @click="copyId(record.account_id)">{{ t('admin.orders.copyId') }}</a-button>
                </div>
              </div>
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.orders.planType')" data-index="plan_type">
            <template #cell="{ record }">
              {{ formatPlanType(record.plan_type) }}
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.orders.amount')" data-index="amount">
            <template #cell="{ record }">
              ¥{{ Number(record.amount || 0).toFixed(2) }}
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.orders.payMethod')" data-index="pay_method">
            <template #cell="{ record }">
              {{ formatPayMethod(record.pay_method) }}
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.orders.orderSource')" data-index="order_source">
            <template #cell="{ record }">
              {{ formatOrderSource(record.order_source) }}
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.orders.status')" data-index="status">
            <template #cell="{ record }">
              <a-tag>{{ formatStatus(record.status) }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.orders.paidAt')" data-index="paid_at">
            <template #cell="{ record }">
              {{ formatTime(record.paid_at) }}
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.orders.createdAt')" data-index="created_at">
            <template #cell="{ record }">
              {{ formatTime(record.created_at) }}
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.orders.actions')" :width="160">
            <template #cell="{ record }">
              <a-space>
                <a-button size="mini" @click="openDetail(record)">{{ t('admin.orders.detail') }}</a-button>
                <a-button v-if="canManageOrder && record.status === 'pending'" size="mini" status="danger" :loading="actionLoading" @click="handleClose(record)">
                  {{ t('admin.orders.close') }}
                </a-button>
              </a-space>
            </template>
          </a-table-column>
        </template>
      </a-table>
      <div class="pager">
        <a-pagination
          :total="total"
          :current="filters.current_page"
          :page-size="filters.page_size"
          show-total
          @change="onPageChange"
        />
      </div>
    </section>

    <a-modal :visible="detailVisible" :title="t('admin.orders.detailTitle')" :footer="false" @cancel="closeDetail">
      <div v-if="currentOrder" class="detail-grid">
        <div class="detail-item"><span>{{ t('admin.orders.orderNo') }}</span><strong>{{ currentOrder.order_no }}</strong></div>
        <div class="detail-item"><span>{{ t('admin.orders.user') }}</span><strong>{{ formatUser(currentOrder).name }}</strong></div>
        <div class="detail-item"><span>{{ t('admin.orders.userEmail') }}</span><strong>{{ currentOrder.user_email || '-' }}</strong></div>
        <div class="detail-item"><span>{{ t('admin.orders.accountId') }}</span><strong>{{ currentOrder.account_id }}</strong></div>
        <div class="detail-item"><span>{{ t('admin.orders.planType') }}</span><strong>{{ formatPlanType(currentOrder.plan_type) }}</strong></div>
        <div class="detail-item"><span>{{ t('admin.orders.amount') }}</span><strong>¥{{ Number(currentOrder.amount || 0).toFixed(2) }}</strong></div>
        <div class="detail-item"><span>{{ t('admin.orders.payMethod') }}</span><strong>{{ formatPayMethod(currentOrder.pay_method) }}</strong></div>
        <div class="detail-item"><span>{{ t('admin.orders.orderSource') }}</span><strong>{{ formatOrderSource(currentOrder.order_source) }}</strong></div>
        <div class="detail-item"><span>{{ t('admin.orders.status') }}</span><strong>{{ formatStatus(currentOrder.status) }}</strong></div>
        <div class="detail-item"><span>{{ t('admin.orders.transactionId') }}</span><strong>{{ currentOrder.transaction_id || '-' }}</strong></div>
        <div class="detail-item"><span>{{ t('admin.orders.paidAt') }}</span><strong>{{ formatTime(currentOrder.paid_at) }}</strong></div>
        <div class="detail-item"><span>{{ t('admin.orders.createdAt') }}</span><strong>{{ formatTime(currentOrder.created_at) }}</strong></div>
      </div>
    </a-modal>
  </section>
</template>

<style scoped>
.orders-page {
  display: grid;
  gap: 20px;
}

.page-header,
.panel,
.filter-panel {
  padding: 24px;
  border-radius: 22px;
  background: #fff;
  box-shadow: 0 14px 40px rgba(15, 23, 42, 0.06);
}

.page-header {
  background: linear-gradient(135deg, #101828, #36527e);
  color: #fff;
}

.page-kicker {
  margin: 0 0 8px;
  color: #a9c7ff;
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

h2,
h3,
p {
  margin: 0;
}

.page-header p:not(.page-kicker) {
  margin-top: 8px;
  color: #d8e4f7;
}

.filter-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 160px 160px auto;
  gap: 12px;
  box-shadow: none;
  border: 1px solid #eef2f7;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.detail-grid {
  display: grid;
  gap: 10px;
}

.detail-item {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 0;
  border-bottom: 1px solid #eef2f7;
}

.detail-item span {
  color: #667085;
}

.detail-item strong {
  color: #101828;
  word-break: break-all;
  text-align: right;
}

.cell-stack {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cell-sub {
  color: #667085;
  font-size: 12px;
}

.cell-id-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.cell-id {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 11px;
  color: #98a2b3;
}

@media (max-width: 960px) {
  .filter-panel {
    grid-template-columns: 1fr;
  }
}
</style>