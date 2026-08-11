<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { getMembershipSummary, getRedeemRecords, redeemCode } from '@/services/billing'
import { type MembershipSummary, type RedeemRecord } from '@/models/billing'
import { getErrorMessage } from '@/utils/error'

const loading = ref(false)
const redeeming = ref(false)
const code = ref('')
const summary = ref<MembershipSummary | null>(null)
const redeemRecords = ref<RedeemRecord[]>([])

const formatTime = (value: number | null) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const loadSummary = async () => {
  loading.value = true
  try {
    const [summaryResult, recordsResult] = await Promise.all([getMembershipSummary(), getRedeemRecords()])
    summary.value = summaryResult
    redeemRecords.value = recordsResult.list
  } catch (error) {
    Message.error(getErrorMessage(error, '加载会员信息失败'))
  } finally {
    loading.value = false
  }
}

const handleRedeem = async () => {
  redeeming.value = true
  try {
    await redeemCode(code.value)
    Message.success('兑换成功')
    code.value = ''
    await loadSummary()
  } catch (error) {
    Message.error(getErrorMessage(error, '兑换失败'))
  } finally {
    redeeming.value = false
  }
}

onMounted(loadSummary)
</script>

<template>
  <section class="membership-page" :aria-busy="loading">
    <header class="hero-card">
      <div>
        <p class="kicker">Membership</p>
        <h2>我的会员</h2>
        <p>兑换卡密，查看套餐有效期和算力值余额。</p>
      </div>
      <div class="balance-card">
        <span>当前算力值</span>
        <strong>{{ summary?.credit_account?.balance ?? 0 }}</strong>
      </div>
    </header>

    <section class="redeem-card">
      <a-input v-model="code" placeholder="输入卡密" />
      <a-button type="primary" :loading="redeeming" @click="handleRedeem">兑换</a-button>
    </section>

    <section class="content-grid">
      <article class="panel">
        <h3>当前套餐</h3>
        <strong>{{ summary?.membership?.plan?.name || '暂无会员' }}</strong>
        <p>到期时间：{{ formatTime(summary?.membership?.expires_at ?? null) }}</p>
      </article>
      <article class="panel">
        <h3>算力值账户</h3>
        <p>累计获得：{{ summary?.credit_account?.total_granted ?? 0 }}</p>
        <p>累计消耗：{{ summary?.credit_account?.total_consumed ?? 0 }}</p>
      </article>
    </section>

    <section class="panel">
      <h3>兑换记录</h3>
      <article v-for="record in redeemRecords" :key="record.id" class="tx-row">
        <div>
          <strong>{{ record.code_mask }}</strong>
          <p>{{ record.plan?.name || '未知套餐' }} · 兑换时间：{{ formatTime(record.redeemed_at) }}</p>
          <p>会员有效期：{{ formatTime(record.membership_expires_at) }}</p>
        </div>
        <span>+{{ record.grant_token_credits }}</span>
      </article>
    </section>

    <section class="panel">
      <h3>最近算力值流水</h3>
      <article v-for="transaction in summary?.recent_transactions || []" :key="transaction.id" class="tx-row">
        <div>
          <strong>{{ transaction.description }}</strong>
          <p>{{ transaction.transaction_type }} · {{ formatTime(transaction.created_at) }}</p>
        </div>
        <span>{{ transaction.amount }}</span>
      </article>
    </section>
  </section>
</template>

<style scoped>
.membership-page {
  height: 100%;
  overflow-y: auto;
  display: grid;
  gap: 16px;
  padding: 24px;
  background: var(--aicss-bg-subtle);
  color: var(--aicss-text);
}

.hero-card,
.panel,
.redeem-card {
  padding: 22px;
  border-radius: var(--aicss-radius-lg);
  border: 1px solid var(--aicss-border);
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
}

.hero-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--aicss-accent) 12%, var(--aicss-surface)), var(--aicss-surface) 68%),
    var(--aicss-surface);
  color: var(--aicss-text);
}

.kicker {
  margin: 0 0 8px;
  color: var(--aicss-accent-text);
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

h2,
h3,
p {
  margin: 0;
}

h2 {
  font-size: 28px;
  color: var(--aicss-text);
}

.hero-card p:not(.kicker) {
  margin-top: 8px;
  color: var(--aicss-muted);
}

.balance-card {
  display: grid;
  align-content: center;
  min-width: 180px;
  padding: 18px 20px;
  border-radius: var(--aicss-radius);
  border: 1px solid color-mix(in srgb, var(--aicss-accent) 22%, var(--aicss-border));
  background: var(--aicss-accent-soft);
  color: var(--aicss-text);
}

.balance-card span {
  color: var(--aicss-muted);
}

.balance-card strong {
  margin-top: 8px;
  font-size: 30px;
  color: var(--aicss-accent-text);
}

.redeem-card {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) auto;
  gap: 12px;
}

.content-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.panel strong {
  display: block;
  margin-top: 12px;
  font-size: 22px;
  color: var(--aicss-text);
}

.panel p,
.tx-row p {
  margin-top: 6px;
  color: var(--aicss-muted);
}

.tx-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 0;
  border-top: 1px solid var(--aicss-border);
}

.tx-row strong {
  color: var(--aicss-text);
}

.tx-row > span {
  color: var(--aicss-success);
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 640px) {
  .membership-page {
    padding: 16px;
  }

  .hero-card {
    flex-direction: column;
    align-items: stretch;
  }

  .balance-card {
    min-width: 0;
  }

  .content-grid {
    grid-template-columns: 1fr;
  }

  .redeem-card {
    grid-template-columns: 1fr;
  }
}
</style>
