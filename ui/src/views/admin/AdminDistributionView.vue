<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getDistributionOverview, listDistributionCommissions, listDistributionRelations } from '@/services/admin-commerce'
import { listCustomerUsers } from '@/services/admin-customer-users'
import { type AdminDistributionOverview, type AdminDistributionRelation, type DistributionCommission } from '@/models/distribution'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()
const router = useRouter()

const loading = ref(false)
const overview = ref<AdminDistributionOverview | null>(null)

const distributionEnabled = computed(() => !!overview.value?.distribution_enabled)
const goFeatureFlags = () => {
  router.push('/admin/orchestration-flags')
}

const relations = ref<AdminDistributionRelation[]>([])
const relationsTotal = ref(0)
const relationFilter = ref({ inviter_id: '', current_page: 1, page_size: 20 })
const inviterOptions = ref<{ label: string; value: string }[]>([])

const commissions = ref<DistributionCommission[]>([])
const commissionsTotal = ref(0)
const commissionFilter = ref({ user_id: '', current_page: 1, page_size: 20 })
const commissionUserOptions = ref<{ label: string; value: string }[]>([])

const loadOverview = async () => {
  try {
    overview.value = await getDistributionOverview()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.distribution.loadOverviewFailed')))
  }
}

const loadRelations = async () => {
  loading.value = true
  try {
    const result = await listDistributionRelations(relationFilter.value)
    relations.value = result.list || []
    relationsTotal.value = result.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.distribution.loadRelationsFailed')))
  } finally {
    loading.value = false
  }
}

const loadCommissions = async () => {
  loading.value = true
  try {
    const result = await listDistributionCommissions({ ...commissionFilter.value, current_page: commissionFilter.value.current_page, page_size: commissionFilter.value.page_size })
    commissions.value = result.list || []
    commissionsTotal.value = result.paginator?.total_record || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.distribution.loadCommissionsFailed')))
  } finally {
    loading.value = false
  }
}

const onCommissionUserSearch = async (keyword: string) => {
  try {
    const response = await listCustomerUsers({ keyword, status: '', current_page: 1, page_size: 20 })
    commissionUserOptions.value = (response.list || []).map((user) => ({
      label: `${user.name || user.email || user.id}${user.email && user.name ? ` · ${user.email}` : ''}`,
      value: user.id,
    }))
  } catch {
    commissionUserOptions.value = []
  }
}

const onInviterSearch = async (keyword: string) => {
  try {
    const response = await listCustomerUsers({ keyword, status: '', current_page: 1, page_size: 20 })
    inviterOptions.value = (response.list || []).map((user) => ({
      label: `${user.name || user.email || user.id}${user.email && user.name ? ` · ${user.email}` : ''}`,
      value: user.id,
    }))
  } catch {
    inviterOptions.value = []
  }
}

const queryRelations = async () => {
  relationFilter.value.current_page = 1
  await loadRelations()
}

const queryCommissions = async () => {
  commissionFilter.value.current_page = 1
  await loadCommissions()
}

const onRelationsPageChange = async (page: number) => {
  relationFilter.value.current_page = page
  await loadRelations()
}

const onCommissionsPageChange = async (page: number) => {
  commissionFilter.value.current_page = page
  await loadCommissions()
}

const formatTime = (value: number | null) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

const formatSource = (source: string) => {
  return t(`membership.distribution.source.${source}`) || source
}

const formatCommissionSource = (source: string) => {
  return t(`membership.distribution.commissionSource.${source}`) || source
}

const formatRate = (rate: number | null) => {
  if (rate == null) return '-'
  return `${Number(rate)}%`
}

onMounted(async () => {
  await loadOverview()
  await Promise.all([loadRelations(), loadCommissions()])
})
</script>

