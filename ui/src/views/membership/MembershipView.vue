<script setup lang="ts">
/**
 * 会员中心 — 原型复刻布局 + 真实接口数据
 *
 * 布局 1:1 对齐画布原型 membership.html；数据来自真实接口：
 * /membership/summary、/redeem-codes/redeem、/account/balance、
 * /balance/withdrawals、/orders、/auto-renewals、/plans、分销接口等。
 * 写操作面板（充值/购买/兑换/提现/续费）复用已封装组件的完整交互。
 */
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  getMembershipSummary,
  getRedeemRecords,
  redeemCode,
} from '@/services/billing'
import { getBalanceProfile, listWithdrawals, createWithdrawal } from '@/services/balance'
import {
  cancelOrder,
  createAutoRenewal,
  createOrder,
  createRefund,
  listAutoRenewals,
  listOrders,
  listPlans,
  setAutoRenewalStatus,
} from '@/services/commerce'
import {
  getDistributionQrcode,
  getMyDistribution,
  listMyCommissions,
  listSubordinates,
} from '@/services/distribution'
import type {
  AutoRenewal,
  BalanceProfile,
  CommercePlan,
  PurchaseOrder,
  WithdrawalRecord,
} from '@/models/commerce'
import type {
  CreditTransaction,
  MembershipSummary,
  RedeemRecord,
} from '@/models/billing'
import type {
  DistributionCommission,
  DistributionSubordinate,
  MyDistribution,
} from '@/models/distribution'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()

// ---------- 只读概览数据 ----------
const summary = ref<MembershipSummary | null>(null)
const profile = ref<BalanceProfile | null>(null)
const redeemRecords = ref<RedeemRecord[]>([])
const withdrawRecords = ref<WithdrawalRecord[]>([])
const orders = ref<PurchaseOrder[]>([])
const renewals = ref<AutoRenewal[]>([])
const distribution = ref<MyDistribution | null>(null)
const subordinates = ref<DistributionSubordinate[]>([])
const commissions = ref<DistributionCommission[]>([])
const qrcodeUrl = ref('')
const plans = ref<CommercePlan[]>([])
const loading = ref(false)

// 折叠面板状态（保持复刻版交互）
const openPanel = ref('')
const togglePanel = (id: string) => {
  openPanel.value = openPanel.value === id ? '' : id
}

// ---------- 展示辅助 ----------
const planLabel = (o: PurchaseOrder) => {
  const plan = plans.value.find((p) => p.id === o.plan_id)
  return plan?.name || (o.plan_type === 'balance' ? '余额充值' : '会员套餐')
}
const payMethodLabel = (m: string) => {
  return t(`membership.balance.payMethod.${m}`) || m
}
const orderStatus = (s: string) => {
  const key = `membership.status.order.${s}`
  const label = t(key)
  return label === key ? s : label
}
const orderStatusClass = (s: string) => {
  if (s === 'paid') return 'pill-soft'
  if (s === 'pending') return 'pill-neutral'
  if (s === 'refunded') return 'pill-muted'
  return 'pill-neutral'
}
const transactionTypeLabel = (type: string) => {
  if (type.includes('redeem')) return '兑换'
  if (type.includes('order') || type.includes('grant')) return '获得'
  if (type.includes('consume')) return '消费'
  return type
}
const flowAmount = (f: CreditTransaction) => {
  const v = Number(f.amount)
  if (v > 0) return `+${formatNum(v)}`
  if (v < 0) return formatNum(v)
  return '0'
}
const withdrawStatusLabel = (s: string) => t(`membership.status.withdraw.${s}`) || s
const renewalStatusLabel = (s: string) => t(`membership.autoRenewal.status.${s}`) || s

// 佣金来源：优先接口返回的购买者名；否则从描述中提取“· 用户名”段；再退化为“下级用户”
const commissionSource = (c: DistributionCommission) => {
  if (c.buyer_name) return c.buyer_name
  const desc = c.description || ''
  const m = desc.match(/(?:·|返佣\s*)\s*([^\s·]+)$/)
  if (m && !/^[\d.%]+$/.test(m[1])) return m[1]
  return '下级用户'
}

// ---------- 派生展示数据 ----------
const formatMoney = (value: number | null | undefined) => Number(value || 0).toFixed(2)
const formatNum = (value: number | null | undefined) => Number(value || 0).toLocaleString()
const formatTime = (value: number | null) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}
const formatDate = (value: number | null) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleDateString('zh-CN', { hour12: false })
}

const balanceItems = computed(() => [
  { label: '可用余额', value: `¥${formatMoney(profile.value?.balance)}`, highlight: false },
  { label: '充值余额', value: `¥${formatMoney(profile.value?.recharge_balance)}`, highlight: false },
  { label: '分销佣金', value: `¥${formatMoney(profile.value?.commission_balance)}`, highlight: true },
  { label: '累计提现', value: `¥${formatMoney(profile.value?.total_withdrawn)}`, highlight: false },
  { label: '累计消费', value: `¥${formatMoney(profile.value?.total_purchased)}`, highlight: false },
])

const compute = computed(() => ({
  quota: formatNum(profile.value?.quota_credit),
  permanent: formatNum(profile.value?.permanent_credit),
}))

const planInfo = computed(() => ({
  name: summary.value?.membership?.plan?.name || '暂无会员',
  expire: formatDate(summary.value?.membership?.expires_at ?? null),
}))

const creditAccount = computed(() => ({
  granted: `+${formatNum(summary.value?.credit_account?.total_granted)}`,
  consumed: `−${formatNum(summary.value?.credit_account?.total_consumed)}`,
}))

// 最近任务消耗：一次用户提问=一条算力消费。优先展示问题原文，无消息时退化为通用说明。
const recentConsumes = computed(() => {
  const tasks = summary.value?.recent_tasks || []
  return tasks.slice(0, 6).map((f) => ({
    id: f.id,
    name: f.message || '算力任务消耗',
    cost: Math.abs(Number(f.amount)),
    time: formatTime(f.created_at),
    full: f.message || '',
  }))
})

const currentCredit = computed(() => formatNum(summary.value?.credit_account?.balance))

const consumeTotal = computed(() => {
  const tasks = summary.value?.recent_tasks || []
  return tasks
    .slice(0, 6)
    .reduce((sum, f) => sum + Math.abs(Number(f.amount)), 0)
})

// 订单表行
const orderRows = computed(() =>
  orders.value.map((o) => ({
    plan: planLabel(o),
    amount: `¥${formatMoney(o.amount)}`,
    no: o.order_no,
    pay: payMethodLabel(o.pay_method),
    status: orderStatus(o.status),
    time: formatTime(o.created_at),
    raw: o,
  })),
)

const redeemRows = computed(() =>
  redeemRecords.value.map((r) => ({
    code: r.code_mask,
    plan: r.plan?.name || '未知套餐',
    time: formatTime(r.redeemed_at),
    expire: formatDate(r.membership_expires_at),
    credit: `+${formatNum(r.grant_token_credits)}`,
  })),
)

const creditFlows = computed(() =>
  (summary.value?.recent_transactions || []).map((f) => {
    // 消费描述：后端已把 token 算式替换为用户问题（问题过长用 title 全文展示）
    const isConsume = f.transaction_type === 'consume' || Number(f.amount) < 0
    const raw = f.description || ''
    const looksTokenMath = /token|算力值|1k token|余额不足/i.test(raw)
    const desc = isConsume && (!raw || looksTokenMath) ? '模型对话算力消耗' : raw
    return {
      desc,
      type: transactionTypeLabel(f.transaction_type),
      time: formatTime(f.created_at),
      amount: flowAmount(f),
      positive: Number(f.amount) >= 0,
      isConsume,
    }
  }),
)

const commissionRate = computed(() => distribution.value?.commission_rate || '0')
const highRateLocked = computed(() => distribution.value?.high_rate_locked || profile.value?.high_rate_locked || false)
const subordinateCount = computed(() => distribution.value?.subordinate_count ?? 0)

