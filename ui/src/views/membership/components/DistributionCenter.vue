<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getDistributionQrcode, getMyDistribution, listMyCommissions, listSubordinates, updateReferralCode } from '@/services/distribution'
import { type DistributionCommission, type DistributionSubordinate, type MyDistribution } from '@/models/distribution'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()

const SUB_PAGE_SIZE = 10
const COMMISSION_PAGE_SIZE = 10

const loading = ref(false)
const summary = ref<MyDistribution | null>(null)
const newCode = ref('')
const editingCode = ref(false)
const updatingCode = ref(false)

const qrcodeUrl = ref('')
const shareUrl = ref('')

const subordinates = ref<DistributionSubordinate[]>([])
const subordinateTotal = ref(0)
const subordinatePage = ref(1)

const commissions = ref<DistributionCommission[]>([])
const commissionTotal = ref(0)
const commissionPage = ref(1)

const loadSummary = async () => {
  loading.value = true
  try {
    summary.value = await getMyDistribution()
    const qrcode = await getDistributionQrcode()
    qrcodeUrl.value = qrcode.qrcode_url || ''
    shareUrl.value = qrcode.share_url || summary.value?.share_url || ''
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.distribution.loadFailed')))
  } finally {
    loading.value = false
  }
}

const loadSubordinates = async () => {
  try {
    const result = await listSubordinates({ current_page: subordinatePage.value, page_size: SUB_PAGE_SIZE })
    subordinates.value = result.list || []
    subordinateTotal.value = result.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.distribution.loadSubordinatesFailed')))
  }
}

const loadCommissions = async () => {
  try {
    const result = await listMyCommissions({ current_page: commissionPage.value, page_size: COMMISSION_PAGE_SIZE })
    commissions.value = result.list || []
    commissionTotal.value = result.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.distribution.loadCommissionsFailed')))
  }
}

const startEditCode = () => {
  newCode.value = summary.value?.referral_code || ''
  editingCode.value = true
}

const cancelEditCode = () => {
  editingCode.value = false
  newCode.value = ''
}

const handleUpdateCode = async () => {
  const code = newCode.value.trim()
  if (!code) {
    Message.error(t('membership.distribution.codeRequired'))
    return
  }
  updatingCode.value = true
  try {
    summary.value = await updateReferralCode(code)
    editingCode.value = false
    newCode.value = ''
    Message.success(t('membership.distribution.codeUpdated'))
  } catch (error) {
    Message.error(getErrorMessage(error, t('membership.distribution.updateCodeFailed')))
  } finally {
    updatingCode.value = false
  }
}

const handleCopyShareUrl = async () => {
  const url = shareUrl.value
  if (!url) return
  try {
    await navigator.clipboard.writeText(url)
    Message.success(t('membership.distribution.copied'))
  } catch {
    Message.error(t('membership.distribution.copyFailed'))
  }
}

const onSubordinatePageChange = async (page: number) => {
  subordinatePage.value = page
  await loadSubordinates()
}

const onCommissionPageChange = async (page: number) => {
  commissionPage.value = page
  await loadCommissions()
}

const formatTime = (value: number | null) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const formatSource = (source: string) => {
  return t(`membership.distribution.source.${source}`)
}

const formatCommissionSource = (source: string) => {
  return t(`membership.distribution.commissionSource.${source}`)
}

onMounted(() => {
  loadSummary()
  loadSubordinates()
  loadCommissions()
})

onBeforeUnmount(() => {
  if (qrcodeUrl.value) {
    URL.revokeObjectURL(qrcodeUrl.value)
  }
})
</script>

