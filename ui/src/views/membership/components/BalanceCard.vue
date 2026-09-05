<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { redeemCode } from '@/services/billing'
import { cancelWithdrawal, createWithdrawal, listWithdrawals } from '@/services/balance'
import { createOrder, getOrderDetail, listPlans } from '@/services/commerce'
import { type BalanceProfile, type CommercePlan, type WithdrawalRecord } from '@/models/commerce'
import { getErrorMessage } from '@/utils/error'

const props = defineProps<{
  profile: BalanceProfile | null
}>()

const emit = defineEmits<{
  (event: 'redeemed'): void
  (event: 'balance-changed'): void
}>()

const { t } = useI18n()

const MIN_WITHDRAW_AMOUNT = 1
const WITHDRAW_PAGE_SIZE = 10
const ONLINE_CHANNELS: Array<{ label: string; value: string }> = [
  { label: 'wechat', value: 'wechat' },
  { label: 'alipay', value: 'alipay' },
]

const plansLoading = ref(false)
const plans = ref<CommercePlan[]>([])
const code = ref('')

const topupPlanId = ref('')
const topupChannel = ref('')
const purchasePlanId = ref('')
const purchaseMethod = ref('balance')
const orderLoading = ref(false)
const redeeming = ref(false)
const unavailableChannels = ref<Set<string>>(new Set())

const withdrawing = ref(false)
const withdrawAmount = ref<number | undefined>(undefined)
const withdrawals = ref<WithdrawalRecord[]>([])
const withdrawalsTotal = ref(0)
const withdrawalsPage = ref(1)

const balanceTopupPlans = computed(() =>
  plans.value.filter((plan) => plan.plan_type === 'balance' && plan.status === 'active'),
)
const purchasePlans = computed(() =>
  plans.value.filter((plan) => plan.plan_type !== 'balance' && plan.status === 'active'),
)

const channelOptions = computed(() =>
  ONLINE_CHANNELS.map((channel) => ({
    label: t(`membership.balance.payMethod.${channel.value}`),
    value: channel.value,
    disabled: unavailableChannels.value.has(channel.value),
  })),
)

const selectedPurchasePlan = computed(() =>
  plans.value.find((plan) => plan.id === purchasePlanId.value),
)

const balanceNotEnough = computed(() => {
  const selectedPlan = plans.value.find((plan) => plan.id === purchasePlanId.value)
  if (!selectedPlan || purchaseMethod.value !== 'balance') return false
  return Number(props.profile?.balance ?? 0) < Number(selectedPlan.price)
})

const formatMoney = (value: number | undefined | null) => {
  return Number(value || 0).toFixed(2)
}

const loadPlans = async () => {
  plansLoading.value = true
  try {
    const result = await listPlans({ current_page: 1, page_size: 50, status: 'active' })
    plans.value = result.list || []
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.balance.loadPlansFailed')))
  } finally {
    plansLoading.value = false
  }
}

const loadWithdrawals = async () => {
  try {
    const result = await listWithdrawals({
      current_page: withdrawalsPage.value,
      page_size: WITHDRAW_PAGE_SIZE,
    })
    withdrawals.value = result.list || []
    withdrawalsTotal.value = result.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.balance.loadWithdrawalsFailed')))
  }
}

const onWithdrawPageChange = async (page: number) => {
  withdrawalsPage.value = page
  await loadWithdrawals()
}

const handleRedeem = async () => {
  const trimCode = code.value.trim()
  if (!trimCode) return
  redeeming.value = true
  try {
    await redeemCode(trimCode)
    Message.success(t('membership.balance.redeemSuccess'))
    code.value = ''
    emit('redeemed')
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.balance.redeemFailed')))
  } finally {
    redeeming.value = false
  }
}

const isChannelUnavailableError = (error: unknown) => {
  const message = getErrorMessage(error, '')
  return message.includes('渠道') && (message.includes('未开通') || message.includes('未配置'))
}