// 分销分页：下级与佣金记录在分销大卡中完整展示
const SUB_PAGE_SIZE = 6
const COMMISSION_PAGE_SIZE = 6
const subPage = ref(1)
const subTotal = ref(0)
const commissionPage = ref(1)
const commissionTotal = ref(0)
const subLoading = ref(false)
const commissionLoading = ref(false)
const loadSubordinates = async (page = subPage.value) => {
  subLoading.value = true
  try {
    const res = await listSubordinates({ current_page: page, page_size: SUB_PAGE_SIZE })
    subordinates.value = res.list || []
    subTotal.value = res.paginator?.total_record ?? 0
    subPage.value = page
  } catch {
    /* 静默 */
  } finally {
    subLoading.value = false
  }
}
const loadCommissions = async (page = commissionPage.value) => {
  commissionLoading.value = true
  try {
    const res = await listMyCommissions({ current_page: page, page_size: COMMISSION_PAGE_SIZE })
    commissions.value = res.list || []
    commissionTotal.value = res.paginator?.total_record ?? 0
    commissionPage.value = page
  } catch {
    /* 静默 */
  } finally {
    commissionLoading.value = false
  }
}

// ---------- 数据加载 ----------
const loadAll = async () => {
  loading.value = true
  try {
    const [s, rec] = await Promise.all([getMembershipSummary(), getRedeemRecords()])
    summary.value = s
    redeemRecords.value = rec.list
  } catch (error) {
    Message.error(getErrorMessage(error, '加载会员信息失败'))
  } finally {
    loading.value = false
  }
  void reloadSecondary()
}

const reloadSecondary = async () => {
  try {
    profile.value = await getBalanceProfile()
  } catch {
    /* 静默 */
  }
  try {
    const [w, o, r, d] = await Promise.all([
      listWithdrawals({ current_page: 1, page_size: 5 }),
      listOrders({ current_page: 1, page_size: 10 }),
      listAutoRenewals(),
      getMyDistribution(),
    ])
    withdrawRecords.value = w.list || []
    orders.value = o.list || []
    renewals.value = r.list || []
    distribution.value = d
    try {
      const qrcode = await getDistributionQrcode()
      qrcodeUrl.value = qrcode.qrcode_url || ''
      if (qrcode.share_url) shareUrlText.value = qrcode.share_url
    } catch {
      /* 二维码失败可忽略 */
    }
  } catch {
    /* 部分接口失败不阻塞整体 */
  }
  try {
    const plansRes = await listPlans({ current_page: 1, page_size: 100, status: 'active' })
    plans.value = plansRes.list || []
  } catch {
    /* 静默 */
  }
  await Promise.all([loadSubordinates(1), loadCommissions(1)])
}

// ---------- 交易交互 ----------
const balancePlans = computed(() => plans.value.filter((p) => p.plan_type === 'balance'))
const memberPlans = computed(() => plans.value.filter((p) => p.plan_type !== 'balance'))

// 兑换
const code = ref('')
const redeeming = ref(false)
const handleRedeem = async () => {
  const trimCode = code.value.trim()
  if (!trimCode) {
    Message.warning('请输入卡密码')
    return
  }
  redeeming.value = true
  try {
    await redeemCode(trimCode)
    Message.success('兑换成功')
    code.value = ''
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '兑换失败'))
  } finally {
    redeeming.value = false
  }
}

// 在线充值 / 购买：选套餐 → 创建订单（余额直接成功；在线渠道走收银台/提示）
const topupPlanId = ref('')
const topupChannel = ref('')
const purchasePlanId = ref('')
const purchaseMethod = ref('balance')
const orderLoading = ref(false)
const balanceNotEnough = computed(() => {
  const plan = plans.value.find((p) => p.id === purchasePlanId.value)
  if (!plan || purchaseMethod.value !== 'balance') return false
  return Number(profile.value?.balance ?? 0) < Number(plan.price)
})
const handleTopup = async () => {
  if (!topupPlanId.value || !topupChannel.value) return
  orderLoading.value = true
  try {
    const result = await createOrder(topupPlanId.value, topupChannel.value)
    if (result?.payment_params) {
      Message.info('在线支付订单已创建，请在支付完成后刷新查看')
    } else {
      Message.success('充值成功')
      await loadAll()
    }
    topupPlanId.value = ''
    topupChannel.value = ''
  } catch (error) {
    Message.error(getErrorMessage(error, '创建充值订单失败'))
  } finally {
    orderLoading.value = false
  }
}
const handlePurchase = async () => {
  if (!purchasePlanId.value) return
  orderLoading.value = true
  try {
    const result = await createOrder(purchasePlanId.value, purchaseMethod.value)
    if (purchaseMethod.value === 'balance') {
      Message.success('购买成功')
    } else if (result?.payment_params) {
      Message.info('在线支付订单已创建，请在支付完成后刷新查看')
    } else {
      Message.success('购买成功')
    }
    purchasePlanId.value = ''
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '创建购买订单失败'))
  } finally {
    orderLoading.value = false
  }
}

// 提现
const withdrawAmount = ref<number | null>(null)
const withdrawing = ref(false)
const handleWithdraw = async () => {
  const amount = Number(withdrawAmount.value || 0)
  if (!amount || amount < 1) {
    Message.warning('最低提现金额 1 元')
    return
  }
  withdrawing.value = true
  try {
    await createWithdrawal(amount)
    Message.success('提现申请已提交')
    withdrawAmount.value = null
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, '提现申请失败'))
  } finally {
    withdrawing.value = false
  }
}

// 续费操作（暂停/恢复/取消）—— 并入「当前套餐」卡一体管理
const renewalLoadingId = ref('')
const handleRenewalAction = async (item: AutoRenewal, action: 'pause' | 'resume' | 'cancel') => {
  renewalLoadingId.value = item.id
  try {
    await setAutoRenewalStatus(item.id, action)
    Message.success('操作成功')
    await reloadSecondary()
  } catch (error) {
    Message.error(getErrorMessage(error, '操作失败'))
  } finally {
    renewalLoadingId.value = ''
  }
}

// 在套餐卡内开启自动续费（余额扣款）
const renewOpen = ref(false)
const renewPlanId = ref('')
const renewing = ref(false)
const renewablePlans = computed(() =>
  plans.value.filter((p) => p.status === 'active' && p.plan_type !== 'balance'),
)
const handleEnableRenewal = async () => {
  if (!renewPlanId.value) {
    Message.warning('请选择要续费的套餐')
    return
  }
  renewing.value = true
  try {
    await createAutoRenewal(renewPlanId.value, 'balance')
    Message.success('自动续费已开启')
    renewOpen.value = false
    renewPlanId.value = ''
    await reloadSecondary()
  } catch (error) {
    Message.error(getErrorMessage(error, '开启自动续费失败'))
  } finally {
    renewing.value = false
  }
}

// 订单操作（取消/退款）
const orderActionLoading = ref('')
const refundModal = ref<PurchaseOrder | null>(null)
const refundReason = ref('')
const openRefundModal = (o: PurchaseOrder) => {
  refundModal.value = o
  refundReason.value = ''
}
const submitRefund = async () => {
  if (!refundModal.value) return
  if (!refundReason.value.trim()) {
    Message.warning('请填写退款原因')
    return
  }
  orderActionLoading.value = 'refund'
  try {
    await createRefund(refundModal.value.order_no, refundReason.value.trim())
    Message.success('退款申请已提交')
    refundModal.value = null
    await reloadSecondary()
  } catch (error) {
    Message.error(getErrorMessage(error, '提交退款失败'))
  } finally {
    orderActionLoading.value = ''
  }
}
const handleCancelOrder = async (o: PurchaseOrder) => {
  orderActionLoading.value = o.order_no
  try {
    await cancelOrder(o.order_no)
    Message.success('订单已取消')
    await reloadSecondary()
  } catch (error) {
    Message.error(getErrorMessage(error, '取消订单失败'))
  } finally {
    orderActionLoading.value = ''
  }
}

