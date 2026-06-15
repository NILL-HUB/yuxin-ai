<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useAdminStore } from '@/stores/admin'
import {
  createPlan,
  disableRedeemCode,
  disableRedeemCodeBatch,
  generateRedeemCodes,
  listPlans,
  listRedeemCodeBatches,
  listRedeemCodes,
  setPlanStatus,
} from '@/services/admin-billing'
import { type GeneratedRedeemCode, type Plan, type RedeemCodeBatch, type RedeemCodeRecord } from '@/models/billing'
import { getErrorMessage } from '@/utils/error'

const loading = ref(false)
const adminStore = useAdminStore()
const canUpdatePlan = computed(() => adminStore.hasPermission('plan:update'))
const canUpdateRedeemCode = computed(() => adminStore.hasPermission('redeem_code:update'))

const actionLoading = ref(false)
const plans = ref<Plan[]>([])
const batches = ref<RedeemCodeBatch[]>([])
const codes = ref<RedeemCodeRecord[]>([])
const generatedCodes = ref<GeneratedRedeemCode[]>([])
const generatedBatchName = ref('')

const planForm = ref({ code: '', name: '', duration_days: 30, grant_token_credits: 100, price: '0.00', status: 'active' as const })
const codeForm = ref({ name: '', quantity: 1 })
const codeFilter = ref({ batch_id: '', status: '' as '' | 'unused' | 'used' | 'disabled' | 'expired', code_keyword: '', current_page: 1, page_size: 20 })

const loadBilling = async () => {
  loading.value = true
  try {
    const [planResult, batchResult, codeResult] = await Promise.all([
      listPlans({ keyword: '', status: '', current_page: 1, page_size: 20 }),
      listRedeemCodeBatches({ keyword: '', current_page: 1, page_size: 20 }),
      listRedeemCodes(codeFilter.value),
    ])
    plans.value = planResult.list
    batches.value = batchResult.list
    codes.value = codeResult.list
  } catch (error) {
    Message.error(getErrorMessage(error, '加载套餐卡密失败'))
  } finally {
    loading.value = false
  }
}

const handleCreatePlan = async () => {
  actionLoading.value = true
  try {
    await createPlan({
      ...planForm.value,
      sort_order: 0,
      entitlements: [{ feature_key: 'max_agents', feature_value: '10', value_type: 'number' }],
    })
    Message.success('套餐已创建')
    await loadBilling()
  } catch (error) {
    Message.error(getErrorMessage(error, '创建套餐失败'))
  } finally {
    actionLoading.value = false
  }
}

const handleTogglePlan = async (plan: Plan) => {
  actionLoading.value = true
  try {
    await setPlanStatus(plan.id, plan.status === 'active' ? 'disabled' : 'active')
    Message.success(plan.status === 'active' ? '套餐已停用' : '套餐已启用')
    await loadBilling()
  } catch (error) {
    Message.error(getErrorMessage(error, '更新套餐状态失败'))
  } finally {
    actionLoading.value = false
  }
}

const getPlainCodesText = () => generatedCodes.value.map((code) => code.plain_code).join('\n')

const getGeneratedFileBaseName = () => {
  const name = generatedBatchName.value.trim() || 'redeem-codes'
  return name.replace(/[^\u4e00-\u9fa5a-zA-Z0-9_-]/g, '_')
}

const copyGeneratedCodes = async () => {
  await navigator.clipboard.writeText(getPlainCodesText())
  Message.success('卡密已复制')
}