const handleCreateOrder = async (planId: string, payMethod: string) => {
  orderLoading.value = true
  try {
    const result = await createOrder(planId, payMethod)
    if (payMethod === 'balance') {
      Message.success(t('membership.balance.purchaseSuccess'))
      emit('balance-changed')
    } else if (result?.payment_params) {
      await openPayment(result.order, result.payment_params as Record<string, string>)
    } else if (result?.order?.status === 'paid') {
      Message.success(t('membership.balance.purchaseSuccess'))
      emit('balance-changed')
    } else {
      Message.success(t('membership.balance.onlineOrderCreated'))
    }
    topupPlanId.value = ''
    topupChannel.value = ''
    purchasePlanId.value = ''
  } catch (error) {
    if (isChannelUnavailableError(error) && payMethod !== 'balance') {
      unavailableChannels.value.add(payMethod)
      Message.warning(t('membership.balance.channelUnavailable', { channel: t(`membership.balance.payMethod.${payMethod}`) }))
    } else {
      Message.error(getErrorMessage(error, t('membership.balance.orderFailed')))
    }
  } finally {
    orderLoading.value = false
  }
}

const payModalOpen = ref(false)
const payProvider = ref('')
const payType = ref('')
const payOrderNo = ref('')
const payAmount = ref(0)
const payUrl = ref('')
const payCodeUrl = ref('')
const qrDataUrl = ref('')
const payChecking = ref(false)

const openPayment = async (order: { order_no: string; amount: number; pay_method: string } | null, params: Record<string, string>) => {
  payOrderNo.value = order?.order_no || params.out_trade_no || ''
  payAmount.value = Number(params.amount ?? order?.amount ?? 0)
  payProvider.value = String(params.provider || order?.pay_method || '')
  payType.value = String(params.pay_type || '')
  payUrl.value = String(params.pay_url || '')
  payCodeUrl.value = String(params.code_url || '')
  qrDataUrl.value = ''
  payModalOpen.value = true
  if (payType.value === 'native' && payCodeUrl.value) {
    try {
      const QRCode = (await import('qrcode')).default
      qrDataUrl.value = await QRCode.toDataURL(payCodeUrl.value, { width: 260, margin: 1 })
    } catch {
      qrDataUrl.value = ''
    }
  }
}

const closePayment = () => {
  payModalOpen.value = false
}

const openAlipay = () => {
  if (payUrl.value) window.open(payUrl.value, '_blank')
}

const refreshPayStatus = async () => {
  if (!payOrderNo.value) return
  payChecking.value = true
  try {
    const order = await getOrderDetail(payOrderNo.value)
    if (order?.status === 'paid') {
      Message.success(t('membership.balance.purchaseSuccess'))
      payModalOpen.value = false
      emit('balance-changed')
    } else if (order?.status === 'closed') {
      Message.info(t('membership.balance.orderClosed'))
      payModalOpen.value = false
    } else {
      Message.info(t('membership.balance.payStillPending'))
    }
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.balance.orderFailed')))
  } finally {
    payChecking.value = false
  }
}

const handleTopup = () => {
  if (!topupPlanId.value || !topupChannel.value) return
  return handleCreateOrder(topupPlanId.value, topupChannel.value)
}

const handlePurchase = () => {
  if (!purchasePlanId.value) return
  return handleCreateOrder(purchasePlanId.value, purchaseMethod.value)
}

const handleWithdraw = async () => {
  const amount = Number(withdrawAmount.value || 0)
  if (!amount || amount < MIN_WITHDRAW_AMOUNT) {
    Message.error(t('membership.balance.withdrawMinTip'))
    return
  }
  withdrawing.value = true
  try {
    await createWithdrawal(amount)
    Message.success(t('membership.balance.withdrawSuccess'))
    withdrawAmount.value = undefined
    withdrawalsPage.value = 1
    await loadWithdrawals()
    emit('balance-changed')
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.balance.withdrawFailed')))
  } finally {
    withdrawing.value = false
  }
}