// 分销复制
const shareUrlText = ref('')
const shareFallback = computed(() => distribution.value?.share_url || shareUrlText.value || '')
const handleCopy = async (text: string) => {
  try {
    await navigator.clipboard.writeText(text)
    Message.success('已复制')
  } catch {
    Message.info(text)
  }
}

// 充值渠道（沿用在线渠道固定项）
const onlineChannels = computed(() => [
  { value: 'wechat', label: '微信支付' },
  { value: 'alipay', label: '支付宝' },
])

onMounted(loadAll)
</script>

<template>
  <div class="mock-page">
    <div class="mx-auto w-full max-w-6xl">
      <!-- ===== Hero ===== -->
      <section class="hero">
        <div class="hero-inner">
          <div class="hero-copy">
            <p class="kicker">Membership</p>
            <h1 class="serif hero-title">我的会员</h1>
            <p class="hero-desc">兑换卡密，查看余额、算力值套餐与分销收益。</p>
          </div>
          <div class="credit-chip">
            <p class="credit-chip-label">当前算力值</p>
            <p class="credit-chip-value mono">{{ currentCredit }}</p>
          </div>
        </div>
      </section>

      <!-- ===== 余额中心 ===== -->
      <section class="card pad">
        <div class="head-row">
          <span class="icon-sq primary"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/></svg></span>
          <div>
            <h2 class="serif card-title">余额中心</h2>
            <p class="card-sub">余额、佣金与提现一览</p>
          </div>
        </div>

        <!-- 5 指标 -->
        <dl class="metrics">
          <div v-for="item in balanceItems" :key="item.label" class="metric" :class="{ hl: item.highlight }">
            <dt>{{ item.label }}</dt>
            <dd class="mono">{{ item.value }}</dd>
          </div>
        </dl>

        <!-- 4 折叠入口 -->
        <div class="panel-stack">
          <!-- 卡密兑换 -->
          <details class="entry" :open="openPanel === 'redeem'">
            <summary class="entry-summary" @click.prevent="togglePanel('redeem')">
              <span class="icon-sq soft"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M13 5v2"/><path d="M13 17v2"/><path d="M13 11v2"/></svg></span>
              <span class="entry-copy">
                <span class="entry-name">卡密兑换</span>
                <span class="entry-desc">输入卡密码兑换算力与套餐</span>
              </span>
              <svg class="chev" :class="{ open: openPanel === 'redeem' }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
            </summary>
            <div v-if="openPanel === 'redeem'" class="entry-body">
              <label class="field-label" for="redeem-code">卡密码</label>
              <div class="field-row">
                <input id="redeem-code" v-model="code" type="text" placeholder="请输入 16 位卡密码" class="input" @keyup.enter="handleRedeem" />
                <button type="button" class="btn-primary" :disabled="redeeming" @click="handleRedeem">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M13 5v2"/><path d="M13 17v2"/><path d="M13 11v2"/></svg>{{ redeeming ? '兑换中…' : '兑换' }}</button>
              </div>
              <p class="hint">兑换成功后算力与套餐立即到账，可在下方兑换记录中查看。</p>
            </div>
          </details>

          <!-- 余额充值 -->
          <details class="entry" :open="openPanel === 'recharge'">
            <summary class="entry-summary" @click.prevent="togglePanel('recharge')">
              <span class="icon-sq soft"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="14" x="2" y="5" rx="2"/><line x1="2" x2="22" y1="10" y2="10"/></svg></span>
              <span class="entry-copy">
                <span class="entry-name">余额充值</span>
                <span class="entry-desc">充值余额，充得多送得多</span>
              </span>
              <svg class="chev" :class="{ open: openPanel === 'recharge' }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
            </summary>
            <div v-if="openPanel === 'recharge'" class="entry-body">
              <p class="field-label">选择充值套餐</p>
              <div v-if="balancePlans.length > 0" class="radio-grid cols-3">
                <label
                  v-for="p in balancePlans"
                  :key="p.id"
                  class="radio-card"
                  :class="{ checked: topupPlanId === p.id }"
                >
                  <input type="radio" name="recharge-plan" class="sr" :value="p.id" v-model="topupPlanId" />
                  <span class="radio-money mono">¥{{ Number(p.price).toFixed(0) }}</span>
                  <span class="radio-bonus" :class="{ accent: true }">{{ p.name }}</span>
                  <span class="radio-dot"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span>
                </label>
              </div>
              <p v-else class="hint">暂无可充值套餐</p>
              <p class="field-label">支付渠道</p>
              <div class="radio-grid cols-2">
                <label v-for="ch in onlineChannels" :key="ch.value" class="radio-card row" :class="{ checked: topupChannel === ch.value }">
                  <input type="radio" name="recharge-channel" class="sr" :value="ch.value" v-model="topupChannel" />
                  <svg v-if="ch.value === 'wechat'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="row-ico"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>
                  <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="row-ico"><rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/></svg>
                  <span class="grow">{{ ch.label }}</span>
                  <span class="radio-dot"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span>
                </label>
              </div>
              <button type="button" class="btn-primary block" :disabled="!topupPlanId || !topupChannel || orderLoading" @click="handleTopup">
                {{ orderLoading ? '处理中…' : '去支付' }}
              </button>
            </div>
          </details>

          <!-- 套餐购买 -->
          <details class="entry" :open="openPanel === 'plan'">
            <summary class="entry-summary" @click.prevent="togglePanel('plan')">
              <span class="icon-sq soft"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/></svg></span>
              <span class="entry-copy">
                <span class="entry-name">套餐购买</span>
                <span class="entry-desc">选购会员套餐，解锁更多算力</span>
              </span>
              <svg class="chev" :class="{ open: openPanel === 'plan' }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
            </summary>
            <div v-if="openPanel === 'plan'" class="entry-body">
              <p class="field-label">选择套餐</p>
              <div v-if="memberPlans.length > 0" class="radio-grid cols-3">
                <label
                  v-for="p in memberPlans"
                  :key="p.id"
                  class="radio-card"
                  :class="{ checked: purchasePlanId === p.id }"
                >
                  <input type="radio" name="buy-plan" class="sr" :value="p.id" v-model="purchasePlanId" />
                  <span class="radio-name">{{ p.name }}</span>
                  <span class="radio-bonus accent">¥{{ Number(p.price).toFixed(0) }}/月</span>
                  <span class="radio-dot"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span>
                </label>
              </div>
              <p v-else class="hint">暂无可购套餐</p>
              <p class="field-label">购买方式</p>
              <div class="radio-grid cols-3">
                <label class="radio-card row" :class="{ checked: purchaseMethod === 'balance' }">
                  <input type="radio" name="buy-pay" class="sr" value="balance" v-model="purchaseMethod" />
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="row-ico"><path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/></svg>
                  <span class="grow">余额</span>
                  <span class="radio-dot"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span>
                </label>
                <label class="radio-card row" :class="{ checked: purchaseMethod === 'wechat' }">
                  <input type="radio" name="buy-pay" class="sr" value="wechat" v-model="purchaseMethod" />
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="row-ico"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>
                  <span class="grow">微信</span>
                  <span class="radio-dot"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span>
                </label>
                <label class="radio-card row" :class="{ checked: purchaseMethod === 'alipay' }">
                  <input type="radio" name="buy-pay" class="sr" value="alipay" v-model="purchaseMethod" />
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="row-ico"><rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/></svg>
                  <span class="grow">支付宝</span>
                  <span class="radio-dot"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span>
                </label>
              </div>
              <p v-if="balanceNotEnough" class="hint danger">余额不足，请先充值</p>
              <button type="button" class="btn-primary" :disabled="!purchasePlanId || orderLoading" @click="handlePurchase">
                {{ orderLoading ? '处理中…' : '立即购买' }}
              </button>
            </div>
          </details>

          <!-- 余额提现 -->
          <details class="entry" :open="openPanel === 'withdraw'">
            <summary class="entry-summary" @click.prevent="togglePanel('withdraw')">
              <span class="icon-sq soft"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="12" x="2" y="6" rx="2"/><circle cx="12" cy="12" r="2"/><path d="M6 12h.01M18 12h.01"/></svg></span>
              <span class="entry-copy">
                <span class="entry-name">余额提现</span>
                <span class="entry-desc">将可提现佣金提至账户</span>
              </span>
              <svg class="chev" :class="{ open: openPanel === 'withdraw' }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
            </summary>
            <div v-if="openPanel === 'withdraw'" class="entry-body">
              <label class="field-label" for="withdraw-amount">提现金额</label>
              <div class="field-row">
                <input id="withdraw-amount" v-model.number="withdrawAmount" type="number" min="1" placeholder="可提现 ¥{{ formatMoney(profile?.commission_balance) }}" class="input mono" />
                <button type="button" class="btn-primary" :disabled="withdrawing" @click="handleWithdraw">
                  {{ withdrawing ? '提交中…' : '申请提现' }}
                </button>
              </div>
              <p class="list-label">提现记录</p>
              <ul v-if="withdrawRecords.length > 0" class="withdraw-list">
                <li v-for="r in withdrawRecords" :key="r.id">
                  <span class="mono">¥{{ formatMoney(r.amount) }}</span>
                  <span class="pill" :class="r.status === 'pending' ? 'pill-muted' : 'pill-soft'">{{ withdrawStatusLabel(r.status) }}</span>
                  <span class="date">{{ formatDate(r.created_at) }}</span>
                </li>
              </ul>
              <p v-else class="hint">暂无提现记录</p>
            </div>
          </details>
        </div>
      </section>

      <!-- ===== 算力值 + 当前套餐（含算力值账户 / 自动续费） ===== -->
      <section class="two-col lg">
        <!-- 算力值 -->
        <article class="card pad hover compute-card">
          <div class="head-row between">
            <div class="head-row">
              <span class="icon-sq primary"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg></span>
              <div>
                <h2 class="serif card-title">算力值</h2>
                <p class="card-sub">高级模型对话专用额度</p>
              </div>
            </div>
            <span v-if="highRateLocked" class="badge"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>高倍率已锁定</span>
          </div>
          <div class="stat-row">
            <div class="stat accent"><span>套餐额度</span><strong class="mono">{{ compute.quota }}</strong></div>
            <div class="stat"><span>永久算力</span><strong class="mono">{{ compute.permanent }}</strong></div>
          </div>
          <p class="tip"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>消费时先扣套餐额度再扣永久算力。</p>

          <!-- 最近任务消耗：跟随主卡片自适应，每条 = 用户问题 + 消耗算力 -->
          <div class="recent-box">
            <div class="recent-head">
              <span class="recent-title">最近任务消耗</span>
              <span class="recent-sum">近 {{ recentConsumes.length }} 次任务 · 共 <b>{{ formatNum(consumeTotal) }}</b> 算力</span>
            </div>
            <ul v-if="recentConsumes.length > 0" class="recent-list">
              <li v-for="r in recentConsumes" :key="r.id" :title="r.full">
                <div class="recent-info">
                  <p class="ellipsis">{{ r.name }}</p>
                  <span>{{ r.time }}</span>
                </div>
                <em class="mono">-{{ formatNum(r.cost) }}</em>
              </li>
            </ul>
            <p v-else class="recent-empty">暂无任务消耗记录</p>
          </div>
        </article>

        <!-- 当前套餐 × 算力值账户 × 自动续费（一体） -->
        <article class="card pad hover plan-card">
          <div class="head-row">
            <span class="icon-sq primary"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h12l4 6-10 13L2 9Z"/><path d="M11 3 8 9l4 13 4-13-3-6"/><path d="M2 9h20"/></svg></span>
            <div class="grow">
              <h2 class="serif card-title">当前套餐</h2>
              <p class="card-sub">{{ planInfo.name }}</p>
            </div>
            <span v-if="renewals.some((r) => r.status === 'active')" class="pill pill-soft">自动续费开启中</span>
          </div>
          <dl class="kv-list">
            <div class="kv">
              <dt>到期时间</dt>
              <dd class="mono"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 7.5V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/><path d="M18 14v4h4"/></svg>{{ planInfo.expire }}</dd>
            </div>
            <div class="kv">
              <dt>账户余额</dt>
              <dd class="mono accent"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>{{ currentCredit }} 算力</dd>
            </div>
          </dl>
          <!-- 算力值账户 -->
          <div class="stat-row compact">
            <div class="stat accent">
              <div class="stat-head"><span>累计获得</span><span class="round in" aria-hidden="true">+</span></div>
              <strong class="mono">{{ creditAccount.granted }}</strong>
            </div>
            <div class="stat">
              <div class="stat-head"><span>累计消耗</span><span class="round out" aria-hidden="true">−</span></div>
              <strong class="mono deep">{{ creditAccount.consumed }}</strong>
            </div>
          </div>

          <!-- 自动续费（并入套餐卡一体） -->
          <div class="renew-box">
            <div class="renew-box-head">
              <span class="renew-box-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>自动续费</span>
              <button v-if="renewals.length === 0" type="button" class="btn-ghost" @click="renewOpen = !renewOpen">
                {{ renewOpen ? '收起' : '开启续费' }}
              </button>
            </div>

            <ul v-if="renewals.length > 0" class="renew-list">
              <li v-for="r in renewals" :key="r.id" class="renew" :class="{ paused: r.status !== 'active' }">
                <div class="renew-head">
                  <div class="grow">
                    <p class="renew-name">{{ r.plan_name }}</p>
                    <p class="renew-meta">
                      <span v-if="r.status === 'active'">下次续费：{{ formatDate(r.next_renew_at) }}</span>
                      <span v-else>自动续费已暂停</span>
                      <span>已续费 {{ r.renew_count }} 次</span>
                    </p>
                  </div>
                  <span class="pill" :class="r.status === 'active' ? 'pill-soft' : 'pill-neutral'">{{ r.status === 'active' ? '开启中' : '已暂停' }}</span>
                </div>
                <div class="btn-row mini">
                  <button
                    v-if="r.status === 'active'"
                    type="button"
                    class="btn-ghost border"
                    :disabled="renewalLoadingId === r.id"
                    @click="handleRenewalAction(r, 'pause')"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="14" y="4" width="4" height="16" rx="1"/><rect x="6" y="4" width="4" height="16" rx="1"/></svg>
                    暂停
                  </button>
                  <button
                    v-else
                    type="button"
                    class="btn-ghost border"
                    :disabled="renewalLoadingId === r.id"
                    @click="handleRenewalAction(r, 'resume')"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 3 20 12 6 21 6 3"/></svg>
                    恢复
                  </button>
                  <button type="button" class="btn-ghost border" :disabled="renewalLoadingId === r.id" @click="handleRenewalAction(r, 'cancel')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>取消
                  </button>
                </div>
              </li>
            </ul>

            <template v-if="renewals.length === 0 && renewOpen">
              <p class="field-label">选择续费套餐（余额自动扣款）</p>
              <label v-for="p in renewablePlans" :key="p.id" class="radio-card row" :class="{ checked: renewPlanId === p.id }">
                <input type="radio" name="renew-plan" class="sr" :value="p.id" v-model="renewPlanId" />
                <span class="grow">{{ p.name }} · ¥{{ Number(p.price).toFixed(2) }}</span>
                <span class="radio-dot static"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span>
              </label>
              <p v-if="renewablePlans.length === 0" class="hint">暂无可续费套餐</p>
              <button type="button" class="btn-primary" :disabled="!renewPlanId || renewing" @click="handleEnableRenewal">
                {{ renewing ? '开启中…' : '确认开启自动续费' }}
              </button>
            </template>
            <p v-if="renewals.length === 0 && !renewOpen" class="hint">暂未开启自动续费，到期前需手动续费。</p>
          </div>
        </article>
      </section>

      <!-- ===== 分销中心（整张大卡） ===== -->
      <section class="card pad hover dist-card">
        <div class="head-row between">
          <div class="head-row">
            <span class="icon-sq soft"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 2 8 4.5v9L12 22l-8-4.5v-9L12 2z"/><path d="M12 22v-9"/><path d="M20 6.5 12 13 4 6.5"/></svg></span>
            <div>
              <h2 class="serif card-title">分销中心</h2>
              <p class="card-sub">邀请好友赚取佣金，下级越多收益越高</p>
            </div>
          </div>
          <span v-if="highRateLocked" class="badge"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>高倍率已锁定</span>
        </div>

        <dl class="dist-summary">
          <div class="dist-rate">
            <dt>我的佣金比例</dt>
            <dd class="mono">{{ commissionRate }}%</dd>
          </div>
          <div class="dist-sub-count">
            <dt>累计下级</dt>
            <dd class="mono">{{ subordinateCount }}</dd>
          </div>
          <div class="qr-box">
            <span>分享二维码</span>
            <img v-if="qrcodeUrl" :src="qrcodeUrl" class="qr-img" alt="referral qrcode" />
            <span v-else class="qr"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="5" height="5" x="3" y="3" rx="1"/><rect width="5" height="5" x="16" y="3" rx="1"/><rect width="5" height="5" x="3" y="16" rx="1"/><path d="M21 16h-3a2 2 0 0 0-2 2v3"/><path d="M21 21v.01"/><path d="M12 7v3a2 2 0 0 1-2 2H7"/><path d="M3 12h.01"/><path d="M12 3h.01"/><path d="M12 16v.01"/><path d="M16 12h1"/><path d="M21 12v.01"/><path d="M12 21v-1"/></svg></span>
          </div>
        </dl>

        <div class="code-pair">
          <div class="code-block">
            <label>我的推荐码</label>
            <div class="code-row">
              <input :value="distribution?.referral_code || '-'" readonly class="input mono" />
              <button type="button" class="btn-ghost" @click="handleCopy(distribution?.referral_code || '')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>复制</button>
            </div>
          </div>
          <div class="code-block">
            <label>分享链接</label>
            <div class="code-row">
              <input :value="shareFallback || '暂无分享链接'" readonly class="input mono muted" />
              <button type="button" class="btn-ghost" @click="handleCopy(shareFallback)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>复制</button>
            </div>
          </div>
        </div>

        <div class="dist-body">
          <!-- 下级列表 -->
          <section class="dist-block">
            <div class="dist-block-head">
              <p class="list-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>下级列表 <span class="count">{{ subordinateCount }}</span></p>
              <span class="dist-block-meta">共 {{ subTotal }} 位</span>
            </div>
            <div class="table-wrap">
              <table v-if="subordinates.length > 0" class="table dist-table">
                <thead>
                  <tr><th>用户</th><th>绑定时间</th></tr>
                </thead>
                <tbody>
                  <tr v-for="s in subordinates" :key="s.id">
                    <td>
                      <p class="cell-name">{{ s.name }}</p>
                      <p v-if="s.email" class="cell-sub">{{ s.email }}</p>
                    </td>
                    <td class="muted">{{ formatTime(s.bound_at) }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-else class="hint pad-hint">暂无下级，分享推荐码邀请好友加入</p>
            </div>
            <div v-if="subTotal > SUB_PAGE_SIZE" class="pager">
              <button type="button" class="btn-ghost" :disabled="subPage <= 1 || subLoading" @click="loadSubordinates(subPage - 1)">上一页</button>
              <span class="pager-info">{{ subPage }} / {{ Math.ceil(subTotal / SUB_PAGE_SIZE) }}</span>
              <button type="button" class="btn-ghost" :disabled="subPage >= Math.ceil(subTotal / SUB_PAGE_SIZE) || subLoading" @click="loadSubordinates(subPage + 1)">下一页</button>
            </div>
          </section>

          <!-- 佣金记录 -->
          <section class="dist-block">
            <div class="dist-block-head">
              <p class="list-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/><path d="M12 17.5v-11"/></svg>佣金记录</p>
              <span class="dist-block-meta">共 {{ commissionTotal }} 笔</span>
            </div>
            <div class="table-wrap">
              <table v-if="commissions.length > 0" class="table dist-table">
                <thead>
                  <tr><th>来源</th><th>比例</th><th>时间</th><th class="right">金额</th></tr>
                </thead>
                <tbody>
                  <tr v-for="c in commissions" :key="c.id">
                    <td>{{ commissionSource(c) }}</td>
                    <td class="muted">{{ c.rate != null ? `${c.rate}%` : '-' }}</td>
                    <td class="muted">{{ formatTime(c.created_at) }}</td>
                    <td class="right mono accent">+¥{{ formatMoney(c.amount) }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-else class="hint pad-hint">暂无佣金记录</p>
            </div>
            <div v-if="commissionTotal > COMMISSION_PAGE_SIZE" class="pager">
              <button type="button" class="btn-ghost" :disabled="commissionPage <= 1 || commissionLoading" @click="loadCommissions(commissionPage - 1)">上一页</button>
              <span class="pager-info">{{ commissionPage }} / {{ Math.ceil(commissionTotal / COMMISSION_PAGE_SIZE) }}</span>
              <button type="button" class="btn-ghost" :disabled="commissionPage >= Math.ceil(commissionTotal / COMMISSION_PAGE_SIZE) || commissionLoading" @click="loadCommissions(commissionPage + 1)">下一页</button>
            </div>
          </section>
        </div>
      </section>

      <!-- ===== 我的订单 ===== -->
      <section class="card">
        <div class="head-only">
          <h2 class="serif card-title">我的订单</h2>
          <p class="card-sub">套餐与充值订单记录</p>
        </div>
        <div class="table-wrap">
          <table class="table orders">
            <thead>
              <tr><th>套餐</th><th>金额</th><th>单号</th><th>支付方式</th><th>状态</th><th>时间</th><th class="right">操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="o in orderRows" :key="o.no">
                <td>{{ o.plan }}</td>
                <td class="mono">{{ o.amount }}</td>
                <td class="mono muted small">{{ o.no }}</td>
                <td class="muted">{{ o.pay }}</td>
                <td><span class="pill" :class="orderStatusClass(o.raw.status)">{{ o.status }}</span></td>
                <td class="muted">{{ o.time }}</td>
                <td class="right">
                  <button v-if="o.raw.status === 'paid'" type="button" class="btn-ghost" :disabled="orderActionLoading === o.no" @click="openRefundModal(o.raw)">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>申请退款
                  </button>
                  <button v-else-if="o.raw.status === 'pending'" type="button" class="btn-ghost" :disabled="orderActionLoading === o.no" @click="handleCancelOrder(o.raw)">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/></svg>取消订单
                  </button>
                  <span v-else class="muted small">已完成</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ===== 兑换记录表 ===== -->
      <section class="card">
        <div class="head-only">
          <h2 class="serif card-title">兑换记录</h2>
          <p class="card-sub">卡密兑换历史与算力到账明细</p>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr><th>卡密</th><th>套餐</th><th>兑换时间</th><th>有效期</th><th class="right">获得算力</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in redeemRows" :key="r.code">
                <td class="mono small">{{ r.code }}</td>
                <td>{{ r.plan }}</td>
                <td class="muted">{{ r.time }}</td>
                <td class="muted">{{ r.expire }}</td>
                <td class="right mono accent">{{ r.credit }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ===== 算力流水表 ===== -->
      <section class="card">
        <div class="head-only">
          <h2 class="serif card-title">算力流水</h2>
          <p class="card-sub">消费扣减与充值到账明细（仅显示算力值）</p>
        </div>
        <div class="table-wrap">
          <table class="table credit-flow-table">
            <thead>
              <tr><th>说明</th><th>类型</th><th>时间</th><th class="right">算力值</th></tr>
            </thead>
            <tbody>
              <tr v-for="f in creditFlows" :key="f.time + f.desc">
                <td class="flow-desc" :title="f.desc">{{ f.desc }}</td>
                <td><span class="pill" :class="f.positive ? 'pill-soft' : 'pill-muted'">{{ f.type }}</span></td>
                <td class="muted nowrap">{{ f.time }}</td>
                <td class="right mono" :class="f.positive ? 'accent' : 'muted'">{{ f.amount }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ===== 页脚 ===== -->
      <footer class="page-foot">
        <p>钰心AI © 2026 · 保留所有权利</p>
        <div><a href="#">隐私政策</a><a href="#">服务条款</a></div>
      </footer>
    </div>

    <!-- 退款申请弹窗 -->
    <a-modal
      :visible="refundModal !== null"
      :title="'申请退款'"
      :confirm-loading="orderActionLoading === 'refund'"
      :ok-text="'提交退款申请'"
      :cancel-text="'取消'"
      @ok="submitRefund"
      @cancel="refundModal = null"
    >
      <div class="refund-modal">
        <p v-if="refundModal" class="muted small">订单号：{{ refundModal.order_no }} · ¥{{ formatMoney(refundModal.amount) }}</p>
        <textarea
          v-model="refundReason"
          rows="3"
          class="input"
          placeholder="请填写退款原因（不超过 1024 字）"
        />
      </div>
    </a-modal>
  </div>
</template>

<style scoped>
/* ---------- 基础与容器 ---------- */
.mock-page {
  height: 100%;
  overflow-y: auto;
  padding: 20px 16px;
  background:
    radial-gradient(circle at 90% 2%, rgba(233, 30, 99, 0.06), transparent 28%),
    radial-gradient(circle at 8% 26%, rgba(255, 158, 197, 0.12), transparent 30%),
    var(--aicss-bg);
  color: var(--aicss-text);
  font-family: var(--aicss-font-sans, inherit);
}

.mock-page > div {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.refund-modal {
  display: grid;
  gap: 10px;
}
.refund-modal textarea {
  width: 100%;
  resize: vertical;
}

.serif {
  font-family: var(--aicss-font-serif, Georgia, 'Songti SC', serif);
  letter-spacing: -0.02em;
}
.mono {
  font-family: 'SFMono-Regular', Consolas, Menlo, monospace;
  font-variant-numeric: tabular-nums;
}
.grow { flex: 1; min-width: 0; }
.accent { color: var(--aicss-accent-text) !important; }
.muted { color: var(--aicss-muted) !important; }
.small { font-size: 12px !important; }
.block { width: 100%; }

/* ---------- 图标通用 ---------- */
.icon-sq {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: var(--aicss-radius);
}
.icon-sq svg, .row-ico, .entry-summary .icon-sq svg { width: 20px; height: 20px; }
.primary { background: var(--aicss-accent); color: #fff; box-shadow: var(--aicss-shadow-card); }
.soft { background: var(--aicss-surface-2); color: var(--aicss-accent-text); }
svg { flex-shrink: 0; }

/* ---------- Hero ---------- */
.hero {
  overflow: hidden;
  border-radius: var(--aicss-radius-lg);
  background: linear-gradient(135deg, var(--aicss-accent) 0%, #ff5c8d 56%, #ff9ec5 100%);
  box-shadow: var(--aicss-shadow-elevated);
  color: #fff;
}
.hero-inner {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 26px 26px;
}
.kicker {
  margin: 0;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.82);
}
.hero-title { margin: 8px 0 0; font-size: 30px; line-height: 1.15; color: #fff; }
.hero-desc { margin: 10px 0 0; max-width: 26rem; font-size: 14px; line-height: 1.65; color: rgba(255, 255, 255, 0.86); }
.credit-chip {
  align-self: flex-start;
  min-width: 150px;
  padding: 14px 20px;
  text-align: center;
  border-radius: var(--aicss-radius);
  border: 1px solid rgba(255, 255, 255, 0.28);
  background: rgba(255, 255, 255, 0.16);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
.credit-chip-label { margin: 0; font-size: 12px; color: rgba(255, 255, 255, 0.85); }
.credit-chip-value { margin: 4px 0 0; font-size: 28px; font-weight: 650; color: #fff; }

/* ---------- 卡片 ---------- */
.card {
  border-radius: var(--aicss-radius-lg);
  border: 1px solid var(--aicss-border);
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
}
.card.pad { padding: 22px; }
.card.hover { transition: box-shadow 0.2s ease; }
.card.hover:hover { box-shadow: var(--aicss-shadow-elevated); }

.head-row { display: flex; align-items: center; gap: 12px; }
.head-row.between { justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.card-title { margin: 0; font-size: 19px; color: var(--aicss-text); }
.card-sub { margin: 4px 0 0; font-size: 12px; color: var(--aicss-muted); }
.head-only { padding: 22px 22px 12px; }

/* ---------- 5 指标 ---------- */
.metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin: 18px 0 0;
}
.metric {
  min-width: 0;
  padding: 14px 16px;
  border-radius: var(--aicss-radius);
  border: 1px solid var(--aicss-border);
  background: var(--aicss-bg-subtle);
  transition: box-shadow 0.18s ease;
}
.metric:hover { box-shadow: var(--aicss-shadow-card); }
.metric.hl {
  border-color: color-mix(in srgb, var(--aicss-accent) 24%, var(--aicss-border));
  background: var(--aicss-accent-soft);
}
.metric dt {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--aicss-muted);
}
.metric dd {
  margin: 8px 0 0;
  font-size: 20px;
  font-weight: 650;
  color: var(--aicss-text);
  line-height: 1.25;
  overflow-wrap: anywhere;
}
.metric.hl dd { color: var(--aicss-accent-text); }

/* ---------- 折叠面板 ---------- */
.panel-stack { display: grid; gap: 14px; margin-top: 16px; grid-template-columns: 1fr; }
.entry {
  border-radius: var(--aicss-radius);
  border: 1px solid var(--aicss-border);
  background: var(--aicss-surface);
  transition: border-color 0.2s ease;
}
.entry[open] {
  border-color: color-mix(in srgb, var(--aicss-accent) 55%, var(--aicss-border));
  background: color-mix(in srgb, var(--aicss-bg-subtle) 40%, var(--aicss-surface));
}
.entry-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 18px;
  cursor: pointer;
  list-style: none;
}
.entry-summary::-webkit-details-marker { display: none; }
.entry-copy { flex: 1; min-width: 0; }
.entry-name { display: block; font-size: 14px; font-weight: 500; color: var(--aicss-text); }
.entry-desc { display: block; margin-top: 2px; font-size: 12px; color: var(--aicss-muted); }
.chev { width: 16px; height: 16px; color: var(--aicss-muted); transition: transform 0.2s ease; }
.chev.open { transform: rotate(180deg); }
.entry-body { padding: 0 18px 18px; border-top: 1px solid var(--aicss-border); }
.entry-body .field-label:first-child { padding-top: 16px; }

.field-label { display: block; margin: 14px 0 0; font-size: 12px; font-weight: 500; color: var(--aicss-text); }
.field-label.mt { margin-top: 16px; }
.field-row { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; }
.input {
  min-width: 0;
  padding: 10px 14px;
  font-size: 14px;
  color: var(--aicss-text);
  background: var(--aicss-surface);
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  outline: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}
.input:focus { border-color: var(--aicss-accent); box-shadow: 0 0 0 3px var(--aicss-accent-soft); }
.input::placeholder { color: var(--aicss-muted); }
.input.mono { font-family: 'SFMono-Regular', Consolas, Menlo, monospace; font-size: 13px; }
.input.muted { background: var(--aicss-bg-subtle); color: var(--aicss-muted); }
.hint { margin: 10px 0 0; font-size: 12px; line-height: 1.6; color: var(--aicss-muted); }
.list-label { margin: 16px 0 0; font-size: 13px; font-weight: 500; color: var(--aicss-text); }

/* ---------- 按钮 ---------- */
.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 18px;
  font-size: 14px;
  font-weight: 500;
  color: #fff;
  background: var(--aicss-accent);
  border: none;
  border-radius: var(--aicss-radius);
  box-shadow: var(--aicss-shadow-card);
  cursor: pointer;
  transition: opacity 0.18s ease;
}
.btn-primary:hover { opacity: 0.9; }
.btn-primary svg { width: 16px; height: 16px; }
.btn-primary.block { width: 100%; }
.btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  font-size: 13px;
  font-weight: 500;
  color: var(--aicss-text);
  background: transparent;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  cursor: pointer;
  transition: background 0.18s ease;
}
.btn-ghost:hover { background: var(--aicss-bg-subtle); }
.btn-ghost.border { background: var(--aicss-surface); }
.btn-ghost svg { width: 14px; height: 14px; }
.btn-row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
.btn-row.mini { margin-top: 14px; }

/* ---------- radio 卡片 ---------- */
.radio-grid { display: grid; gap: 10px; margin-top: 10px; }
.radio-grid.cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.radio-grid.cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.radio-card {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 14px;
  border-radius: var(--aicss-radius);
  border: 1px solid var(--aicss-border);
  background: var(--aicss-surface);
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease;
}
.radio-card:hover { border-color: var(--aicss-accent); background: color-mix(in srgb, var(--aicss-bg-subtle) 55%, var(--aicss-surface)); }
.radio-card.checked { border-color: var(--aicss-accent); }
.radio-card.row { flex-direction: row; align-items: center; gap: 8px; padding: 11px 13px; }
.radio-money, .radio-name { font-size: 15px; font-weight: 600; color: var(--aicss-text); }
.radio-bonus { margin-top: 4px; font-size: 12px; color: var(--aicss-muted); }
.radio-bonus.accent { color: var(--aicss-accent-text); }
.row-ico { width: 18px; height: 18px; color: var(--aicss-accent-text); }
.sr { position: absolute; opacity: 0; width: 0; height: 0; }
.radio-dot {
  position: absolute;
  top: 10px;
  right: 10px;
  display: none;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 999px;
  background: var(--aicss-accent);
  color: #fff;
}
.radio-dot.static { display: flex; position: static; flex-shrink: 0; }
.radio-card.checked .radio-dot { display: flex; }
.radio-card.checked .radio-dot.static { display: flex; }
.radio-dot svg { width: 10px; height: 10px; }
.check { display: flex; align-items: center; gap: 8px; margin-top: 14px; font-size: 14px; color: var(--aicss-text); }
.check input { accent-color: var(--aicss-accent); }

/* ---------- 徽标 / 药丸 ---------- */
.pill {
  display: inline-flex;
  align-items: center;
  padding: 3px 11px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 999px;
  white-space: nowrap;
}
.pill-soft { background: var(--aicss-accent-soft); color: var(--aicss-accent-text); }
.pill-neutral { background: var(--aicss-bg-subtle); color: var(--aicss-muted); }
.pill-muted { background: var(--aicss-surface-2); color: var(--aicss-text-2); }
.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  font-size: 12px;
  border-radius: 999px;
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
}
.badge svg { width: 13px; height: 13px; }

/* ---------- 双栏 ---------- */
.two-col { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; }
.two-col.lg, .two-col.md { grid-template-columns: minmax(0, 1fr); }
.two-col > * { min-width: 0; }

/* 统计卡 */
.stat-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 18px; }
.stat {
  padding: 15px;
  border-radius: var(--aicss-radius);
  border: 1px solid var(--aicss-border);
  background: var(--aicss-bg-subtle);
}
.stat.accent { border-color: color-mix(in srgb, var(--aicss-accent) 24%, var(--aicss-border)); background: var(--aicss-accent-soft); }
.stat-head { display: flex; align-items: flex-start; justify-content: space-between; }
.stat span { font-size: 12px; color: var(--aicss-muted); }
.stat strong { display: block; margin-top: 10px; font-size: 24px; font-weight: 650; letter-spacing: -0.02em; color: var(--aicss-text); }
.stat.accent strong { color: var(--aicss-accent-text); }
.stat strong.deep { color: var(--aicss-text-2); }
.round {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  font-size: 16px;
  font-weight: 700;
  line-height: 1;
}
.round.in { background: var(--aicss-accent-soft); color: var(--aicss-accent-text); border: 1px solid color-mix(in srgb, var(--aicss-accent) 32%, transparent); }
.round.out { background: color-mix(in srgb, var(--aicss-accent) 10%, var(--aicss-bg-subtle)); color: var(--aicss-muted); border: 1px solid var(--aicss-border); }
.tip { display: flex; align-items: flex-start; gap: 6px; margin: 14px 0 0; font-size: 12px; line-height: 1.6; color: var(--aicss-muted); }
.tip svg { width: 14px; height: 14px; color: var(--aicss-accent-text); flex-shrink: 0; }

/* 最近任务消耗 */
.recent-box {
  margin-top: 16px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-bg-subtle);
  overflow: hidden;
}
.recent-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 11px 14px;
  border-bottom: 1px solid var(--aicss-border);
}
.recent-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--aicss-text);
}
.recent-sum {
  font-size: 11px;
  color: var(--aicss-muted);
}
.recent-sum b {
  font-weight: 650;
  color: var(--aicss-accent-text);
}
.recent-empty {
  margin: 0;
  padding: 14px;
  text-align: center;
  font-size: 12px;
  color: var(--aicss-muted);
}
.recent-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.recent-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 14px;
  border-bottom: 1px solid var(--aicss-border);
}
.recent-list li:last-child { border-bottom: none; }
.recent-info { min-width: 0; }
.recent-info p {
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--aicss-text);
}
.recent-info span { display: block; margin-top: 2px; font-size: 11px; color: var(--aicss-muted); }
.recent-list em {
  flex-shrink: 0;
  font-style: normal;
  font-size: 13px;
  font-weight: 600;
  color: var(--aicss-accent-text);
}

