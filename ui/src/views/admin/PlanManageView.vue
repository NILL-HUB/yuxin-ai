<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useAdminStore } from '@/stores/admin'
import { createPlan, deletePlan, getBillingConfig, listPlans, setPlanStatus, updateBillingConfig, updatePlan } from '@/services/admin-billing'
import { type BillingConfig, type BillingStatus, type Plan } from '@/models/billing'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()
const adminStore = useAdminStore()
const canManagePlan = computed(() => adminStore.hasPermission('plan:update'))

const loading = ref(false)
const saving = ref(false)
const savingPerYuan = ref(false)
const configLoading = ref(false)
const billingConfig = ref<BillingConfig | null>(null)
const billingPerYuanConfig = ref<BillingConfig | null>(null)
const billingRateDraft = ref(1)
const billingPerYuanDraft = ref(100)
const plans = ref<Plan[]>([])
const total = ref(0)
const filters = reactive({ keyword: '', status: '' as '' | BillingStatus, current_page: 1, page_size: 20 })

const loadBillingConfig = async () => {
  configLoading.value = true
  try {
    const [rateConfig, perYuanConfig] = await Promise.all([
      getBillingConfig(),
      getBillingConfig('credits_per_yuan'),
    ])
    billingConfig.value = rateConfig
    billingRateDraft.value = rateConfig?.value_numeric ?? 1
    billingPerYuanConfig.value = perYuanConfig
    billingPerYuanDraft.value = perYuanConfig?.value_numeric ?? 100
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.plans.loadBillingConfigFailed')))
  } finally {
    configLoading.value = false
  }
}

const handleSaveRate = async () => {
  saving.value = true
  try {
    const result = await updateBillingConfig({ value_numeric: billingRateDraft.value ?? 1 })
    billingConfig.value = result
    billingRateDraft.value = result?.value_numeric ?? billingRateDraft.value
    Message.success(t('admin.plans.billingConfigSaved'))
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.plans.saveBillingConfigFailed')))
  } finally {
    saving.value = false
  }
}

const handleSavePerYuan = async () => {
  savingPerYuan.value = true
  try {
    const result = await updateBillingConfig({ code: 'credits_per_yuan', value_numeric: billingPerYuanDraft.value ?? 100 })
    billingPerYuanConfig.value = result
    billingPerYuanDraft.value = result?.value_numeric ?? billingPerYuanDraft.value
    Message.success(t('admin.plans.billingConfigSaved'))
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.plans.saveBillingConfigFailed')))
  } finally {
    savingPerYuan.value = false
  }
}

const perYuanImpact = computed(() => {
  const current = billingPerYuanConfig.value?.value_numeric ?? 100
  const next = billingPerYuanDraft.value ?? current
  if (next === current) return t('admin.plans.billingPerYuanNoChange')
  const delta = ((current - next) / current) * 100
  const sign = delta > 0 ? '+' : ''
  return `${sign}${delta.toFixed(0)}%`
})

type PlanType = 'balance' | 'membership' | 'credits'

const emptyForm = () => ({
  code: '',
  name: '',
  description: '',
  plan_type: 'membership' as PlanType,
  price: 0,
  duration_days: 30,
  grant_token_credits: 0,
  auto_renew_threshold_percent: 10,
  auto_renew_threshold_days: 1,
  purchase_limit: 0,
  purchase_limit_period: 'none' as 'none' | 'all' | 'day' | 'week' | 'month',
  quota_refresh_period: 'none' as 'none' | 'cycle',
  auto_renew_default: false,
  sort_order: 0,
  status: 'active' as BillingStatus,
})

const drawerVisible = ref(false)
const editingId = ref('')
const form = reactive(emptyForm())

const planTypeOptions = computed(() => [
  { label: t('admin.plans.planType.membership'), value: 'membership' },
  { label: t('admin.plans.planType.credits'), value: 'credits' },
  { label: t('admin.plans.planType.balance'), value: 'balance' },
])

const statusOptions = computed(() => [
  { label: t('admin.plans.statusFilter.all'), value: '' },
  { label: t('admin.plans.statusFilter.active'), value: 'active' },
  { label: t('admin.plans.statusFilter.disabled'), value: 'disabled' },
])

