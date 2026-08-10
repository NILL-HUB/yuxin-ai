<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
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

const { t } = useI18n()

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
const codeForm = ref({ name: '', quantity: '1' })
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
    Message.error(getErrorMessage(error, t('admin.billing.loadFailed')))
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
    Message.success(t('admin.billing.planCreated'))
    await loadBilling()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.billing.createPlanFailed')))
  } finally {
    actionLoading.value = false
  }
}

const handleTogglePlan = async (plan: Plan) => {
  actionLoading.value = true
  try {
    await setPlanStatus(plan.id, plan.status === 'active' ? 'disabled' : 'active')
    Message.success(plan.status === 'active' ? t('admin.billing.planDisabled') : t('admin.billing.planEnabled'))
    await loadBilling()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.billing.updatePlanFailed')))
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
  Message.success(t('admin.billing.codesCopied'))
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
  unused: t('admin.billing.statusUnused'),
  used: t('admin.billing.statusUsed'),
  disabled: t('admin.billing.statusDisabled'),
  expired: t('admin.billing.statusExpired'),
}[status] || status)

const queryCodes = async () => {
  actionLoading.value = true
  try {
    const result = await listRedeemCodes(codeFilter.value)
    codes.value = result.list
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.billing.queryCodesFailed')))
  } finally {
    actionLoading.value = false
  }
}

const handleDisableBatch = async (batchId: string) => {
  actionLoading.value = true
  try {
    await disableRedeemCodeBatch(batchId)
    Message.success(t('admin.billing.batchDisabled'))
    await loadBilling()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.billing.disableBatchFailed')))
  } finally {
    actionLoading.value = false
  }
}

const handleDisableCode = async (codeId: string) => {
  actionLoading.value = true
  try {
    await disableRedeemCode(codeId)
    Message.success(t('admin.billing.codeDisabled'))
    await queryCodes()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.billing.disableCodeFailed')))
  } finally {
    actionLoading.value = false
  }
}

const handleGenerateCodes = async () => {
  const firstPlan = plans.value[0]
  if (!firstPlan) {
    Message.error(t('admin.billing.planRequired'))
    return
  }
  actionLoading.value = true
  try {
    const result = await generateRedeemCodes({ name: codeForm.value.name, plan_id: firstPlan.id, quantity: Number(codeForm.value.quantity) })
    generatedBatchName.value = result.batch.name || codeForm.value.name
    generatedCodes.value = result.codes
    Message.success(t('admin.billing.codesGenerated'))
    await loadBilling()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.billing.generateFailed')))
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
        <h2>{{ t('admin.billing.title') }}</h2>
        <p>{{ t('admin.billing.description') }}</p>
      </div>
    </header>

    <section class="quick-forms">
      <div v-if="canUpdatePlan" class="panel">
        <h3>{{ t('admin.billing.createPlanTitle') }}</h3>
        <div class="form-grid">
          <a-input v-model="planForm.code" :placeholder="t('admin.billing.planCodePlaceholder')" />
          <a-input v-model="planForm.name" :placeholder="t('admin.billing.planNamePlaceholder')" />
          <a-input v-model="planForm.price" :placeholder="t('admin.billing.planPricePlaceholder')" />
          <a-button type="primary" :loading="actionLoading" @click="handleCreatePlan">{{ t('admin.billing.createPlan') }}</a-button>
        </div>
      </div>
      <div v-if="canUpdateRedeemCode" class="panel">
        <h3>{{ t('admin.billing.generateCodesTitle') }}</h3>
        <div class="form-grid">
          <a-input v-model="codeForm.name" :placeholder="t('admin.billing.batchNamePlaceholder')" />
          <a-input v-model="codeForm.quantity" :placeholder="t('admin.billing.quantityPlaceholder')" />
          <a-button type="primary" :loading="actionLoading" @click="handleGenerateCodes">{{ t('admin.billing.generateCodes') }}</a-button>
        </div>
      </div>
    </section>

    <section v-if="canUpdateRedeemCode && generatedCodes.length" class="generated-panel">
      <div class="generated-header">
        <div>
          <h3>{{ t('admin.billing.generatedTitle') }}</h3>
          <p>{{ t('admin.billing.generatedDesc') }}</p>
        </div>
        <div class="generated-actions">
          <a-button size="small" @click="copyGeneratedCodes">{{ t('admin.billing.copyAll') }}</a-button>
          <a-button size="small" @click="downloadGeneratedCodes('txt')">{{ t('admin.billing.downloadTxt') }}</a-button>
          <a-button size="small" @click="downloadGeneratedCodes('csv')">{{ t('admin.billing.downloadCsv') }}</a-button>
        </div>
      </div>
      <div v-for="code in generatedCodes" :key="code.plain_code" class="code-line">{{ code.plain_code }}</div>
    </section>

    <section class="columns">
      <div class="panel">
        <h3>{{ t('admin.billing.planListTitle') }}</h3>
        <article v-for="plan in plans" :key="plan.id" class="row-card">
          <div>
            <strong>{{ plan.name }}</strong>
            <p>{{ plan.code }} · {{ plan.duration_days }} {{ t('admin.billing.days') }} · {{ plan.grant_token_credits }} {{ t('admin.billing.credits') }}</p>
          </div>
          <a-button v-if="canUpdatePlan" size="small" :status="plan.status === 'active' ? 'danger' : 'normal'" :loading="actionLoading" @click="handleTogglePlan(plan)">
            {{ plan.status === 'active' ? t('admin.billing.disable') : t('admin.billing.enable') }}
          </a-button>
        </article>
      </div>

      <div class="panel">
        <h3>{{ t('admin.billing.batchTitle') }}</h3>
        <article v-for="batch in batches" :key="batch.id" class="row-card">
        <div>
          <strong>{{ batch.name }}</strong>
          <p>{{ t('admin.billing.quantityPlaceholder') }} {{ batch.quantity }} · {{ batch.status === 'disabled' ? t('admin.billing.batchDisabledLabel') : t('admin.billing.batchAvailable') }}</p>
        </div>
        <a-button v-if="canUpdateRedeemCode && batch.status !== 'disabled'" size="small" status="danger" :loading="actionLoading" @click="handleDisableBatch(batch.id)">{{ t('admin.billing.disableBatch') }}</a-button>
      </article>
      </div>

      <div class="panel">
        <div class="panel-title-row">
          <h3>{{ t('admin.billing.recentCodesTitle') }}</h3>
          <div class="code-filter-form">
            <a-input v-model="codeFilter.code_keyword" :placeholder="t('admin.billing.codeKeywordPlaceholder')" />
            <a-input v-model="codeFilter.status" :placeholder="t('admin.billing.statusPlaceholder')" />
            <a-button :loading="actionLoading" @click="queryCodes">{{ t('admin.billing.queryCodes') }}</a-button>
          </div>
        </div>
        <article v-for="code in codes" :key="code.id" class="row-card">
        <div>
          <strong>{{ code.code_mask }}</strong>
          <p>{{ formatCodeStatus(code.status) }}</p>
          <p>{{ t('admin.billing.redeemedBy') }}：{{ code.redeemed_by || '-' }} · {{ t('admin.billing.redeemedAt') }}：{{ formatTimestamp(code.redeemed_at) }}</p>
        </div>
        <a-button v-if="canUpdateRedeemCode && (code.status === 'unused' || code.status === 'expired')" size="small" status="danger" :loading="actionLoading" @click="handleDisableCode(code.id)">{{ t('admin.billing.disableCode') }}</a-button>
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
