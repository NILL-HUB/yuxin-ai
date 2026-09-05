<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { createAutoRenewal, listAutoRenewals, listPlans, setAutoRenewalStatus } from '@/services/commerce'
import { type AutoRenewal, type CommercePlan } from '@/models/commerce'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()

const loading = ref(false)
const actionLoading = ref(false)
const items = ref<AutoRenewal[]>([])
const plans = ref<CommercePlan[]>([])

const enableModalVisible = ref(false)
const selectedPlanId = ref('')
const selectedPayMethod = ref('balance')

const renewablePlans = computed(() =>
  plans.value.filter((plan) => plan.status === 'active' && (plan.plan_type === 'membership' || plan.plan_type === 'credits')),
)

const loadData = async () => {
  loading.value = true
  try {
    const [renewals, planResult] = await Promise.all([listAutoRenewals(), listPlans({ current_page: 1, page_size: 50, status: 'active' })])
    items.value = renewals.list || []
    plans.value = planResult.list || []
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.autoRenewal.loadFailed')))
  } finally {
    loading.value = false
  }
}

const openEnableModal = () => {
  selectedPlanId.value = ''
  selectedPayMethod.value = 'balance'
  enableModalVisible.value = true
}

const closeEnableModal = () => {
  enableModalVisible.value = false
}

const handleEnable = async () => {
  if (!selectedPlanId.value) {
    Message.error(t('membership.autoRenewal.planRequired'))
    return
  }
  actionLoading.value = true
  try {
    await createAutoRenewal(selectedPlanId.value, selectedPayMethod.value)
    Message.success(t('membership.autoRenewal.enabled'))
    closeEnableModal()
    await loadData()
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.autoRenewal.enableFailed')))
  } finally {
    actionLoading.value = false
  }
}

const handleAction = async (item: AutoRenewal, action: 'pause' | 'resume' | 'cancel') => {
  actionLoading.value = true
  try {
    await setAutoRenewalStatus(item.id, action)
    Message.success(t(`membership.autoRenewal.actionDone.${action}`))
    await loadData()
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.autoRenewal.actionFailed')))
  } finally {
    actionLoading.value = false
  }
}

const formatTime = (value: number | null) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const formatStatus = (status: string) => {
  return t(`membership.status.autoRenewal.${status}`) || status
}

const formatPlanType = (planType: string) => {
  return t(`membership.status.planType.${planType}`) || planType
}

const formatTrigger = (item: AutoRenewal) => {
  if (item.plan_type === 'membership') return t('membership.autoRenewal.triggerExpiryDays', { days: item.threshold_days ?? 1 })
  if (item.plan_type === 'credits') return t('membership.autoRenewal.triggerThreshold', { percent: item.threshold_percent ?? 5 })
  return item.trigger || '-'
}

onMounted(loadData)
</script>

<template>
  <section class="panel">
    <div class="panel-header">
      <div>
        <h3>{{ t('membership.autoRenewal.title') }}</h3>
        <p>{{ t('membership.autoRenewal.description') }}</p>
      </div>
      <a-button type="primary" @click="openEnableModal">{{ t('membership.autoRenewal.enable') }}</a-button>
    </div>

    <article v-for="item in items" :key="item.id" class="renewal-row">
      <div>
        <strong>{{ item.plan_name || formatPlanType(item.plan_type) }}</strong>
        <p>
          {{ formatPlanType(item.plan_type) }} · {{ t('membership.status.payMethod.balance') }} · {{ formatTrigger(item) }}
        </p>
        <p class="renewal-meta">
          {{ t('membership.autoRenewal.nextRenewAt', { time: formatTime(item.next_renew_at) }) }}
          · {{ t('membership.autoRenewal.lastRenewedAt', { time: formatTime(item.last_renewed_at) }) }}
          · {{ t('membership.autoRenewal.renewCount', { count: item.renew_count }) }}
          <template v-if="item.fail_count > 0"> · {{ t('membership.autoRenewal.failCount', { count: item.fail_count }) }}</template>
        </p>
      </div>
      <div class="renewal-actions">
        <a-tag>{{ formatStatus(item.status) }}</a-tag>
        <a-button v-if="item.status === 'active'" size="mini" @click="handleAction(item, 'pause')">{{ t('membership.autoRenewal.pause') }}</a-button>
        <a-button v-if="item.status === 'paused'" size="mini" type="primary" @click="handleAction(item, 'resume')">{{ t('membership.autoRenewal.resume') }}</a-button>
        <a-button v-if="item.status === 'active' || item.status === 'paused'" size="mini" status="warning" @click="handleAction(item, 'cancel')">{{ t('membership.autoRenewal.cancel') }}</a-button>
      </div>
    </article>

    <p v-if="!loading && items.length === 0" class="empty-text">{{ t('membership.autoRenewal.empty') }}</p>

    <a-modal
      :visible="enableModalVisible"
      :title="t('membership.autoRenewal.enableTitle')"
      :ok-loading="actionLoading"
      @ok="handleEnable"
      @cancel="closeEnableModal"
    >
      <div class="enable-form">
        <a-select
          v-model="selectedPlanId"
          :placeholder="t('membership.autoRenewal.planPlaceholder')"
          :options="renewablePlans.map((plan) => ({ label: `${plan.name} · ${t(`membership.status.planType.${plan.plan_type}`)} · ¥${Number(plan.price).toFixed(2)}`, value: plan.id }))"
          :loading="loading"
        />
        <a-radio-group v-model="selectedPayMethod" type="button">
          <a-radio value="balance">{{ t('membership.balance.payMethod.balance') }}</a-radio>
        </a-radio-group>
        <p class="hint">{{ t('membership.autoRenewal.balanceOnlyHint') }}</p>
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

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
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

.renewal-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 14px 0;
  border-top: 1px solid var(--aicss-border);
}

.renewal-row:first-of-type {
  margin-top: 10px;
}

.renewal-row strong {
  color: var(--aicss-text);
}

.renewal-row p {
  margin: 4px 0 0;
  color: var(--aicss-muted);
  font-size: 13px;
}

.renewal-meta {
  font-size: 12px;
}

.renewal-actions {
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

.enable-form {
  display: grid;
  gap: 12px;
}

.hint {
  margin: 0;
  color: var(--aicss-muted);
  font-size: 13px;
}

@media (max-width: 640px) {
  .renewal-row {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }

  .renewal-row > div:first-child {
    min-width: 0;
  }

  .renewal-row strong,
  .renewal-row p {
    word-break: break-all;
  }

  .renewal-actions {
    justify-content: flex-end;
  }
}
</style>