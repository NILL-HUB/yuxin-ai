<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { cancelOrder, createRefund, listOrders } from '@/services/commerce'
import { type PurchaseOrder } from '@/models/commerce'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()

const PAGE_SIZE = 10

const loading = ref(false)
const orders = ref<PurchaseOrder[]>([])
const total = ref(0)
const page = ref(1)
const currentOrder = ref<PurchaseOrder | null>(null)
const refundReason = ref('')
const refunding = ref(false)
const cancellingNo = ref('')

const loadOrders = async () => {
  loading.value = true
  try {
    const result = await listOrders({ current_page: page.value, page_size: PAGE_SIZE })
    orders.value = result.list || []
    total.value = result.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.orders.loadFailed')))
  } finally {
    loading.value = false
  }
}

const onPageChange = async (nextPage: number) => {
  page.value = nextPage
  await loadOrders()
}

const openRefund = (order: PurchaseOrder) => {
  currentOrder.value = order
  refundReason.value = ''
}

const closeRefund = () => {
  currentOrder.value = null
  refundReason.value = ''
}

const canRefund = (order: PurchaseOrder) => {
  return order.status === 'paid'
}

const canCancel = (order: PurchaseOrder) => {
  return order.status === 'pending'
}

const handleSubmitRefund = async () => {
  if (!currentOrder.value) return
  const reason = refundReason.value.trim()
  if (!reason) {
    Message.error(t('membership.orders.refundReasonRequired'))
    return
  }
  refunding.value = true
  try {
    await createRefund(currentOrder.value.order_no, reason)
    Message.success(t('membership.orders.refundSubmitted'))
    closeRefund()
    await loadOrders()
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.orders.refundFailed')))
  } finally {
    refunding.value = false
  }
}

const handleCancelOrder = async (order: PurchaseOrder) => {
  cancellingNo.value = order.order_no
  try {
    await cancelOrder(order.order_no)
    Message.success(t('membership.orders.cancelled'))
    await loadOrders()
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.orders.cancelFailed')))
  } finally {
    cancellingNo.value = ''
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

onMounted(loadOrders)
</script>

<template>
  <section class="panel">
    <div class="panel-header">
      <div>
        <h3>{{ t('membership.orders.title') }}</h3>
        <p>{{ t('membership.orders.description') }}</p>
      </div>
    </div>

    <article v-for="order in orders" :key="order.order_no" class="order-row">
      <div class="order-info">
        <strong>{{ formatPlanType(order.plan_type) }} · ¥{{ Number(order.amount || 0).toFixed(2) }}</strong>
        <p>{{ order.order_no }} · {{ formatPayMethod(order.pay_method) }} · {{ formatOrderSource(order.order_source) }}</p>
        <p>{{ t('membership.orders.createdAt', { time: formatTime(order.created_at) }) }}</p>
        <p v-if="order.paid_at">{{ t('membership.orders.paidAt', { time: formatTime(order.paid_at) }) }}</p>
      </div>
      <div class="order-actions">
        <a-tag>{{ formatStatus(order.status) }}</a-tag>
        <a-button v-if="canRefund(order)" size="mini" type="primary" @click="openRefund(order)">
          {{ t('membership.orders.applyRefund') }}
        </a-button>
        <a-button v-if="canCancel(order)" size="mini" status="warning" :loading="cancellingNo === order.order_no" @click="handleCancelOrder(order)">
          {{ t('membership.orders.cancelOrder') }}
        </a-button>
      </div>
    </article>

    <p v-if="!loading && orders.length === 0" class="empty-text">{{ t('membership.orders.empty') }}</p>
    <div v-if="total > PAGE_SIZE" class="pager">
      <a-pagination :total="total" :current="page" :page-size="PAGE_SIZE" @change="onPageChange" />
    </div>

    <a-modal
      :visible="!!currentOrder"
      :title="t('membership.orders.refundTitle')"
      :ok-loading="refunding"
      @ok="handleSubmitRefund"
      @cancel="closeRefund"
    >
      <div class="refund-form">
        <p v-if="currentOrder" class="refund-target">
          {{ currentOrder.order_no }} · ¥{{ Number(currentOrder.amount || 0).toFixed(2) }}
        </p>
        <a-textarea
          v-model="refundReason"
          :placeholder="t('membership.orders.refundReasonPlaceholder')"
          :max-length="1024"
          show-word-limit
        />
      </div>
    </a-modal>
  </section>
</template>

<style scoped>
.panel {
  padding: 22px;
  border-radius: var(--aicss-radius-lg);
  border: 1px solid var(--aicss-border);
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
}

.panel-header h3,
.panel-header p {
  margin: 0;
}

.panel-header p {
  margin-top: 6px;
  color: var(--aicss-muted);
  font-size: 13px;
}

.order-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 14px 0;
  border-top: 1px solid var(--aicss-border);
}

.order-row:first-of-type {
  margin-top: 10px;
}

.order-info strong {
  color: var(--aicss-text);
  font-size: 15px;
}

.order-info p {
  margin: 4px 0 0;
  color: var(--aicss-muted);
  font-size: 13px;
}

.order-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.empty-text {
  margin: 16px 0 0;
  color: var(--aicss-muted);
  font-size: 13px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.refund-form {
  display: grid;
  gap: 12px;
}

.refund-target {
  margin: 0;
  color: var(--aicss-text);
  font-weight: 600;
}

@media (max-width: 640px) {
  .order-row {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }

  .order-info {
    min-width: 0;
  }

  .order-info strong,
  .order-info p {
    word-break: break-all;
  }

  .order-actions {
    justify-content: flex-end;
  }

  .pager {
    justify-content: center;
    flex-wrap: wrap;
  }
}
</style>