const downloadGeneratedCodes = (format: 'txt' | 'csv') => {
  const content = format === 'txt'
    ? getPlainCodesText()
    : ['code', ...generatedCodes.value.map((code) => code.plain_code)].join('\n')
  const blob = new Blob([content], { type: format === 'txt' ? 'text/plain;charset=utf-8' : 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${getGeneratedFileBaseName()}.${format}`
  link.click()
  URL.revokeObjectURL(url)
}

const formatTimestamp = (timestamp: number | null) => timestamp ? new Date(timestamp * 1000).toISOString().slice(0, 10) : '-'

const formatCodeStatus = (status: string) => ({
  unused: '未兑换',
  used: '已兑换',
  disabled: '已禁用',
  expired: '已过期',
}[status] || status)

const queryCodes = async () => {
  actionLoading.value = true
  try {
    const result = await listRedeemCodes(codeFilter.value)
    codes.value = result.list
  } catch (error) {
    Message.error(getErrorMessage(error, '查询卡密失败'))
  } finally {
    actionLoading.value = false
  }
}

const handleDisableBatch = async (batchId: string) => {
  actionLoading.value = true
  try {
    await disableRedeemCodeBatch(batchId)
    Message.success('批次已禁用')
    await loadBilling()
  } catch (error) {
    Message.error(getErrorMessage(error, '禁用批次失败'))
  } finally {
    actionLoading.value = false
  }
}

const handleDisableCode = async (codeId: string) => {
  actionLoading.value = true
  try {
    await disableRedeemCode(codeId)
    Message.success('卡密已禁用')
    await queryCodes()
  } catch (error) {
    Message.error(getErrorMessage(error, '禁用卡密失败'))
  } finally {
    actionLoading.value = false
  }
}

const handleGenerateCodes = async () => {
  const firstPlan = plans.value[0]
  if (!firstPlan) {
    Message.error('请先创建套餐')
    return
  }
  actionLoading.value = true
  try {
    const result = await generateRedeemCodes({ name: codeForm.value.name, plan_id: firstPlan.id, quantity: codeForm.value.quantity })
    generatedBatchName.value = result.batch.name || codeForm.value.name
    generatedCodes.value = result.codes
    Message.success('卡密已生成，请立即复制或下载明文')
    await loadBilling()
  } catch (error) {
    Message.error(getErrorMessage(error, '生成卡密失败'))
  } finally {
    actionLoading.value = false
  }
}

onMounted(loadBilling)
</script>

<template>
  <section class="billing-page" :aria-busy="loading">
    <header class="page-header">
      <div>
        <p class="page-kicker">Billing MVP</p>
        <h2>套餐卡密</h2>
        <p>维护套餐权益，批量生成卡密，明文只在生成后展示一次。</p>
      </div>
    </header>

    <section class="quick-forms">
      <div v-if="canUpdatePlan" class="panel">
        <h3>快速创建套餐</h3>
        <div class="form-grid">
          <a-input v-model="planForm.code" placeholder="套餐代码" />
          <a-input v-model="planForm.name" placeholder="套餐名称" />
          <a-input v-model="planForm.price" placeholder="价格" />
          <a-button type="primary" :loading="actionLoading" @click="handleCreatePlan">创建套餐</a-button>
        </div>
      </div>
      <div v-if="canUpdateRedeemCode" class="panel">
        <h3>生成卡密</h3>
        <div class="form-grid">
          <a-input v-model="codeForm.name" placeholder="卡密批次名称" />
          <a-input v-model="codeForm.quantity" placeholder="数量" />
          <a-button type="primary" :loading="actionLoading" @click="handleGenerateCodes">生成卡密</a-button>
        </div>
      </div>
    </section>

    <section v-if="canUpdateRedeemCode && generatedCodes.length" class="generated-panel">
      <div class="generated-header">
        <div>
          <h3>本次生成明文</h3>
          <p>卡密明文只展示一次，请立即复制、下载并妥善保存，系统后续只保留掩码和哈希。</p>
        </div>
        <div class="generated-actions">
          <a-button size="small" @click="copyGeneratedCodes">复制全部</a-button>
          <a-button size="small" @click="downloadGeneratedCodes('txt')">下载 TXT</a-button>
          <a-button size="small" @click="downloadGeneratedCodes('csv')">下载 CSV</a-button>
        </div>
      </div>
      <div v-for="code in generatedCodes" :key="code.plain_code" class="code-line">{{ code.plain_code }}</div>
    </section>

    <section class="columns">
      <div class="panel">
        <h3>套餐列表</h3>
        <article v-for="plan in plans" :key="plan.id" class="row-card">
          <div>
            <strong>{{ plan.name }}</strong>
            <p>{{ plan.code }} · {{ plan.duration_days }} 天 · {{ plan.grant_token_credits }} 算力值</p>
          </div>
          <a-button v-if="canUpdatePlan" size="small" :status="plan.status === 'active' ? 'danger' : 'normal'" :loading="actionLoading" @click="handleTogglePlan(plan)">
            {{ plan.status === 'active' ? '停用' : '启用' }}
          </a-button>
        </article>
      </div>

      <div class="panel">
        <h3>卡密批次</h3>
        <article v-for="batch in batches" :key="batch.id" class="row-card">
        <div>
          <strong>{{ batch.name }}</strong>
          <p>数量 {{ batch.quantity }} · {{ batch.status === 'disabled' ? '已禁用' : '可用' }}</p>
        </div>
        <a-button v-if="canUpdateRedeemCode && batch.status !== 'disabled'" size="small" status="danger" :loading="actionLoading" @click="handleDisableBatch(batch.id)">禁用批次</a-button>
      </article>
      </div>

      <div class="panel">
        <div class="panel-title-row">
          <h3>最近卡密</h3>
          <div class="code-filter-form">
            <a-input v-model="codeFilter.code_keyword" placeholder="卡密掩码关键词" />
            <a-input v-model="codeFilter.status" placeholder="状态 unused/used/disabled/expired" />
            <a-button :loading="actionLoading" @click="queryCodes">查询卡密</a-button>
          </div>
        </div>
        <article v-for="code in codes" :key="code.id" class="row-card">
        <div>
          <strong>{{ code.code_mask }}</strong>
          <p>{{ formatCodeStatus(code.status) }}</p>
          <p>兑换用户：{{ code.redeemed_by || '-' }} · 兑换时间：{{ formatTimestamp(code.redeemed_at) }}</p>
        </div>
        <a-button v-if="canUpdateRedeemCode && (code.status === 'unused' || code.status === 'expired')" size="small" status="danger" :loading="actionLoading" @click="handleDisableCode(code.id)">禁用卡密</a-button>
      </article>
      </div>
    </section>
  </section>
</template>

<style scoped>
.billing-page {
  display: grid;
  gap: 20px;
}

.page-header,
.panel,
.generated-panel {
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

h2 {
  font-size: 30px;
}

.page-header p:not(.page-kicker) {
  margin-top: 8px;
  color: #d8e4f7;
}

.quick-forms,
.columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.columns {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.form-grid {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.row-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 0;
  border-top: 1px solid #edf2f7;
}

.row-card:first-of-type {
  margin-top: 12px;
}

.row-card p,
.generated-panel p {
  margin-top: 4px;
  color: #667085;
  font-size: 13px;
}

.generated-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.generated-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.code-line {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  background: #101828;
  color: #f8fafc;
  font-family: monospace;
}
</style>
