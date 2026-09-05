<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useAdminStore } from '@/stores/admin'
import { listAdminWithdrawals, reviewWithdrawal } from '@/services/admin-commerce'
import { type WithdrawalRecord } from '@/models/commerce'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()
const adminStore = useAdminStore()
const canManageWithdraw = computed(() => adminStore.hasPermission('withdraw:manage'))

const loading = ref(false)
const actionLoading = ref(false)
const withdrawals = ref<WithdrawalRecord[]>([])
const total = ref(0)
const filters = ref({ status: '' as string, current_page: 1, page_size: 20 })

const reviewing = ref<{ record: WithdrawalRecord; action: 'approve' | 'reject' } | null>(null)
const note = ref('')

const statusOptions = computed(() => [
  { label: t('admin.withdrawals.allStatus'), value: '' },
  { label: t('membership.status.withdraw.pending'), value: 'pending' },
  { label: t('membership.status.withdraw.approved'), value: 'approved' },
  { label: t('membership.status.withdraw.rejected'), value: 'rejected' },
  { label: t('membership.status.withdraw.cancelled'), value: 'cancelled' },
])

const modalTitle = computed(() => {
  if (!reviewing.value) return ''
  return reviewing.value.action === 'approve'
    ? t('admin.withdrawals.approveTitle')
    : t('admin.withdrawals.rejectTitle')
})

const loadWithdrawals = async () => {
  loading.value = true
  try {
    const result = await listAdminWithdrawals(filters.value)
    withdrawals.value = result.list || []
    total.value = result.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.withdrawals.loadFailed')))
  } finally {
    loading.value = false
  }
}

const handleSearch = async () => {
  filters.value.current_page = 1
  await loadWithdrawals()
}

const onPageChange = async (page: number) => {
  filters.value.current_page = page
  await loadWithdrawals()
}

const openReview = (record: WithdrawalRecord, action: 'approve' | 'reject') => {
  reviewing.value = { record, action }
  note.value = ''
}

const closeReview = () => {
  reviewing.value = null
  note.value = ''
}

const submitReview = async () => {
  if (!reviewing.value) return
  actionLoading.value = true
  try {
    await reviewWithdrawal(reviewing.value.record.id, reviewing.value.action, note.value.trim())
    Message.success(
      reviewing.value.action === 'approve'
        ? t('admin.withdrawals.approved')
        : t('admin.withdrawals.rejected'),
    )
    closeReview()
    await loadWithdrawals()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.withdrawals.reviewFailed')))
  } finally {
    actionLoading.value = false
  }
}

const formatTime = (value: number | null) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const formatStatus = (status: string) => {
  return t(`membership.status.withdraw.${status}`) || status
}

const copyUserId = async (id: string) => {
  try {
    await navigator.clipboard.writeText(id)
    Message.success(t('admin.withdrawals.idCopied'))
  } catch {
    Message.error(t('admin.withdrawals.copyFailed'))
  }
}

onMounted(loadWithdrawals)
</script>

<template>
  <section class="withdrawals-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Withdrawals</p>
        <h2>{{ t('admin.withdrawals.title') }}</h2>
        <p>{{ t('admin.withdrawals.description') }}</p>
      </div>
    </header>

    <section class="filter-panel">
      <a-select v-model="filters.status" :options="statusOptions" :placeholder="t('admin.withdrawals.statusPlaceholder')" />
      <a-button type="primary" :loading="loading" @click="handleSearch">{{ t('admin.withdrawals.search') }}</a-button>
    </section>

    <section class="panel">
      <a-table :loading="loading" :data="withdrawals" :pagination="false" :bordered="{ wrapper: true, cell: true }" row-key="id">
        <template #columns>
          <a-table-column :title="t('admin.withdrawals.user')" data-index="account_id">
            <template #cell="{ record }">
              <div class="cell-stack">
                <span>{{ record.user_name || record.user_email || '-' }}</span>
                <span v-if="record.user_email && record.user_name" class="cell-sub">{{ record.user_email }}</span>
                <div class="cell-id-row">
                  <code class="cell-id">{{ record.account_id }}</code>
                  <a-button size="mini" type="text" @click="copyUserId(record.account_id)">{{ t('admin.withdrawals.copyId') }}</a-button>
                </div>
              </div>
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.withdrawals.amount')" data-index="amount">
            <template #cell="{ record }">
              ¥{{ Number(record.amount || 0).toFixed(2) }}
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.withdrawals.status')" data-index="status">
            <template #cell="{ record }">
              <a-tag>{{ formatStatus(record.status) }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.withdrawals.reviewNote')" data-index="review_note">
            <template #cell="{ record }">
              {{ record.review_note || '-' }}
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.withdrawals.createdAt')" data-index="created_at">
            <template #cell="{ record }">
              {{ formatTime(record.created_at) }}
            </template>
          </a-table-column>
          <a-table-column v-if="canManageWithdraw" :title="t('admin.withdrawals.actions')" :width="180">
            <template #cell="{ record }">
              <a-space v-if="record.status === 'pending'">
                <a-button size="mini" type="primary" @click="openReview(record, 'approve')">{{ t('admin.withdrawals.approve') }}</a-button>
                <a-button size="mini" status="danger" @click="openReview(record, 'reject')">{{ t('admin.withdrawals.reject') }}</a-button>
              </a-space>
            </template>
          </a-table-column>
        </template>
      </a-table>
      <div class="pager">
        <a-pagination
          :total="total"
          :current="filters.current_page"
          :page-size="filters.page_size"
          show-total
          @change="onPageChange"
        />
      </div>
    </section>

    <a-modal
      :visible="!!reviewing"
      :title="modalTitle"
      :ok-loading="actionLoading"
      :ok-text="t('common.actions.confirm')"
      @ok="submitReview"
      @cancel="closeReview"
    >
      <div class="review-form">
        <p v-if="reviewing" class="target-line">
          {{ reviewing.record.user_name || reviewing.record.user_email || reviewing.record.account_id }} · ¥{{ Number(reviewing.record.amount || 0).toFixed(2) }}
        </p>
        <a-textarea
          v-model="note"
          :placeholder="t('admin.withdrawals.notePlaceholder')"
          :max-length="1024"
          show-word-limit
        />
      </div>
    </a-modal>
  </section>
</template>

<style scoped>
.withdrawals-page {
  display: grid;
  gap: 20px;
}

.page-header,
.panel,
.filter-panel {
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

.page-header p:not(.page-kicker) {
  margin-top: 8px;
  color: #d8e4f7;
}

.filter-panel {
  display: grid;
  grid-template-columns: 220px auto;
  gap: 12px;
  box-shadow: none;
  border: 1px solid #eef2f7;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.review-form {
  display: grid;
  gap: 12px;
}

.cell-stack {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cell-sub {
  color: #667085;
  font-size: 12px;
}

.cell-id-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.cell-id {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 11px;
  color: #98a2b3;
}

.target-line {
  color: #101828;
  font-weight: 600;
}
</style>