const handleCancelWithdraw = async (record: WithdrawalRecord) => {
  withdrawing.value = true
  try {
    await cancelWithdrawal(record.id)
    Message.success(t('membership.balance.withdrawCancelled'))
    await loadWithdrawals()
    emit('balance-changed')
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.balance.withdrawCancelFailed')))
  } finally {
    withdrawing.value = false
  }
}

const formatTime = (value: number | null) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const formatWithdrawStatus = (status: string) => {
  return t(`membership.status.withdraw.${status}`)
}

onMounted(() => {
  loadPlans()
  loadWithdrawals()
})
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <div class="head-copy">
        <h3>{{ t('membership.balance.title') }}</h3>
        <p>{{ t('membership.balance.description') }}</p>
      </div>
    </div>

    <div class="balance-grid">
      <div class="balance-item accent">
        <span>{{ t('membership.balance.available') }}</span>
        <strong>¥{{ formatMoney(profile?.balance) }}</strong>
      </div>
      <div class="balance-item">
        <span>{{ t('membership.balance.recharge') }}</span>
        <strong>¥{{ formatMoney(profile?.recharge_balance) }}</strong>
      </div>
      <div class="balance-item commission">
        <span>{{ t('membership.balance.commission') }}</span>
        <strong>¥{{ formatMoney(profile?.commission_balance) }}</strong>
      </div>
      <div class="balance-item">
        <span>{{ t('membership.balance.totalWithdrawn') }}</span>
        <strong>¥{{ formatMoney(profile?.total_withdrawn) }}</strong>
      </div>
      <div class="balance-item">
        <span>{{ t('membership.balance.totalPurchased') }}</span>
        <strong>¥{{ formatMoney(profile?.total_purchased) }}</strong>
      </div>
    </div>

    <div class="sub-grid">
      <section class="sub-card">
        <h4>{{ t('membership.balance.redeemTitle') }}</h4>
        <div class="inline-form">
          <a-input v-model="code" :placeholder="t('membership.balance.redeemPlaceholder')" />
          <a-button type="primary" :loading="redeeming" @click="handleRedeem">
            {{ t('membership.balance.redeem') }}
          </a-button>
        </div>
      </section>

      <section class="sub-card">
        <h4>{{ t('membership.balance.topupTitle') }}</h4>
        <div class="stack-form">
          <a-select
            v-model="topupPlanId"
            :placeholder="t('membership.balance.topupPlanPlaceholder')"
            :options="balanceTopupPlans.map((plan) => ({ label: `${plan.name} · ¥${Number(plan.price).toFixed(2)}`, value: plan.id }))"
            :loading="plansLoading"
          />
          <a-select
            v-model="topupChannel"
            :placeholder="t('membership.balance.topupChannelPlaceholder')"
            :options="channelOptions"
          />
          <a-button type="primary" :loading="orderLoading" :disabled="!topupPlanId || !topupChannel" @click="handleTopup">
            {{ t('membership.balance.topup') }}
          </a-button>
        </div>
      </section>

      <section class="sub-card">
        <h4>{{ t('membership.balance.purchaseTitle') }}</h4>
        <div class="stack-form">
          <a-select
            v-model="purchasePlanId"
            :placeholder="t('membership.balance.purchasePlanPlaceholder')"
            :options="purchasePlans.map((plan) => ({ label: `${plan.name} · ¥${Number(plan.price).toFixed(2)}`, value: plan.id }))"
            :loading="plansLoading"
          />
          <a-radio-group v-model="purchaseMethod" type="button">
            <a-radio value="balance">{{ t('membership.balance.payMethod.balance') }}</a-radio>
            <a-radio value="wechat" :disabled="unavailableChannels.has('wechat')">{{ t('membership.balance.payMethod.wechat') }}</a-radio>
            <a-radio value="alipay" :disabled="unavailableChannels.has('alipay')">{{ t('membership.balance.payMethod.alipay') }}</a-radio>
          </a-radio-group>
          <p v-if="selectedPurchasePlan?.auto_renew_default" class="hint auto-renew-tip">
            <a-tag color="purple" size="small">{{ t('membership.balance.autoRenew') }}</a-tag>
            {{ t('membership.balance.autoRenewTip') }}
          </p>
          <p v-if="balanceNotEnough" class="hint danger">{{ t('membership.balance.lowBalance') }}</p>
          <a-button type="primary" :loading="orderLoading" :disabled="!purchasePlanId" @click="handlePurchase">
            {{ t('membership.balance.purchase') }}
          </a-button>
        </div>
      </section>

      <section class="sub-card">
        <h4>{{ t('membership.balance.withdrawTitle') }}</h4>
        <div class="inline-form">
          <a-input-number v-model="withdrawAmount" :min="MIN_WITHDRAW_AMOUNT" :precision="2" :placeholder="t('membership.balance.withdrawAmountPlaceholder')" />
          <a-button type="primary" :loading="withdrawing" @click="handleWithdraw">
            {{ t('membership.balance.withdraw') }}
          </a-button>
        </div>
        <div class="withdraw-list">
          <p class="list-title">{{ t('membership.balance.withdrawRecords') }}</p>
          <article v-for="record in withdrawals" :key="record.id" class="tx-row compact">
            <div>
              <strong>¥{{ formatMoney(record.amount) }}</strong>
              <p>{{ formatWithdrawStatus(record.status) }} · {{ formatTime(record.created_at) }}</p>
              <p v-if="record.review_note">{{ record.review_note }}</p>
            </div>
            <a-button v-if="record.status === 'pending'" size="mini" status="warning" :loading="withdrawing" @click="handleCancelWithdraw(record)">
              {{ t('membership.balance.cancelWithdraw') }}
            </a-button>
          </article>
          <p v-if="withdrawals.length === 0" class="empty-text">{{ t('membership.balance.noWithdrawals') }}</p>
          <a-pagination
            v-if="withdrawalsTotal > WITHDRAW_PAGE_SIZE"
            :total="withdrawalsTotal"
            :current="withdrawalsPage"
            :page-size="WITHDRAW_PAGE_SIZE"
            @change="onWithdrawPageChange"
          />
        </div>
      </section>
    </div>

    <!-- 在线支付弹窗 -->
    <a-modal
      :visible="payModalOpen"
      :title="t('membership.balance.payModalTitle')"
      :footer="false"
      width="360"
      @cancel="closePayment"
    >
      <div class="pay-modal">
        <p class="pay-order-line">
          {{ t('membership.balance.payOrderNo') }}：<code>{{ payOrderNo }}</code>
        </p>
        <p class="pay-amount">¥{{ formatMoney(payAmount) }}</p>
        <template v-if="payType === 'native'">
          <div v-if="qrDataUrl" class="pay-qr">
            <img :src="qrDataUrl" alt="QR" />
          </div>
          <p v-else class="pay-hint">{{ t('membership.balance.payCodeUrlHint', { url: payCodeUrl }) }}</p>
          <p class="pay-tip">{{ t('membership.balance.wechatScanTip') }}</p>
        </template>
        <template v-else-if="payProvider === 'alipay'">
          <a-button type="primary" long :loading="payChecking" @click="openAlipay">
            {{ t('membership.balance.openAlipay') }}
          </a-button>
          <p class="pay-tip">{{ t('membership.balance.alipayPageTip') }}</p>
        </template>
        <div class="pay-actions">
          <a-button type="secondary" :loading="payChecking" @click="refreshPayStatus">
            {{ t('membership.balance.refreshPayStatus') }}
          </a-button>
          <a-button type="text" @click="closePayment">{{ t('common.actions.close') }}</a-button>
        </div>
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