const purchasePeriodOptions = computed(() => [
  { label: t('admin.plans.purchaseLimit.none'), value: 'none' },
  { label: t('admin.plans.purchaseLimit.all'), value: 'all' },
  { label: t('admin.plans.purchaseLimit.day'), value: 'day' },
  { label: t('admin.plans.purchaseLimit.week'), value: 'week' },
  { label: t('admin.plans.purchaseLimit.month'), value: 'month' },
])

const refreshPeriodOptions = computed(() => [
  { label: t('admin.plans.quotaRefresh.none'), value: 'none' },
  { label: t('admin.plans.quotaRefresh.cycle'), value: 'cycle' },
])

const refreshText = (record: Plan) => {
  if (record.quota_refresh_period !== 'cycle' || !record.duration_days) return '-'
  return t('admin.plans.quotaRefresh.perCycle', { days: record.duration_days })
}

const limitText = (record: Plan) => {
  const limit = record.purchase_limit || 0
  const period = record.purchase_limit_period || 'none'
  if (limit <= 0 || period === 'none') return '-'
  return `${limit}次/${t(`admin.plans.purchaseLimit.${period}`)}`
}

const perYuan = computed(() => form.grant_token_credits / Math.max(Number(form.price || 0), 0.01))
const planTypeHint = computed(() => {
  if (form.plan_type === 'membership') return t('admin.plans.hints.membership', { rate: perYuan.value.toFixed(0) })
  if (form.plan_type === 'credits') return t('admin.plans.hints.credits', { rate: perYuan.value.toFixed(0) })
  return t('admin.plans.hints.balance')
})

const loadPlans = async () => {
  loading.value = true
  try {
    const result = await listPlans(filters)
    plans.value = result.list || []
    total.value = result.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.plans.loadFailed')))
  } finally {
    loading.value = false
  }
}

const handleSearch = async () => {
  filters.current_page = 1
  await loadPlans()
}

const onPageChange = async (page: number) => {
  filters.current_page = page
  await loadPlans()
}

const openCreate = () => {
  editingId.value = ''
  Object.assign(form, emptyForm())
  drawerVisible.value = true
}

const openEdit = (plan: Plan) => {
  editingId.value = plan.id
  Object.assign(form, {
    code: plan.code,
    name: plan.name,
    description: plan.description || '',
    plan_type: plan.plan_type || 'membership',
    price: Number(plan.price),
    duration_days: plan.duration_days,
    grant_token_credits: plan.grant_token_credits,
    auto_renew_threshold_percent: plan.auto_renew_threshold_percent,
    auto_renew_threshold_days: plan.auto_renew_threshold_days,
    purchase_limit: plan.purchase_limit,
    purchase_limit_period: plan.purchase_limit_period || 'none',
    quota_refresh_period: plan.quota_refresh_period || 'none',
    auto_renew_default: !!plan.auto_renew_default,
    sort_order: plan.sort_order,
    status: plan.status,
  })
  drawerVisible.value = true
}

const handleSave = async () => {
  if (!form.code.trim()) {
    Message.error(t('admin.plans.errors.codeRequired'))
    return
  }
  if (!form.name.trim()) {
    Message.error(t('admin.plans.errors.nameRequired'))
    return
  }
  const price = Number(form.price)
  if (!Number.isFinite(price) || price < 0) {
    Message.error(t('admin.plans.errors.priceInvalid'))
    return
  }
  saving.value = true
  try {
    const payload = {
      ...form,
      price: price.toFixed(2),
      grant_token_credits: Math.max(0, Math.floor(Number(form.grant_token_credits) || 0)),
      duration_days: Math.max(0, Math.floor(Number(form.duration_days) || 0)),
      auto_renew_threshold_percent: Math.min(100, Math.max(0, Math.floor(Number(form.auto_renew_threshold_percent) || 0))),
      purchase_limit: Math.max(0, Math.floor(Number(form.purchase_limit) || 0)),
    }
    if (editingId.value) {
      await updatePlan(editingId.value, payload)
      Message.success(t('admin.plans.updated'))
    } else {
      await createPlan(payload)
      Message.success(t('admin.plans.created'))
    }
    drawerVisible.value = false
    await loadPlans()
  } catch (error) {
    Message.error(getErrorMessage(error, editingId.value ? t('admin.plans.errors.createFailed') : t('admin.plans.errors.createFailed')))
  } finally {
    saving.value = false
  }
}