<template>
  <section class="panel" :aria-busy="loading">
    <div class="panel-header">
      <div>
        <h3>{{ t('membership.distribution.title') }}</h3>
        <p>{{ t('membership.distribution.description') }}</p>
      </div>
      <a-tag v-if="summary?.high_rate_locked" color="gold">{{ t('membership.distribution.highRateLocked') }}</a-tag>
    </div>

    <div class="dist-grid">
      <div class="dist-main">
        <div class="rate-line">
          <span>{{ t('membership.distribution.commissionRate') }}</span>
          <strong>{{ summary?.commission_rate || '0.00' }}%</strong>
          <span v-if="summary?.superior">{{ t('membership.distribution.superior', { name: summary.superior.name }) }}</span>
          <span v-else>{{ t('membership.distribution.noSuperior') }}</span>
        </div>

        <div class="code-row">
          <template v-if="!editingCode">
            <code class="referral-code">{{ summary?.referral_code || '-' }}</code>
            <a-button size="mini" type="primary" @click="startEditCode">{{ t('membership.distribution.editCode') }}</a-button>
          </template>
          <template v-else>
            <a-input v-model="newCode" :placeholder="t('membership.distribution.codePlaceholder')" />
            <a-button size="mini" type="primary" :loading="updatingCode" @click="handleUpdateCode">{{ t('common.actions.save') }}</a-button>
            <a-button size="mini" @click="cancelEditCode">{{ t('common.actions.cancel') }}</a-button>
          </template>
        </div>

        <div class="share-row">
          <span class="share-url">{{ shareUrl || summary?.share_url || '-' }}</span>
          <a-button size="mini" @click="handleCopyShareUrl">{{ t('membership.distribution.copyLink') }}</a-button>
        </div>

        <img v-if="qrcodeUrl" :src="qrcodeUrl" class="qrcode" alt="referral qrcode" />
      </div>

      <div class="dist-side">
        <div class="stat-item">
          <span>{{ t('membership.distribution.subordinateCount') }}</span>
          <strong>{{ summary?.subordinate_count ?? 0 }}</strong>
        </div>
      </div>
    </div>

    <div class="sub-lists">
      <section class="sub-section">
        <h4>{{ t('membership.distribution.subordinatesTitle') }}</h4>
        <article v-for="item in subordinates" :key="item.id" class="tx-row compact">
          <div>
            <strong>{{ item.name }}</strong>
            <p v-if="item.email">{{ item.email }}</p>
            <p>{{ formatSource(item.source) }} · {{ formatTime(item.bound_at) }}</p>
          </div>
        </article>
        <p v-if="subordinates.length === 0" class="empty-text">{{ t('membership.distribution.noSubordinates') }}</p>
        <a-pagination
          v-if="subordinateTotal > SUB_PAGE_SIZE"
          :total="subordinateTotal"
          :current="subordinatePage"
          :page-size="SUB_PAGE_SIZE"
          @change="onSubordinatePageChange"
        />
      </section>

      <section class="sub-section">
        <h4>{{ t('membership.distribution.commissionsTitle') }}</h4>
        <article v-for="item in commissions" :key="item.id" class="tx-row compact">
          <div>
            <strong>{{ item.description }}</strong>
            <p>{{ formatCommissionSource(item.source) }} · {{ item.rate != null ? `${item.rate}%` : '-' }} · {{ formatTime(item.created_at) }}</p>
          </div>
          <span class="amount">+¥{{ Number(item.amount || 0).toFixed(2) }}</span>
        </article>
        <p v-if="commissions.length === 0" class="empty-text">{{ t('membership.distribution.noCommissions') }}</p>
        <a-pagination
          v-if="commissionTotal > COMMISSION_PAGE_SIZE"
          :total="commissionTotal"
          :current="commissionPage"
          :page-size="COMMISSION_PAGE_SIZE"
          @change="onCommissionPageChange"
        />
      </section>
    </div>
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
.panel-header p,
h4 {
  margin: 0;
}

.panel-header p {
  margin-top: 6px;
  color: var(--aicss-muted);
  font-size: 13px;
}

.dist-grid {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 16px;
  margin-top: 16px;
}

.rate-line {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.rate-line span,
.rate-line strong {
  color: var(--aicss-muted);
}

.rate-line strong {
  font-size: 26px;
  color: var(--aicss-accent-text);
}

.code-row,
.share-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.referral-code {
  padding: 6px 12px;
  border-radius: var(--aicss-radius);
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
  font-weight: 650;
}

.share-url {
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--aicss-muted);
  font-size: 13px;
}

.qrcode {
  width: 132px;
  height: 132px;
  margin-top: 14px;
  border-radius: var(--aicss-radius);
  border: 1px solid var(--aicss-border);
}

.stat-item {
  min-width: 150px;
  padding: 16px;
  border-radius: var(--aicss-radius);
  border: 1px solid var(--aicss-border);
  background: var(--aicss-bg-subtle);
}

.stat-item span {
  color: var(--aicss-muted);
  font-size: 13px;
}

.stat-item strong {
  display: block;
  margin-top: 6px;
  font-size: 26px;
  color: var(--aicss-accent-text);
}

.sub-lists {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-top: 16px;
}

.sub-section {
  padding: 16px;
  border-radius: var(--aicss-radius);
  border: 1px solid var(--aicss-border);
  background: var(--aicss-bg-subtle);
}

.sub-section h4 {
  margin-bottom: 8px;
  color: var(--aicss-text);
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

.tx-row .amount {
  color: var(--aicss-success);
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

.empty-text {
  margin: 8px 0 0;
  color: var(--aicss-muted);
  font-size: 13px;
}

@media (max-width: 860px) {
  .dist-grid,
  .sub-lists {
    grid-template-columns: 1fr;
  }
}
</style>