.pay-modal {
  display: grid;
  gap: 10px;
  text-align: center;
}

.pay-order-line {
  color: var(--aicss-muted);
  font-size: 13px;
  word-break: break-all;
}

.pay-order-line code {
  font-family: 'SFMono-Regular', Consolas, Menlo, monospace;
  font-size: 12px;
}

.pay-amount {
  font-size: 26px;
  font-weight: 700;
  color: var(--aicss-strong);
  font-variant-numeric: tabular-nums;
}

.pay-qr {
  padding: 10px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius-md);
  background: #fff;
}

.pay-qr img {
  display: block;
  width: 260px;
  height: 260px;
  margin: 0 auto;
}

.pay-hint {
  padding: 18px;
  border-radius: var(--aicss-radius-md);
  background: var(--aicss-bg-muted, #f5f7fa);
  color: var(--aicss-muted);
  font-size: 13px;
  word-break: break-all;
}

.pay-tip {
  color: var(--aicss-muted);
  font-size: 12px;
}

.pay-actions {
  display: flex;
  justify-content: center;
  gap: 8px;
  margin-top: 6px;
}

.panel-head h3,
.panel-head p,
h4 {
  margin: 0;
}

.panel-head .head-copy h3 {
  font-family: var(--aicss-font-serif, Georgia, 'Songti SC', serif);
  font-size: 19px;
  letter-spacing: -0.02em;
  color: var(--aicss-text);
}

.panel-head .head-copy p {
  margin-top: 4px;
  color: var(--aicss-muted);
  font-size: 12px;
}

.balance-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.balance-item {
  padding: 14px 16px;
  border-radius: var(--aicss-radius);
  border: 1px solid var(--aicss-border);
  background: var(--aicss-bg-subtle);
  transition: box-shadow 0.18s ease;
}
.balance-item:hover {
  box-shadow: var(--aicss-shadow-card);
}

.balance-item.accent {
  border-color: color-mix(in srgb, var(--aicss-accent) 22%, var(--aicss-border));
  background: var(--aicss-accent-soft);
}

.balance-item span {
  color: var(--aicss-muted);
  font-size: 13px;
}

.balance-item strong {
  display: block;
  margin-top: 6px;
  font-size: 22px;
  color: var(--aicss-text);
  font-variant-numeric: tabular-nums;
}

.balance-item.accent strong {
  color: var(--aicss-accent-text);
}

.balance-item.commission {
  border-color: color-mix(in srgb, var(--aicss-accent) 22%, var(--aicss-border));
  background: var(--aicss-accent-soft);
}
.balance-item.commission strong {
  color: var(--aicss-accent-text);
}

.sub-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-top: 16px;
}

