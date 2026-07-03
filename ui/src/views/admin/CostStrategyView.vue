<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  createCostPolicy,
  listCostPolicies,
  updateCostPolicy,
} from '@/services/admin-model-pool'
import { getErrorMessage } from '@/utils/error'

type CostPolicy = {
  id: string
  policy_name: string
  model_tier: string
  max_cost_per_request: string
  billing_mode: string
  upgrade_threshold: string
  created_at?: number
  updated_at?: number
}

const { t } = useI18n()

const MODEL_TIERS = ['cheap', 'standard', 'strong']
const MODEL_TIER_LABELS: Record<string, string> = {
  cheap: t('admin.models.tierLabels.cheap'),
  standard: t('admin.models.tierLabels.standard'),
  strong: t('admin.models.tierLabels.strong'),
}
const BILLING_MODES = ['token', 'request', 'credit']
const BILLING_MODE_LABELS: Record<string, string> = {
  token: t('admin.costStrategy.billingModes.token'),
  request: t('admin.costStrategy.billingModes.request'),
  credit: t('admin.costStrategy.billingModes.credit'),
}

const loading = ref(false)
const actionLoading = ref(false)
const costPolicies = ref<CostPolicy[]>([])

const stats = computed(() => ({
  total: costPolicies.value.length,
  byToken: costPolicies.value.filter((item) => item.billing_mode === 'token').length,
  byRequest: costPolicies.value.filter((item) => item.billing_mode === 'request').length,
  byCredit: costPolicies.value.filter((item) => item.billing_mode === 'credit').length,
}))

const costModalVisible = ref(false)
const editingCostId = ref('')
const costForm = ref({
  policy_name: '',
  model_tier: 'standard',
  max_cost_per_request: '0.000000',
  billing_mode: 'token',
  upgrade_threshold: '0.000000',
})

const openCreateCost = () => {
  editingCostId.value = ''
  costForm.value = {
    policy_name: '',
    model_tier: 'standard',
    max_cost_per_request: '0.000000',
    billing_mode: 'token',
    upgrade_threshold: '0.000000',
  }
  costModalVisible.value = true
}

const openEditCost = (policy: CostPolicy) => {
  editingCostId.value = policy.id
  costForm.value = {
    policy_name: policy.policy_name,
    model_tier: policy.model_tier,
    max_cost_per_request: policy.max_cost_per_request,
    billing_mode: policy.billing_mode,
    upgrade_threshold: policy.upgrade_threshold,
  }
  costModalVisible.value = true
}

const loadAll = async () => {
  loading.value = true
  try {
    const result = await listCostPolicies() as { data?: { list?: CostPolicy[] } }
    costPolicies.value = result.data?.list || []
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.costStrategy.messages.loadFailed')))
  } finally {
    loading.value = false
  }
}