/* 分销补充 */
.hint.danger {
  color: var(--aicss-danger, #f53f3f);
}
.hint + .btn-primary,
.btn-primary + .hint {
  margin-top: 12px;
}

/* 分销 */
.dist-summary {
  display: flex;
  align-items: stretch;
  gap: 14px;
  margin: 18px 0 0;
  padding: 14px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-bg-subtle);
}
.dist-rate,
.dist-sub-count {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 4px 10px;
}
.dist-summary dt { font-size: 12px; color: var(--aicss-muted); }
.dist-summary dd { margin: 6px 0 0; font-size: 22px; font-weight: 650; color: var(--aicss-accent-text); }
.qr-box { text-align: center; min-width: 132px; padding: 6px 10px; }
.qr-box > span { font-size: 12px; color: var(--aicss-muted); }
.qr-img {
  display: block;
  width: 60px;
  height: 60px;
  margin: 6px auto 0;
  border-radius: var(--aicss-radius-sm);
  object-fit: contain;
}
.qr {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  margin: 8px auto 0;
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-accent);
  color: #fff;
}
.qr svg { width: 28px; height: 28px; }
.code-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 14px; }
.code-block label { display: block; font-size: 12px; color: var(--aicss-muted); }
.code-row { display: flex; flex-direction: column; gap: 8px; margin-top: 6px; }
.list-title { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 13px; font-weight: 600; color: var(--aicss-text); }
.list-title svg { width: 14px; height: 14px; color: var(--aicss-accent-text); }
.list-title .count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  margin-left: 2px;
  border-radius: 999px;
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
  font-size: 11px;
  font-weight: 600;
}

