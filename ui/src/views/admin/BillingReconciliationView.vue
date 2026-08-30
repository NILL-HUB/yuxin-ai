<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import type { BillingReconciliation, MarginSummary, MarginSummaryItem } from '@/models/billing-reconciliation'
import { getMarginSummary, listReconciliations } from '@/services/admin-billing-reconciliation'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()

const loading = ref(false)
const marginSummary = ref<MarginSummary>({
  list: [],
  total_margin: 0,
  total_actual: 0,
  overall: { actual_credits: 0, cost_credits: 0, margin_credits: 0 },
  by_tier: [],
  cached_input_tokens_total: 0,
})
const reconciliations = ref<BillingReconciliation[]>([])

const totalCost = computed(() =>
  marginSummary.value.list.reduce((sum, item) => sum + (Number(item.cost) || 0), 0),
)
const marginClass = computed(() =>
  marginSummary.value.total_margin < 0 ? 'text-red-600' : 'text-green-600',
)
const alertCount = computed(() =>
  reconciliations.value.reduce((sum, record) => sum + (record.alert_flags?.length || 0), 0),
)
const tierSummary = computed(() => marginSummary.value.by_tier ?? [])
const cachedInputTokensTotal = computed(() => marginSummary.value.cached_input_tokens_total ?? 0)

// 毛利 = 实际（售价）算力 - 成本算力；对账行不落模型级毛利时前端兜底计算
const marginOf = (record: MarginSummaryItem) =>
  (Number(record.actual) || 0) - (Number(record.cost) || 0)

const loadMargin = async () => {
  try {
    marginSummary.value = await getMarginSummary()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.reconcile.loadFailed')))
  }
}

const loadList = async () => {
  loading.value = true
  try {
    const result = await listReconciliations({ current_page: 1, page_size: 20 })
    reconciliations.value = result.list
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.reconcile.loadFailed')))
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadMargin()
  loadList()
})
</script>

<template>
  <section class="billing-reconciliation-page" :aria-busy="loading">
    <header class="page-hero">
      <div>
        <p class="page-kicker">Billing Reconcile</p>
        <h2>{{ t('admin.reconcile.title') }}</h2>
        <p>{{ t('admin.reconcile.description') }}</p>
      </div>
    </header>

    <div class="grid gap-4 md:grid-cols-4">
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.reconcile.stats.totalActual') }}</p>
        <strong class="text-xl">{{ marginSummary.total_actual }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.reconcile.stats.totalCost') }}</p>
        <strong class="text-xl">{{ totalCost }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.reconcile.stats.margin') }}</p>
        <strong class="text-xl" :class="marginClass">{{ marginSummary.total_margin }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.reconcile.stats.alertCount') }}</p>
        <strong class="text-xl text-red-600">{{ alertCount }}</strong>
      </article>
    </div>

    <section class="panel mt-4">
      <h3 class="panel-title">{{ t('admin.reconcile.marginByModel') }}</h3>
      <a-table :data="marginSummary.list" :loading="loading" :pagination="false" row-key="model_name">
        <template #columns>
          <a-table-column :title="t('admin.reconcile.columns.model')" data-index="model_name" />
          <a-table-column :title="t('admin.reconcile.columns.calls')" data-index="calls" align="right" />
          <a-table-column :title="t('admin.reconcile.columns.actual')" data-index="actual" align="right" />
          <a-table-column :title="t('admin.reconcile.columns.cost')" data-index="cost" align="right" />
          <a-table-column :title="t('admin.reconcile.columns.margin')" align="right">
            <template #cell="{ record }">
              <a-tag :color="marginOf(record) >= 0 ? 'green' : 'red'">{{ marginOf(record) }}</a-tag>
            </template>
          </a-table-column>
        </template>
      </a-table>
      <p v-if="marginSummary.list.length === 0" class="empty-text">{{ t('admin.reconcile.emptyMargin') }}</p>
    </section>

    <section class="panel mt-4">
      <h3 class="panel-title">按档位汇总</h3>
      <a-table :data="tierSummary" :pagination="false" size="small" row-key="tier">
        <template #columns>
          <a-table-column title="档位" data-index="tier" />
          <a-table-column title="调用次数" data-index="calls" align="right" />
          <a-table-column title="实际算力" data-index="actual_credits" align="right" />
          <a-table-column title="成本算力" data-index="cost_credits" align="right" />
          <a-table-column title="毛利" data-index="margin_credits" align="right" />
        </template>
      </a-table>
      <p class="empty-text">缓存命中输入 Token 合计：{{ cachedInputTokensTotal }}</p>
    </section>

    <section class="panel mt-4">
      <h3 class="panel-title">{{ t('admin.reconcile.settleRecords') }}</h3>
      <a-table :data="reconciliations" :loading="loading" :pagination="false" row-key="id">
        <template #columns>
          <a-table-column :title="t('admin.reconcile.columns.taskId')" data-index="task_id">
            <template #cell="{ record }"><code class="text-xs">{{ (record.task_id || '').slice(0, 12) }}…</code></template>
          </a-table-column>
          <a-table-column :title="t('admin.reconcile.columns.estimated')" data-index="estimated_credits" align="right" />
          <a-table-column :title="t('admin.reconcile.columns.actual')" data-index="actual_credits" align="right" />
          <a-table-column :title="t('admin.reconcile.columns.diff')" data-index="diff_credits" align="right">
            <template #cell="{ record }">
              <span :class="record.diff_credits > 0 ? 'text-amber-600' : record.diff_credits < 0 ? 'text-green-600' : 'text-gray-400'">{{ record.diff_credits }}</span>
            </template>
          </a-table-column>
          <a-table-column :title="t('admin.reconcile.columns.alerts')" data-index="alert_flags">
            <template #cell="{ record }">
              <a-tag v-for="flag in (record.alert_flags || [])" :key="flag" :color="flag === 'negative_margin' ? 'red' : 'orange'">{{ t(`admin.reconcile.alertFlags.${flag}`) }}</a-tag>
            </template>
          </a-table-column>
        </template>
      </a-table>
      <p v-if="reconciliations.length === 0" class="empty-text">{{ t('admin.reconcile.emptyRecords') }}</p>
    </section>
  </section>
</template>

<style scoped>
.billing-reconciliation-page {
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

.panel {
  padding: 20px 22px;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
}

.panel-title {
  margin: 0 0 12px;
  font-size: 16px;
}

.empty-text {
  margin: 14px 0 4px;
  color: #98a2b3;
  font-size: 13px;
}
</style>