const submitCost = async () => {
  actionLoading.value = true
  try {
    if (editingCostId.value) {
      await updateCostPolicy(editingCostId.value, {
        model_tier: costForm.value.model_tier,
        max_cost_per_request: costForm.value.max_cost_per_request,
        billing_mode: costForm.value.billing_mode,
        upgrade_threshold: costForm.value.upgrade_threshold,
      })
      Message.success(t('admin.costStrategy.messages.updated'))
    } else {
      await createCostPolicy({
        policy_name: costForm.value.policy_name,
        model_tier: costForm.value.model_tier,
        max_cost_per_request: costForm.value.max_cost_per_request,
        billing_mode: costForm.value.billing_mode,
        upgrade_threshold: costForm.value.upgrade_threshold,
      })
      Message.success(t('admin.costStrategy.messages.created'))
    }
    costModalVisible.value = false
    await loadAll()
  } catch (error) {
    Message.error(getErrorMessage(error, editingCostId.value ? t('admin.costStrategy.messages.updateFailed') : t('admin.costStrategy.messages.createFailed')))
  } finally {
    actionLoading.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <section class="space-y-6 p-6">
    <header>
      <h1 class="text-2xl font-semibold text-gray-900">{{ t('admin.costStrategy.title') }}</h1>
      <p class="mt-1 text-sm text-gray-500">{{ t('admin.costStrategy.description') }}</p>
    </header>

    <div class="grid gap-4 md:grid-cols-4">
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.costStrategy.stats.total') }}</p>
        <strong class="text-xl">{{ stats.total }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.costStrategy.stats.byToken') }}</p>
        <strong class="text-xl">{{ stats.byToken }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.costStrategy.stats.byRequest') }}</p>
        <strong class="text-xl">{{ stats.byRequest }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.costStrategy.stats.byCredit') }}</p>
        <strong class="text-xl">{{ stats.byCredit }}</strong>
      </article>
    </div>

    <div class="mb-3 flex justify-end">
      <a-button type="primary" @click="openCreateCost">{{ t('admin.costStrategy.actions.create') }}</a-button>
    </div>
    <a-spin :loading="loading" class="block">
      <div class="overflow-hidden rounded-lg border bg-white">
        <table class="w-full text-left text-sm">
          <thead class="bg-gray-50 text-gray-500">
            <tr>
              <th class="p-3">{{ t('admin.costStrategy.columns.policyName') }}</th>
              <th class="p-3">{{ t('admin.costStrategy.columns.modelTier') }}</th>
              <th class="p-3">{{ t('admin.costStrategy.columns.maxCostPerRequest') }}</th>
              <th class="p-3">{{ t('admin.costStrategy.columns.billingMode') }}</th>
              <th class="p-3">{{ t('admin.costStrategy.columns.upgradeThreshold') }}</th>
              <th class="p-3">{{ t('admin.costStrategy.columns.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!costPolicies.length">
              <td class="p-6 text-center text-gray-400" colspan="6">{{ t('admin.costStrategy.empty') }}</td>
            </tr>
            <tr v-for="policy in costPolicies" :key="policy.id" class="border-t">
              <td class="p-3">{{ policy.policy_name }}</td>
              <td class="p-3">{{ MODEL_TIER_LABELS[policy.model_tier] || policy.model_tier }}</td>
              <td class="p-3">{{ policy.max_cost_per_request }}</td>
              <td class="p-3">{{ BILLING_MODE_LABELS[policy.billing_mode] || policy.billing_mode }}</td>
              <td class="p-3">{{ policy.upgrade_threshold }}</td>
              <td class="p-3">
                <a-button size="mini" @click="openEditCost(policy)">{{ t('admin.costStrategy.actions.edit') }}</a-button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </a-spin>

    <a-modal
      v-model:visible="costModalVisible"
      :title="editingCostId ? t('admin.costStrategy.modal.editTitle') : t('admin.costStrategy.actions.create')"
      :ok-loading="actionLoading"
      :mask-closable="false"
      @ok="submitCost"
    >
      <a-form :model="costForm" layout="vertical">
        <a-form-item :label="t('admin.costStrategy.columns.policyName')" field="policy_name">
          <a-input v-model="costForm.policy_name" :disabled="!!editingCostId" :placeholder="t('admin.costStrategy.modal.placeholders.policyName')" />
        </a-form-item>
        <a-form-item :label="t('admin.costStrategy.columns.modelTier')" field="model_tier">
          <a-select v-model="costForm.model_tier">
            <a-option v-for="tier in MODEL_TIERS" :key="tier" :value="tier">{{ MODEL_TIER_LABELS[tier] }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.costStrategy.columns.maxCostPerRequest')" field="max_cost_per_request">
          <a-input v-model="costForm.max_cost_per_request" :placeholder="t('admin.costStrategy.modal.placeholders.price')" />
        </a-form-item>
        <a-form-item :label="t('admin.costStrategy.columns.billingMode')" field="billing_mode">
          <a-select v-model="costForm.billing_mode">
            <a-option v-for="m in BILLING_MODES" :key="m" :value="m">{{ BILLING_MODE_LABELS[m] || m }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('admin.costStrategy.columns.upgradeThreshold')" field="upgrade_threshold">
          <a-input v-model="costForm.upgrade_threshold" :placeholder="t('admin.costStrategy.modal.placeholders.price')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>