/* 分销大卡正文：下级 / 佣金 全宽分块 */
.dist-body { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 18px; }
.dist-block {
  min-width: 0;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-surface);
  overflow: hidden;
}
.dist-block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--aicss-border);
  background: var(--aicss-bg-subtle);
}
.dist-block-meta { font-size: 12px; color: var(--aicss-muted); }
.dist-table { min-width: 0; }
.dist-table th { padding: 10px 16px; }
.dist-table td { padding: 11px 16px; }
.cell-name { margin: 0; font-weight: 500; color: var(--aicss-text); }
.cell-sub { margin: 2px 0 0; font-size: 12px; color: var(--aicss-muted); }
.pad-hint { padding: 0 16px 16px; }
.pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 16px;
  border-top: 1px solid var(--aicss-border);
}
.pager-info { font-size: 12px; color: var(--aicss-muted); font-variant-numeric: tabular-nums; }

/* 当前套餐一体卡 */
.plan-card { display: flex; flex-direction: column; }
.stat-row.compact { margin-top: 12px; }
.stat-row.compact .stat { padding: 11px 13px; }
.stat-row.compact .stat strong { margin-top: 6px; font-size: 19px; }
.renew-box {
  display: flex;
  flex-direction: column;
  flex: 1;
  margin-top: 16px;
  padding: 14px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius);
  background: var(--aicss-bg-subtle);
}
.renew-box-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.renew-box-title {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 600;
  color: var(--aicss-text);
}
.renew-box-title svg { width: 15px; height: 15px; color: var(--aicss-accent-text); }
.renew-box .renew-list { margin-top: 10px; gap: 8px; }
.renew-box .renew { padding: 12px; }
.renew-box .renew-head { gap: 8px; }
.renew-box .btn-row.mini { margin-top: 10px; }
.renew-box .field-label { margin-top: 10px; }
.renew-box > .radio-card,
.renew-box > label.radio-card,
.renew-box > .btn-primary,
.renew-box > .hint { margin-top: 10px; }
.renew-box .radio-card { margin-top: 10px; }
.renew-box .btn-primary { margin-top: 10px; }