const handleToggleStatus = async (plan: Plan) => {
  const next = plan.status === 'active' ? 'disabled' : 'active'
  saving.value = true
  try {
    await setPlanStatus(plan.id, next)
    Message.success(next === 'active' ? t('admin.plans.enabled') : t('admin.plans.disabled'))
    await loadPlans()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.plans.errors.statusFailed')))
  } finally {
    saving.value = false
  }
}

const handleDelete = (plan: Plan) => {
  Modal.confirm({
    title: t('admin.plans.deleteTitle'),
    content: t('admin.plans.deleteConfirm', { name: plan.name }),
    okText: t('admin.plans.delete'),
    cancelText: t('common.actions.cancel'),
    okButtonProps: { status: 'danger' },
    onBeforeOk: async () => {
      try {
        await deletePlan(plan.id)
        Message.success(t('admin.plans.deleted'))
        await loadPlans()
      } catch (error) {
        Message.error(getErrorMessage(error, t('admin.plans.errors.deleteFailed')))
        return false
      }
    },
  })
}

const planTypeTag = (planType: string) => ({
  membership: 'blue',
  credits: 'arcoblue',
  balance: 'green',
}[planType] || 'gray')

const rateText = (plan: Plan) => {
  const price = Number(plan.price || 0)
  if (!price || !plan.grant_token_credits) return '-'
  return `${(plan.grant_token_credits / price).toFixed(0)}/元`
}

const formatTime = (value: number | null) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

onMounted(async () => {
  await Promise.all([loadPlans(), loadBillingConfig()])
})
</script>

