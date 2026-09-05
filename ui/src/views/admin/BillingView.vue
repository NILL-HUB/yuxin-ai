<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useAdminStore } from '@/stores/admin'
import {
  disableRedeemCode,
  disableRedeemCodeBatch,
  generateRedeemCodes,
  getRedeemCodePlain,
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

const planFilter = ref({ current_page: 1, page_size: 10 })
const plansTotal = ref(0)
const batchFilter = ref({ current_page: 1, page_size: 10 })
const batchesTotal = ref(0)
const codeFilter = ref({ batch_id: '', status: '' as '' | 'unused' | 'used' | 'disabled' | 'expired', code_keyword: '', current_page: 1, page_size: 20 })
const codesTotal = ref(0)

const codeForm = ref({ name: '', description: '', plan_id: '', quantity: 10 })

const codeStatusOptions = computed(() => [
  { label: t('admin.billing.statusAll'), value: '' },
  { label: t('admin.billing.statusUnused'), value: 'unused' },
  { label: t('admin.billing.statusUsed'), value: 'used' },
  { label: t('admin.billing.statusDisabled'), value: 'disabled' },
  { label: t('admin.billing.statusExpired'), value: 'expired' },
])

const planOptions = computed(() =>
  plans.value.map((plan) => ({
    label: `${plan.name} · ¥${Number(plan.price).toFixed(2)}`,
    value: plan.id,
  })),
)

const batchOptions = computed(() =>
  batches.value.map((batch) => ({
    label: batch.name,
    value: batch.id,
  })),
)

const planNameOf = (planId: string | null | undefined) => {
  if (!planId) return '-'
  return plans.value.find((plan) => plan.id === planId)?.name || '-'
}

const statusTagColor = (status: string) => ({
  unused: 'arcoblue',
  used: 'gray',
  disabled: 'red',
  expired: 'orange',
}[status] || 'gray')

const loadPlans = async () => {
  try {
    loading.value = true
    const result = await listPlans({ keyword: '', status: '', current_page: planFilter.value.current_page, page_size: planFilter.value.page_size })
    plans.value = result.list
    plansTotal.value = result.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.billing.loadFailed')))
  } finally {
    loading.value = false
  }
}

const loadBatches = async () => {
  try {
    loading.value = true
    const result = await listRedeemCodeBatches({ keyword: '', current_page: batchFilter.value.current_page, page_size: batchFilter.value.page_size })
    batches.value = result.list
    batchesTotal.value = result.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.billing.loadFailed')))
  } finally {
    loading.value = false
  }
}

const loadCodes = async () => {
  try {
    loading.value = true
    const result = await listRedeemCodes(codeFilter.value)
    codes.value = result.list
    codesTotal.value = result.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.billing.loadFailed')))
  } finally {
    loading.value = false
  }
}

const onPlansPageChange = (page: number) => {
  planFilter.value.current_page = page
  loadPlans()
}

const onBatchesPageChange = (page: number) => {
  batchFilter.value.current_page = page
  loadBatches()
}

const onCodesPageChange = (page: number) => {
  codeFilter.value.current_page = page
  loadCodes()
}

const handleTogglePlan = async (plan: Plan) => {
  actionLoading.value = true
  try {
    await setPlanStatus(plan.id, plan.status === 'active' ? 'disabled' : 'active')
    Message.success(plan.status === 'active' ? t('admin.billing.planDisabled') : t('admin.billing.planEnabled'))
    await loadPlans()
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

const formatDate = (timestamp: number | null) => (timestamp ? new Date(timestamp * 1000).toLocaleDateString('zh-CN') : '-')
const formatTime = (timestamp: number | null) => (timestamp ? new Date(timestamp * 1000).toLocaleString('zh-CN', { hour12: false }) : '-')

const formatCodeStatus = (status: string) => t(`admin.billing.status${status.charAt(0).toUpperCase()}${status.slice(1)}`) || status

const queryCodes = async () => {
  actionLoading.value = true
  try {
    codeFilter.value.current_page = 1
    const result = await listRedeemCodes(codeFilter.value)
    codes.value = result.list
    codesTotal.value = result.paginator?.total_record || 0
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
    await loadBatches()
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
  if (!codeForm.value.plan_id) {
    Message.error(t('admin.billing.planSelectRequired'))
    return
  }
  if (!codeForm.value.name.trim()) {
    Message.error(t('admin.billing.batchNameRequired'))
    return
  }
  const quantity = Math.max(1, Math.min(1000, Math.floor(Number(codeForm.value.quantity) || 1)))
  actionLoading.value = true
  try {
    const result = await generateRedeemCodes({
      name: codeForm.value.name.trim(),
      description: codeForm.value.description.trim(),
      plan_id: codeForm.value.plan_id,
      quantity,
    })
    generatedBatchName.value = result.batch.name || codeForm.value.name
    generatedCodes.value = result.codes
    Message.success(t('admin.billing.codesGenerated'))
    await Promise.all([loadBatches(), loadCodes()])
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.billing.generateFailed')))
  } finally {
    actionLoading.value = false
  }
}

const plainModalVisible = ref(false)
const plainCodeValue = ref('')
const plainMaskValue = ref('')

const handleViewPlain = async (code: RedeemCodeRecord) => {
  actionLoading.value = true
  try {
    const result = await getRedeemCodePlain(code.id)
    plainMaskValue.value = result.code_mask
    plainCodeValue.value = result.plain_code
    plainModalVisible.value = true
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.billing.viewPlainFailed')))
  } finally {
    actionLoading.value = false
  }
}

const copyPlainCode = async () => {
  await navigator.clipboard.writeText(plainCodeValue.value)
  Message.success(t('admin.billing.codesCopied'))
}

onMounted(async () => {
  await Promise.all([loadPlans(), loadBatches(), loadCodes()])
})
</script>

<template>
  <section class="billing-page" :aria-busy="loading">
    <header class="page-hero">
      <div>
        <p class="page-kicker">Redeem Codes</p>
        <h2>{{ t('admin.billing.title') }}</h2>
        <p>{{ t('admin.billing.description') }}</p>
      </div>
    </header>

    <div class="content-grid">
      <!-- 套餐列表 -->
      <section class="panel">
        <div class="panel-head">
          <h3>{{ t('admin.billing.planListTitle') }}</h3>
          <span class="count-badge">{{ plansTotal }}</span>
        </div>
        <p class="panel-sub">{{ t('admin.billing.planListDesc') }}</p>
        <article v-for="plan in plans" :key="plan.id" class="row-card">
          <div class="row-main">
            <div class="row-title">
              <strong>{{ plan.name }}</strong>
              <a-tag v-if="plan.auto_renew_default" color="purple" size="small">{{ t('admin.billing.autoRenewTag') }}</a-tag>
            </div>
            <p>{{ plan.code }} · {{ plan.plan_type === 'membership' ? `${plan.duration_days}${t('admin.billing.days')}` : '-' }} · {{ plan.grant_token_credits }} {{ t('admin.billing.credits') }} · ¥{{ Number(plan.price).toFixed(2) }}</p>
          </div>
          <a-switch
            v-if="canUpdatePlan"
            :model-value="plan.status === 'active'"
            :loading="actionLoading"
            :checked-text="t('admin.billing.enabled')"
            :unchecked-text="t('admin.billing.disabled')"
            @change="handleTogglePlan(plan)"
          />
        </article>
        <p v-if="plans.length === 0" class="empty-text">{{ t('admin.billing.noPlans') }}</p>
        <div class="pager">
          <a-pagination
            :total="plansTotal"
            :current="planFilter.current_page"
            :page-size="planFilter.page_size"
            show-total
            @change="onPlansPageChange"
          />
        </div>
      </section>

      <!-- 卡密生成 -->
      <section v-if="canUpdateRedeemCode" class="panel">
        <div class="panel-head">
          <h3>{{ t('admin.billing.generateCodesTitle') }}</h3>
        </div>

        <div class="concept-box">
          <strong>{{ t('admin.billing.batchConceptTitle') }}</strong>
          <p>{{ t('admin.billing.batchConceptDesc') }}</p>
        </div>

        <div class="stack-form">
          <div class="field">
            <label>{{ t('admin.billing.planField') }} <span class="req">*</span></label>
            <a-select
              v-model="codeForm.plan_id"
              :options="planOptions"
              :placeholder="t('admin.billing.planSelectPlaceholder')"
              :loading="loading"
              allow-search
            />
          </div>
          <div class="field-grid two">
            <div class="field">
              <label>{{ t('admin.billing.batchName') }} <span class="req">*</span></label>
              <a-input v-model="codeForm.name" :placeholder="t('admin.billing.batchNamePlaceholder')" />
            </div>
            <div class="field">
              <label>{{ t('admin.billing.quantityLabel') }}</label>
              <a-input-number v-model="codeForm.quantity" :min="1" :max="1000" :precision="0" class="full" />
            </div>
          </div>
          <div class="field">
            <label>{{ t('admin.billing.descriptionLabel') }}</label>
            <a-textarea v-model="codeForm.description" :placeholder="t('admin.billing.descriptionPlaceholder')" :auto-size="{ minRows: 2, maxRows: 3 }" />
          </div>
          <a-button type="primary" long :loading="actionLoading" @click="handleGenerateCodes">
            {{ t('admin.billing.generateCodes') }}
          </a-button>
        </div>
      </section>
    </div>

    <!-- 本次生成明文明细 -->
    <section v-if="canUpdateRedeemCode && generatedCodes.length" class="panel">
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
      <div class="code-grid">
        <div v-for="code in generatedCodes" :key="code.plain_code" class="code-chip">{{ code.plain_code }}</div>
      </div>
    </section>

    <!-- 卡密批次 -->
    <section class="panel">
      <div class="panel-head">
        <h3>{{ t('admin.billing.batchTitle') }}</h3>
        <span class="count-badge">{{ batchesTotal }}</span>
      </div>
      <p class="panel-sub">{{ t('admin.billing.batchListDesc') }}</p>
      <article v-for="batch in batches" :key="batch.id" class="row-card">
        <div class="row-main">
          <div class="row-title">
            <strong>{{ batch.name }}</strong>
            <a-tag :color="batch.status === 'disabled' ? 'red' : 'green'" size="small">
              {{ batch.status === 'disabled' ? t('admin.billing.batchDisabledLabel') : t('admin.billing.batchAvailable') }}
            </a-tag>
          </div>
          <p v-if="batch.description" class="desc-line">{{ t('admin.billing.batchPurpose') }}：{{ batch.description }}</p>
          <p>
            {{ t('admin.billing.batchPlan') }}：{{ batch.plan_name || planNameOf(batch.plan_id) }} ·
            {{ t('admin.billing.quantityLabel') }}：{{ batch.quantity }} ·
            {{ batch.expires_at ? `${t('admin.billing.expiresAt')}${formatDate(batch.expires_at)}` : t('admin.billing.noExpiry') }}
          </p>
        </div>
        <a-button
          v-if="canUpdateRedeemCode && batch.status !== 'disabled'"
          size="small"
          status="danger"
          :loading="actionLoading"
          @click="handleDisableBatch(batch.id)"
        >
          {{ t('admin.billing.disableBatch') }}
        </a-button>
      </article>
      <p v-if="batches.length === 0" class="empty-text">{{ t('admin.billing.noBatches') }}</p>
      <div class="pager">
        <a-pagination
          :total="batchesTotal"
          :current="batchFilter.current_page"
          :page-size="batchFilter.page_size"
          show-total
          @change="onBatchesPageChange"
        />
      </div>
    </section>

    <!-- 卡密明细 -->
    <section class="panel">
      <div class="panel-head">
        <h3>{{ t('admin.billing.recentCodesTitle') }}</h3>
        <span class="count-badge">{{ codesTotal }}</span>
      </div>
      <div class="filter-bar">
        <a-select
          v-model="codeFilter.batch_id"
          :options="batchOptions"
          :placeholder="t('admin.billing.batchFilterPlaceholder')"
          allow-clear
          class="filter-batch"
        />
        <a-select
          v-model="codeFilter.status"
          :options="codeStatusOptions"
          :placeholder="t('admin.billing.statusFilterPlaceholder')"
          class="filter-status"
        />
        <a-input
          v-model="codeFilter.code_keyword"
          :placeholder="t('admin.billing.codeKeywordPlaceholder')"
          allow-clear
          class="filter-keyword"
          @press-enter="queryCodes"
        />
        <a-button type="primary" :loading="actionLoading" @click="queryCodes">{{ t('admin.billing.queryCodes') }}</a-button>
      </div>

      <article v-for="code in codes" :key="code.id" class="row-card">
        <div class="row-main">
          <div class="row-title code-title">
            <code class="code-mask">{{ code.code_mask }}</code>
            <a-tag :color="statusTagColor(code.status)" size="small">{{ formatCodeStatus(code.status) }}</a-tag>
          </div>
          <p>{{ t('admin.billing.batchPlan') }}：{{ code.plan_name || planNameOf(code.plan_id) }}</p>
          <p>
            <template v-if="code.status === 'used'">
              {{ t('admin.billing.redeemedBy') }}：{{ code.redeemed_by || '-' }} · {{ t('admin.billing.redeemedAt') }}：{{ formatTime(code.redeemed_at) }}
            </template>
            <template v-else>
              {{ t('admin.billing.createdAt') }}：{{ formatTime(code.created_at) }}
              <template v-if="code.expires_at"> · {{ t('admin.billing.expiresAt') }}{{ formatDate(code.expires_at) }}</template>
            </template>
          </p>
        </div>
        <div class="row-actions">
          <a-button
            v-if="canUpdateRedeemCode && (code.status === 'unused' || code.status === 'expired')"
            size="mini"
            type="text"
            :loading="actionLoading"
            @click="handleViewPlain(code)"
          >
            {{ t('admin.billing.viewPlain') }}
          </a-button>
          <a-button
            v-if="canUpdateRedeemCode && (code.status === 'unused' || code.status === 'expired')"
            size="mini"
            type="text"
            status="danger"
            :loading="actionLoading"
            @click="handleDisableCode(code.id)"
          >
            {{ t('admin.billing.disableCode') }}
          </a-button>
        </div>
      </article>
      <p v-if="codes.length === 0" class="empty-text">{{ t('admin.billing.noCodes') }}</p>
      <div class="pager">
        <a-pagination
          :total="codesTotal"
          :current="codeFilter.current_page"
          :page-size="codeFilter.page_size"
          show-total
          @change="onCodesPageChange"
        />
      </div>
    </section>

    <!-- 查看卡密明文弹窗 -->
    <a-modal
      :visible="plainModalVisible"
      :title="`${t('admin.billing.plainModalTitle')} · ${plainMaskValue}`"
      :footer="false"
      width="420"
      @cancel="plainModalVisible = false"
    >
      <div class="plain-modal">
        <p class="plain-code">{{ plainCodeValue }}</p>
        <div class="plain-actions">
          <a-button type="primary" @click="copyPlainCode">{{ t('admin.billing.copy') }}</a-button>
          <a-button @click="plainModalVisible = false">{{ t('common.actions.close') }}</a-button>
        </div>
      </div>
    </a-modal>
  </section>
</template>

<style scoped>
.billing-page {
  display: grid;
  gap: 18px;
}

.page-hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 26px 28px;
  border-radius: 22px;
  background: linear-gradient(135deg, #101828, #1d3a5f);
  color: #fff;
  box-shadow: 0 14px 40px rgba(15, 23, 42, 0.14);
}

.page-kicker {
  margin: 0 0 6px;
  color: #a9c7ff;
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.page-hero h2 {
  margin: 0;
  font-size: 28px;
}

.page-hero p:not(.page-kicker) {
  margin: 8px 0 0;
  color: #d8e4f7;
  font-size: 13px;
  max-width: 680px;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  gap: 18px;
}

.panel {
  padding: 20px 22px;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.panel h3 {
  margin: 0;
  font-size: 16px;
}

.panel-sub {
  margin: 6px 0 0;
  color: #667085;
  font-size: 13px;
}

.count-badge {
  min-width: 22px;
  padding: 1px 8px;
  border-radius: 999px;
  background: #eef2f8;
  color: #667085;
  font-size: 12px;
  text-align: center;
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

.row-main {
  min-width: 0;
}

.row-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.row-card p {
  margin: 4px 0 0;
  color: #667085;
  font-size: 13px;
}

.desc-line {
  color: #344054 !important;
}

.code-title {
  gap: 10px;
}

.code-mask {
  font-family: 'SFMono-Regular', Consolas, Menlo, monospace;
  font-size: 13px;
  color: #101828;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  white-space: nowrap;
}

.concept-box {
  margin: 12px 0 16px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #f3f7ff;
  border: 1px solid #dfe9fb;
}

.concept-box strong {
  color: #2f5fd0;
  font-size: 13px;
}

.concept-box p {
  margin: 4px 0 0;
  color: #5b6b8c;
  font-size: 12px;
  line-height: 1.7;
}

.stack-form {
  display: grid;
  gap: 12px;
}

.field {
  display: grid;
  gap: 6px;
}

.field label {
  font-size: 13px;
  color: #344054;
  font-weight: 500;
}

.req {
  color: #f53f3f;
}

.field-grid {
  display: grid;
  gap: 10px;
}

.field-grid.two {
  grid-template-columns: 1fr 1fr;
}

.full {
  width: 100%;
}

.generated-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.generated-header h3 {
  margin: 0;
}

.generated-header p {
  margin: 6px 0 0;
  color: #667085;
  font-size: 13px;
}

.generated-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.code-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.code-chip {
  padding: 8px 10px;
  border-radius: 10px;
  background: #101828;
  color: #f8fafc;
  font-family: monospace;
  font-size: 12px;
  word-break: break-all;
}

.filter-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 12px;
}

.filter-batch {
  width: 220px;
}

.filter-status {
  width: 140px;
}

.filter-keyword {
  width: 180px;
}

.empty-text {
  margin: 14px 0 4px;
  color: #98a2b3;
  font-size: 13px;
}

.plain-modal {
  display: grid;
  gap: 12px;
  text-align: center;
}

.plain-code {
  padding: 16px 12px;
  border-radius: 12px;
  background: #101828;
  color: #f8fafc;
  font-family: monospace;
  font-size: 14px;
  word-break: break-all;
}

.plain-actions {
  display: flex;
  justify-content: center;
  gap: 8px;
}

@media (max-width: 1100px) {
  .content-grid {
    grid-template-columns: 1fr;
  }
}
</style>