.sub-card {
  padding: 18px;
  border-radius: var(--aicss-radius);
  border: 1px solid var(--aicss-border);
  background: var(--aicss-bg-subtle);
}

.sub-card h4 {
  margin-bottom: 12px;
  font-size: 15px;
  color: var(--aicss-text);
}

.inline-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
}

.stack-form {
  display: grid;
  gap: 10px;
}

.hint {
  margin: 0;
  font-size: 13px;
  color: var(--aicss-muted);
}

.hint.danger {
  color: var(--aicss-danger, #f53f3f);
}

.auto-renew-tip {
  display: flex;
  align-items: center;
  gap: 8px;
}

.withdraw-list {
  margin-top: 14px;
}

.list-title {
  margin: 0 0 4px;
  color: var(--aicss-muted);
  font-size: 13px;
}

.tx-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-top: 1px solid var(--aicss-border);
}

.tx-row strong {
  color: var(--aicss-text);
}

.tx-row p {
  margin: 4px 0 0;
  color: var(--aicss-muted);
  font-size: 13px;
}

.empty-text {
  margin: 8px 0 0;
  color: var(--aicss-muted);
  font-size: 13px;
}

@media (max-width: 960px) {
  .balance-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .sub-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .balance-item {
    padding: 12px 14px;
  }
  .balance-item strong {
    font-size: 19px;
  }
}
</style>