<template>
  <section class="plans-page" :aria-busy="loading">
    <header class="page-hero">
      <div>
        <p class="page-kicker">Plan Center</p>
        <h2>{{ t('admin.plans.title') }}</h2>
        <p>{{ t('admin.plans.description') }}</p>
      </div>
      <div class="hero-actions">
        <a-button v-if="canManagePlan" type="primary" @click="openCreate">+ {{ t('admin.plans.createPlan') }}</a-button>
      </div>
    </header>

    <section class="panel billing-config-panel">
      <div class="config-head">
        <div class="config-desc">
          <h3>{{ t('admin.plans.billingConfigTitle') }}</h3>
          <p>{{ t('admin.plans.billingConfigDesc') }}</p>
        </div>
      </div>
      <div class="config-grid">
        <div class="config-card">
          <div class="config-card-head">
            <span class="config-card-title">{{ t('admin.plans.billingRateLabel') }}</span>
            <a-tooltip :content="t('admin.plans.billingRateTooltip')">
              <span class="config-card-badge">{{ t('admin.plans.billingRateBadge') }}</span>
            </a-tooltip>
          </div>
          <p class="config-card-desc">{{ t('admin.plans.billingRateDesc') }}</p>
          <div class="config-card-edit">
            <a-input-number v-model="billingRateDraft" :min="1" :max="1000000" :precision="0" :disabled="!canManagePlan || configLoading" />
            <span class="config-unit">{{ t('admin.plans.configUnit') }}</span>
            <a-button type="primary" size="small" :loading="saving" :disabled="!canManagePlan || billingRateDraft === billingConfig?.value_numeric" @click="handleSaveRate">
              {{ t('admin.plans.saveBillingConfig') }}
            </a-button>
          </div>
        </div>
        <div class="config-card">
          <div class="config-card-head">
            <span class="config-card-title">{{ t('admin.plans.billingPerYuanLabel') }}</span>
            <span class="config-card-badge config-card-badge-adv">{{ t('admin.plans.billingPerYuanBadge') }}</span>
          </div>
          <p class="config-card-desc">{{ t('admin.plans.billingPerYuanDesc') }}</p>
          <div class="config-card-edit">
            <a-input-number v-model="billingPerYuanDraft" :min="1" :max="1000000" :precision="0" :disabled="!canManagePlan || configLoading" />
            <span class="config-unit">{{ t('admin.plans.configYuanUnit') }}</span>
            <a-button type="primary" size="small" :loading="savingPerYuan" :disabled="!canManagePlan || billingPerYuanDraft === billingPerYuanConfig?.value_numeric" @click="handleSavePerYuan">
              {{ t('admin.plans.saveBillingConfig') }}
            </a-button>
          </div>
          <p class="config-card-hint">{{ t('admin.plans.billingPerYuanHint', { impact: perYuanImpact }) }}</p>
        </div>
      </div>
    </section>

    <section class="toolbar panel">
      <a-input v-model="filters.keyword" :placeholder="t('admin.plans.searchPlaceholder')" allow-clear @press-enter="handleSearch" @clear="handleSearch" />
      <a-select v-model="filters.status" :options="statusOptions" class="status-filter" @change="handleSearch" />
      <a-button type="primary" :loading="loading" @click="handleSearch">{{ t('admin.plans.search') }}</a-button>
    </section>

    <section class="panel table-panel">
      <a-table
        :data="plans"
        :loading="loading"
        :pagination="{
          total,
          current: filters.current_page,
          pageSize: filters.page_size,
          showTotal: true,
          showPageSize: true,
        }"
        :row-key="'id'"
        @page-change="onPageChange"
        @page-size-change="(size: number) => { filters.page_size = size; filters.current_page = 1; loadPlans() }"
      >
        <template #columns>
          <a-table-column :title="t('admin.plans.columns.plan')" data-index="name" :width="220">
            <template #cell="{ record }">
              <div class="plan-name">
                <strong>{{ record.name }}</strong>
                <code>{{ record.code }}</code>
              </div>
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.plans.columns.type')" data-index="plan_type" :width="120">
            <template #cell="{ record }">
              <a-tag :color="planTypeTag(record.plan_type)">{{ t(`admin.plans.planType.${record.plan_type}`) }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.plans.columns.price')" data-index="price" :width="110">
            <template #cell="{ record }">
              <span class="price-text">¥{{ record.price }}</span>
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.plans.columns.duration')" data-index="duration_days" :width="90" align="center">
            <template #cell="{ record }">
              {{ record.plan_type === 'membership' ? `${record.duration_days}天` : '-' }}
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.plans.columns.credits')" data-index="grant_token_credits" :width="120" align="right">
            <template #cell="{ record }">{{ record.grant_token_credits.toLocaleString() }}</template>
          </a-table-column>
          <a-table-column :title="t('admin.plans.columns.rate')" data-index="rate" :width="100" align="center">
            <template #cell="{ record }">{{ rateText(record) }}</template>
          </a-table-column>
          <a-table-column :title="t('admin.plans.columns.threshold')" data-index="auto_renew_threshold" :width="100" align="center">
            <template #cell="{ record }">
              {{ record.plan_type === 'credits' ? `${record.auto_renew_threshold_percent}%` : record.plan_type === 'membership' ? `${record.auto_renew_threshold_days}天` : '-' }}
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.plans.columns.purchaseLimit')" data-index="purchase_limit" :width="110" align="center">
            <template #cell="{ record }">{{ limitText(record) }}</template>
          </a-table-column>
          <a-table-column :title="t('admin.plans.columns.refresh')" data-index="quota_refresh_period" :width="100" align="center">
            <template #cell="{ record }">{{ refreshText(record) }}</template>
          </a-table-column>
          <a-table-column :title="t('admin.plans.columns.autoRenew')" data-index="auto_renew_default" :width="100" align="center">
            <template #cell="{ record }">
              <a-tag v-if="record.auto_renew_default" color="purple">{{ t('admin.plans.autoRenewing') }}</a-tag>
              <span v-else>-</span>
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.plans.columns.sort')" data-index="sort_order" :width="80" align="center">
            <template #cell="{ record }">{{ record.sort_order }}</template>
          </a-table-column>
          <a-table-column :title="t('admin.plans.columns.updated')" data-index="updated_at" :width="160">
            <template #cell="{ record }">{{ formatTime(record.updated_at) }}</template>
          </a-table-column>
          <a-table-column :title="t('admin.plans.columns.visible')" data-index="status" :width="130" align="center">
            <template #cell="{ record }">
              <a-switch
                :model-value="record.status === 'active'"
                :disabled="!canManagePlan"
                :loading="saving"
                :checked-text="t('admin.plans.published')"
                :unchecked-text="t('admin.plans.unpublished')"
                @change="handleToggleStatus(record)"
              />
            </template>
          </a-table-column>
          <a-table-column v-if="canManagePlan" :title="t('admin.plans.columns.actions')" :width="130" align="center">
            <template #cell="{ record }">
              <div class="row-actions">
                <a-button size="mini" type="text" @click="openEdit(record)">{{ t('admin.plans.edit') }}</a-button>
                <a-button size="mini" type="text" status="danger" @click="handleDelete(record)">{{ t('admin.plans.delete') }}</a-button>
              </div>
            </template>
          </a-table-column>
        </template>
        <template #empty>
          <a-empty :description="t('admin.plans.emptyText')" />
        </template>
      </a-table>
    </section>

    <a-drawer
      :visible="drawerVisible"
      :title="editingId ? t('admin.plans.editPlan') : t('admin.plans.createPlan')"
      :width="460"
      :footer="false"
      @cancel="drawerVisible = false"
    >
      <div class="plan-form">
        <div class="field-grid two">
          <div class="field">
            <label>{{ t('admin.plans.fields.code') }} <span class="req">*</span></label>
            <a-input v-model="form.code" :placeholder="t('admin.plans.placeholders.code')" :disabled="!!editingId" />
          </div>
          <div class="field">
            <label>{{ t('admin.plans.fields.name') }} <span class="req">*</span></label>
            <a-input v-model="form.name" :placeholder="t('admin.plans.placeholders.name')" />
          </div>
        </div>

        <div class="field">
          <label>{{ t('admin.plans.fields.description') }}</label>
          <a-textarea v-model="form.description" :placeholder="t('admin.plans.placeholders.description')" :auto-size="{ minRows: 2, maxRows: 4 }" />
        </div>

        <div class="field">
          <label>{{ t('admin.plans.fields.planType') }}</label>
          <a-radio-group v-model="form.plan_type" type="button">
            <a-radio v-for="opt in planTypeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</a-radio>
          </a-radio-group>
        </div>

        <div class="field">
          <label>{{ t('admin.plans.fields.price') }} <span class="req">*</span></label>
          <a-input-number v-model="form.price" :min="0" :precision="2" class="full" />
        </div>

        <div v-if="form.plan_type === 'membership'" class="field-grid two">
          <div class="field">
            <label>{{ t('admin.plans.fields.durationDays') }}</label>
            <a-input-number v-model="form.duration_days" :min="0" :precision="0" class="full" />
          </div>
          <div class="field">
            <label>{{ t('admin.plans.fields.grantCredits') }}</label>
            <a-input-number v-model="form.grant_token_credits" :min="0" :precision="0" class="full" />
          </div>
        </div>

        <div v-if="form.plan_type === 'membership'" class="field">
          <label>{{ t('admin.plans.fields.autoRenewDays') }}</label>
          <a-input-number v-model="form.auto_renew_threshold_days" :min="0" :max="3650" :precision="0" class="full" />
        </div>

        <div v-if="form.plan_type === 'membership'" class="field">
          <label>{{ t('admin.plans.fields.quotaRefresh') }}</label>
          <a-select v-model="form.quota_refresh_period" :options="refreshPeriodOptions" />
        </div>

        <div v-if="form.plan_type === 'credits'" class="field-grid two">
          <div class="field">
            <label>{{ t('admin.plans.fields.grantCredits') }}</label>
            <a-input-number v-model="form.grant_token_credits" :min="0" :precision="0" class="full" />
          </div>
          <div class="field">
            <label>{{ t('admin.plans.fields.autoRenewThreshold') }}</label>
            <a-input-number v-model="form.auto_renew_threshold_percent" :min="0" :max="100" :precision="0" class="full" />
          </div>
        </div>

        <p class="hint">{{ planTypeHint }}</p>

        <div v-if="form.plan_type === 'membership' || form.plan_type === 'credits'" class="field">
          <label>{{ t('admin.plans.fields.autoRenewDefault') }}</label>
          <a-switch v-model="form.auto_renew_default" />
        </div>

        <div class="field-grid two">
          <div class="field">
            <label>{{ t('admin.plans.fields.purchaseLimit') }}</label>
            <a-input-number v-model="form.purchase_limit" :min="0" :precision="0" class="full" />
          </div>
          <div class="field">
            <label>{{ t('admin.plans.fields.purchaseLimitPeriod') }}</label>
            <a-select v-model="form.purchase_limit_period" :options="purchasePeriodOptions" />
          </div>
        </div>

        <div class="field-grid two">
          <div class="field">
            <label>{{ t('admin.plans.fields.sortOrder') }}</label>
            <a-input-number v-model="form.sort_order" :min="0" :precision="0" class="full" />
          </div>
          <div class="field">
            <label>{{ t('admin.plans.fields.status') }}</label>
            <a-select v-model="form.status" :options="statusOptions.slice(1)" />
          </div>
        </div>

        <div class="form-actions">
          <a-button @click="drawerVisible = false">{{ t('common.actions.cancel') }}</a-button>
          <a-button type="primary" :loading="saving" @click="handleSave">{{ t('admin.plans.save') }}</a-button>
        </div>
      </div>
    </a-drawer>
  </section>
</template>

<style scoped>
.plans-page {
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

h2 {
  margin: 0;
  font-size: 28px;
}

.page-hero p:not(.page-kicker) {
  margin: 8px 0 0;
  color: #d8e4f7;
  font-size: 13px;
  max-width: 640px;
}

.hero-actions {
  flex-shrink: 0;
}

.panel {
  padding: 18px 20px;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
}

.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
}

.toolbar .status-filter {
  width: 160px;
}

.billing-config-panel {
  padding: 18px 22px;
}

.config-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.config-desc h3 {
  margin: 0;
  font-size: 15px;
}

.config-desc p {
  margin: 4px 0 0;
  color: #667085;
  font-size: 13px;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 14px;
  margin-top: 14px;
}

.config-card {
  padding: 16px;
  border: 1px solid #eaeef5;
  border-radius: 14px;
  background: #fafbfd;
}

.config-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.config-card-title {
  color: #1d2939;
  font-size: 14px;
  font-weight: 600;
}

.config-card-badge {
  padding: 2px 8px;
  border-radius: 999px;
  background: #eef2f7;
  color: #667085;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.config-card-badge-adv {
  background: #eef4ff;
  color: #3f6ad8;
}

.config-card-desc {
  margin: 6px 0 12px;
  color: #667085;
  font-size: 12px;
  line-height: 1.6;
}

.config-card-edit {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.config-card-edit .arco-input-number {
  width: 140px;
}

.config-card-hint {
  margin: 10px 0 0;
  padding: 8px 10px;
  border-radius: 8px;
  background: #fff7e6;
  color: #ad6800;
  font-size: 12px;
  line-height: 1.5;
}

.config-unit {
  color: #667085;
  font-size: 13px;
}

.table-panel {
  padding: 8px 12px;
}

.plan-name {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.plan-name code {
  font-size: 12px;
  color: #667085;
}

.row-actions {
  display: flex;
  justify-content: center;
  gap: 2px;
  white-space: nowrap;
}

.price-text {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.plan-form {
  display: grid;
  gap: 14px;
}

.field-grid {
  display: grid;
  gap: 12px;
}

.field-grid.two {
  grid-template-columns: 1fr 1fr;
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

.full {
  width: 100%;
}

.hint {
  margin: 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f5f8ff;
  color: #4e7ee6;
  font-size: 12px;
  line-height: 1.6;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 6px;
}
</style>