/* kv 行 */
.kv-list { margin: 16px 0 0; }
.kv { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 11px 0; border-bottom: 1px solid var(--aicss-border); }
.kv:last-child { border-bottom: none; }
.kv dt { font-size: 13px; color: var(--aicss-muted); }
.kv dd { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 13px; color: var(--aicss-text); }
.kv dd svg { width: 15px; height: 15px; color: var(--aicss-accent-text); }

/* 任务问题单行省略（hover title 查看全文） */
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.recent-list li {
  position: relative;
  cursor: default;
}

/* 提现记录 */
.withdraw-list { margin: 6px 0 0; padding: 0; list-style: none; display: grid; gap: 8px; }
.withdraw-list li { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 14px; border: 1px solid var(--aicss-border); border-radius: var(--aicss-radius); background: var(--aicss-bg-subtle); }
.withdraw-list .date { font-size: 12px; color: var(--aicss-muted); }

/* ---------- 表格 ---------- */
.table-wrap { overflow-x: auto; }
.table { width: 100%; min-width: 640px; border-collapse: collapse; text-align: left; font-size: 13px; }
.table.orders { min-width: 880px; }
.table th { padding: 11px 22px; font-weight: 500; font-size: 12px; color: var(--aicss-muted); background: var(--aicss-bg-subtle); border-bottom: 1px solid var(--aicss-border); white-space: nowrap; }
.table td { padding: 13px 22px; color: var(--aicss-text); border-bottom: 1px solid var(--aicss-border); vertical-align: middle; }
.table tbody tr:last-child td { border-bottom: none; }
.table tbody tr { transition: background 0.15s ease; }
.table tbody tr:hover { background: var(--aicss-bg-subtle); }
.table .right { text-align: right; }
.table td.mono { font-size: 13px; }
.table td.small { font-size: 12px; }
.credit-flow-table { min-width: 720px; }
.credit-flow-table .flow-desc {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nowrap { white-space: nowrap; }

/* 续费列表 */
.renew-list { margin: 18px 0 0; padding: 0; list-style: none; display: grid; gap: 12px; }
.renew { padding: 18px; border: 1px solid var(--aicss-border); border-radius: var(--aicss-radius); background: var(--aicss-bg-subtle); }
.renew.paused { background: var(--aicss-surface); }
.renew-head { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 12px; }
.renew-name { margin: 0; font-size: 14px; font-weight: 500; color: var(--aicss-text); }
.renew-meta { display: flex; flex-wrap: wrap; gap: 12px; margin: 6px 0 0; font-size: 12px; color: var(--aicss-muted); }

/* 页脚 */
.page-foot {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 18px 4px 6px;
  border-top: 1px solid var(--aicss-border);
  font-size: 12px;
  color: var(--aicss-muted);
}
.page-foot p { margin: 0; }
.page-foot div { display: flex; gap: 18px; }
.page-foot a { color: var(--aicss-muted); text-decoration: none; transition: color 0.15s ease; }
.page-foot a:hover { color: var(--aicss-accent-text); }

/* ---------- 响应式 ---------- */
@media (min-width: 640px) {
  .field-row { flex-direction: row; }
  .code-row { flex-direction: row; }
  .mock-page { padding: 24px 24px; }
}
@media (min-width: 1024px) {
  .two-col.lg { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .compute-card,
  .plan-card { min-width: 0; }
  .hero-inner { flex-direction: row; align-items: center; justify-content: space-between; padding: 34px 38px; }
  .credit-chip { min-width: 170px; }
  .page-foot { flex-direction: row; }
  .metrics { grid-template-columns: repeat(5, minmax(0, 1fr)); }
}
/* 平板：5 指标降 3 列，避免长数字挤压溢出 */
@media (min-width: 641px) and (max-width: 1023px) {
  .metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .radio-grid.cols-3 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .radio-grid.cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .code-pair { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metric:nth-child(5) { grid-column: 1 / -1; }
  .radio-grid.cols-3 { grid-template-columns: 1fr; }
  .radio-grid.cols-2 { grid-template-columns: 1fr; }
  .dist-body { grid-template-columns: 1fr; }
  .code-pair { grid-template-columns: 1fr; }
  .dist-summary { flex-wrap: wrap; }
  .panel-stack { grid-template-columns: 1fr; }

  /* 算力值 / 当前套餐 移动适配 */
  .compute-card .head-row.between,
  .plan-card .head-row,
  .dist-card > .head-row.between { flex-wrap: wrap; }
  .compute-card .stat-row,
  .plan-card .stat-row.compact { grid-template-columns: 1fr 1fr; }
  .compute-card .stat strong,
  .plan-card .stat-row.compact .stat strong {
    font-size: 18px;
    overflow-wrap: anywhere;
  }
  .dist-table { min-width: 460px; }
  .kv-list { margin-top: 12px; }
  .kv { align-items: flex-start; gap: 8px; padding: 10px 0; }
  .kv dd { flex: 1; justify-content: flex-end; text-align: right; min-width: 0; overflow-wrap: anywhere; }
  .plan-card .pill { margin-left: auto; }
  .recent-box { margin-top: 12px; }
  .recent-head { align-items: flex-start; flex-direction: column; gap: 4px; }
  .recent-sum { line-height: 1.4; }
  .renew-box { padding: 12px; }
  .renew-box .renew { padding: 10px; }
  .dist-summary { padding: 10px; gap: 10px; }
  .dist-summary dd { font-size: 19px; }
  .qr-box { min-width: 0; flex: 0 0 auto; }
}
@media (max-width: 380px) {
  .metrics { grid-template-columns: 1fr; }
  .metric:nth-child(n) { grid-column: auto; }
  .qr-box { min-width: 0; }
  .compute-card .stat-row,
  .plan-card .stat-row.compact { grid-template-columns: 1fr; }
  .plan-card .head-row { gap: 8px; }
}
</style>