<template>
  <section class="distribution-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Distribution</p>
        <h2>{{ t('admin.distribution.title') }}</h2>
        <p>{{ t('admin.distribution.description') }}</p>
      </div>
      <div class="header-status">
        <a-tag :color="distributionEnabled ? 'green' : 'gray'" size="medium" class="status-badge">
          {{ distributionEnabled ? t('admin.distribution.enabledBadge') : t('admin.distribution.disabledBadge') }}
        </a-tag>
        <a-button :type="distributionEnabled ? 'secondary' : 'primary'" size="small" @click="goFeatureFlags">
          {{ t('admin.distribution.gotoFlags') }}
        </a-button>
      </div>
    </header>

    <section class="stats-grid">
      <div class="stat-card">
        <span>{{ t('admin.distribution.boundUsers') }}</span>
        <strong>{{ overview?.bound_users ?? 0 }}</strong>
      </div>
      <div class="stat-card">
        <span>{{ t('admin.distribution.commissionTotal') }}</span>
        <strong>¥{{ Number(overview?.commission_total ?? 0).toFixed(2) }}</strong>
      </div>
      <div class="stat-card">
        <span>{{ t('admin.distribution.monthCommission') }}</span>
        <strong>¥{{ Number(overview?.month_commission ?? 0).toFixed(2) }}</strong>
      </div>
      <div class="stat-card">
        <span>{{ t('admin.distribution.inviterUsers') }}</span>
        <strong>{{ overview?.inviter_users ?? 0 }}</strong>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title-row">
        <h3>{{ t('admin.distribution.relationsTitle') }}</h3>
        <div class="filter-form">
          <a-select
            v-model="relationFilter.inviter_id"
            :options="inviterOptions"
            allow-search
            allow-clear
            :filter-option="false"
            :placeholder="t('admin.distribution.inviterSelectPlaceholder')"
            @search="onInviterSearch"
          />
          <a-button :loading="loading" @click="queryRelations">{{ t('admin.distribution.search') }}</a-button>
        </div>
      </div>
      <a-table :loading="loading" :data="relations" :pagination="false" :bordered="{ wrapper: true, cell: true }" row-key="id">
        <template #columns>
          <a-table-column :title="t('admin.distribution.user')" data-index="name">
            <template #cell="{ record }">
              <div class="cell-stack">
                <span>{{ record.name || '-' }}</span>
                <span v-if="record.email" class="cell-sub">{{ record.email }}</span>
              </div>
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.distribution.inviter')" data-index="inviter_id">
            <template #cell="{ record }">
              <div class="cell-stack">
                <span>{{ record.inviter_name || '-' }}</span>
                <span v-if="record.inviter_email" class="cell-sub">{{ record.inviter_email }}</span>
                <code class="cell-id">{{ record.inviter_id }}</code>
              </div>
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.distribution.source')" data-index="source">
            <template #cell="{ record }">
              {{ formatSource(record.source) }}
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.distribution.boundAt')" data-index="bound_at">
            <template #cell="{ record }">
              {{ formatTime(record.bound_at) }}
            </template>
          </a-table-column>
        </template>
      </a-table>
      <div class="pager">
        <a-pagination
          :total="relationsTotal"
          :current="relationFilter.current_page"
          :page-size="relationFilter.page_size"
          show-total
          @change="onRelationsPageChange"
        />
      </div>
    </section>

    <section class="panel">
      <div class="panel-title-row">
        <h3>{{ t('admin.distribution.commissionsTitle') }}</h3>
        <div class="filter-form">
          <a-select
            v-model="commissionFilter.user_id"
            :options="commissionUserOptions"
            allow-search
            allow-clear
            :filter-option="false"
            :placeholder="t('admin.distribution.commissionUserPlaceholder')"
            @search="onCommissionUserSearch"
            @clear="queryCommissions"
          />
          <a-button :loading="loading" @click="queryCommissions">{{ t('admin.distribution.search') }}</a-button>
        </div>
      </div>
      <p class="empty-hint">{{ t('admin.distribution.commissionAllHint') }}</p>
      <a-table :loading="loading" :data="commissions" :pagination="false" :bordered="{ wrapper: true, cell: true }" row-key="id">
        <template #columns>
          <a-table-column :title="t('admin.distribution.user')" data-index="account_name">
            <template #cell="{ record }">
              {{ record.account_name || '-' }}
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.distribution.amount')" data-index="amount">
            <template #cell="{ record }">
              ¥{{ Number(record.amount || 0).toFixed(2) }}
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.distribution.rate')" data-index="rate">
            <template #cell="{ record }">
              {{ formatRate(record.rate) }}
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.distribution.source')" data-index="source">
            <template #cell="{ record }">
              {{ formatCommissionSource(record.source) }}
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.distribution.descriptionCol')" data-index="description" />
          <a-table-column :title="t('admin.distribution.createdAt')" data-index="created_at">
            <template #cell="{ record }">
              {{ formatTime(record.created_at) }}
            </template>
          </a-table-column>
        </template>
      </a-table>
      <div class="pager">
        <a-pagination
          :total="commissionsTotal"
          :current="commissionFilter.current_page"
          :page-size="commissionFilter.page_size"
          show-total
          @change="onCommissionsPageChange"
        />
      </div>
    </section>
  </section>
</template>

<style scoped>
.distribution-page {
  display: grid;
  gap: 20px;
}

.page-header,
.panel {
  padding: 24px;
  border-radius: 22px;
  background: #fff;
  box-shadow: 0 14px 40px rgba(15, 23, 42, 0.06);
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  background: linear-gradient(135deg, #101828, #36527e);
  color: #fff;
}

.header-status {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.status-badge {
  font-weight: 600;
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

.stats-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 14px;
}

.stat-card {
  padding: 18px 20px;
  border-radius: 16px;
  border: 1px solid #eef2f7;
  background: #fff;
}

.stat-card span {
  color: #667085;
  font-size: 13px;
}

.stat-card strong {
  display: block;
  margin-top: 8px;
  font-size: 24px;
  color: #101828;
  font-variant-numeric: tabular-nums;
}

.panel-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.filter-form {
  display: flex;
  gap: 8px;
  align-items: center;
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

.cell-id {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 11px;
  color: #98a2b3;
}

.empty-hint {
  margin: 0 0 12px;
  padding: 12px 16px;
  border-radius: 10px;
  background: #f8fafc;
  color: #98a2b3;
  font-size: 13px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

@media (max-width: 960px) {
  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>