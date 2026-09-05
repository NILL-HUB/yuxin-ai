<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useAdminStore } from '@/stores/admin'
import { listPaymentConfigs, setPaymentConfigEnabled, upsertPaymentConfig } from '@/services/payment-config'
import { type PaymentConfig } from '@/models/payment-config'
import { getErrorMessage } from '@/utils/error'

const { t } = useI18n()
const adminStore = useAdminStore()
const canManagePaymentConfig = computed(() => adminStore.hasPermission('payment_config:manage'))

type ConfigField = {
  key: string
  labelKey: string
  secret: boolean
}

const CONFIG_FIELDS: ConfigField[] = [
  { key: 'app_id', labelKey: 'appId', secret: false },
  { key: 'appid', labelKey: 'appid', secret: false },
  { key: 'seller_id', labelKey: 'sellerId', secret: false },
  { key: 'public_key', labelKey: 'publicKey', secret: false },
  { key: 'notify_url', labelKey: 'notifyUrl', secret: false },
  { key: 'return_url', labelKey: 'returnUrl', secret: false },
  { key: 'mch_id', labelKey: 'mchId', secret: true },
  { key: 'serial_no', labelKey: 'serialNo', secret: true },
  { key: 'api_v3_key', labelKey: 'apiV3Key', secret: true },
  { key: 'platform_public_key', labelKey: 'platformPublicKey', secret: true },
  { key: 'mch_key', labelKey: 'mchKey', secret: true },
  { key: 'app_secret', labelKey: 'appSecret', secret: true },
  { key: 'private_key', labelKey: 'privateKey', secret: true },
  { key: 'ali_public_key', labelKey: 'aliPublicKey', secret: true },
  { key: 'notify_secret', labelKey: 'notifySecret', secret: true },
]

const loading = ref(false)
const saving = ref(false)
const list = ref<PaymentConfig[]>([])

const editingProvider = ref('')
const editName = ref('')
const editConfigs = ref<Record<string, string>>({})

const labelOf = (field: ConfigField) => {
  return t(`admin.paymentConfig.field.${field.labelKey}`)
}

const loadConfigs = async () => {
  loading.value = true
  try {
    const result = await listPaymentConfigs()
    list.value = result.list || []
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.paymentConfig.loadFailed')))
  } finally {
    loading.value = false
  }
}

const openEdit = (config: PaymentConfig) => {
  editingProvider.value = config.provider
  editName.value = config.name || config.provider
  const form: Record<string, string> = {}
  CONFIG_FIELDS.forEach((field) => {
    const raw = config.configs?.[field.key]
    form[field.key] = field.secret ? '' : typeof raw === 'string' ? raw : ''
  })
  editConfigs.value = form
}

const closeEdit = () => {
  editingProvider.value = ''
  editName.value = ''
  editConfigs.value = {}
}

const handleSave = async () => {
  if (!editingProvider.value) return
  const configs: Record<string, string> = {}
  Object.entries(editConfigs.value).forEach(([key, value]) => {
    if (value.trim()) configs[key] = value.trim()
  })
  saving.value = true
  try {
    await upsertPaymentConfig(editingProvider.value, editName.value.trim() || editingProvider.value, configs)
    Message.success(t('admin.paymentConfig.saved'))
    closeEdit()
    await loadConfigs()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.paymentConfig.saveFailed')))
  } finally {
    saving.value = false
  }
}

const handleToggleEnabled = async (config: PaymentConfig) => {
  saving.value = true
  try {
    const result = await setPaymentConfigEnabled(config.provider, !config.enabled)
    Message.success(
      result.enabled
        ? t('admin.paymentConfig.enabled')
        : t('admin.paymentConfig.disabled'),
    )
    await loadConfigs()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.paymentConfig.toggleFailed')))
  } finally {
    saving.value = false
  }
}

const formatUpdatedAt = (value: number | null) => {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

onMounted(loadConfigs)
</script>

<template>
  <section class="payment-config-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Payment Config</p>
        <h2>{{ t('admin.paymentConfig.title') }}</h2>
        <p>{{ t('admin.paymentConfig.description') }}</p>
      </div>
    </header>

    <section class="providers-grid">
      <div v-for="config in list" :key="config.provider" class="provider-card">
        <div class="provider-header">
          <div>
            <h3>{{ t(`admin.paymentConfig.provider.${config.provider}`) }}</h3>
            <p>{{ t('admin.paymentConfig.updatedAt', { time: formatUpdatedAt(config.updated_at) }) }}</p>
          </div>
          <div class="provider-actions">
            <a-switch
              v-if="canManagePaymentConfig"
              :model-value="config.enabled"
              :loading="saving"
              :checked-text="t('admin.paymentConfig.on')"
              :unchecked-text="t('admin.paymentConfig.off')"
              @change="handleToggleEnabled(config)"
            />
            <a-tag v-if="config.enabled" color="green">{{ t('admin.paymentConfig.on') }}</a-tag>
            <a-tag v-else color="gray">{{ t('admin.paymentConfig.off') }}</a-tag>
            <a-button v-if="canManagePaymentConfig" size="mini" type="primary" @click="openEdit(config)">
              {{ t('admin.paymentConfig.edit') }}
            </a-button>
          </div>
        </div>

        <div class="config-summary">
          <div v-for="field in CONFIG_FIELDS" v-show="config.configs?.[field.key]" :key="field.key" class="config-line">
            <span>{{ labelOf(field) }}</span>
            <code>{{ config.configs?.[field.key] }}</code>
          </div>
          <p v-if="!Object.keys(config.configs || {}).length" class="empty-hint">{{ t('admin.paymentConfig.emptyConfig') }}</p>
        </div>
      </div>
    </section>

    <a-modal
      :visible="!!editingProvider"
      :title="t('admin.paymentConfig.editTitle', { provider: t(`admin.paymentConfig.provider.${editingProvider}`) })"
      :ok-loading="saving"
      :ok-text="t('common.actions.save')"
      @ok="handleSave"
      @cancel="closeEdit"
    >
      <div class="edit-form">
        <a-input v-model="editName" :placeholder="t('admin.paymentConfig.namePlaceholder')" />
        <div v-for="field in CONFIG_FIELDS" :key="field.key" class="field-row">
          <label>{{ labelOf(field) }}</label>
          <a-input-password v-if="field.secret" v-model="editConfigs[field.key]" :placeholder="t('admin.paymentConfig.secretPlaceholder')" autocomplete="new-password" />
          <a-input v-else v-model="editConfigs[field.key]" />
        </div>
      </div>
    </a-modal>
  </section>
</template>

<style scoped>
.payment-config-page {
  display: grid;
  gap: 20px;
}

.page-header,
.provider-card {
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

.providers-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.provider-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.provider-header h3 {
  color: #101828;
  font-size: 18px;
}

.provider-header p {
  margin-top: 6px;
  color: #667085;
  font-size: 13px;
}

.provider-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.config-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 16px;
}

.config-line {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 10px;
  background: #f8fafc;
}

.config-line span {
  color: #667085;
  font-size: 12px;
  white-space: nowrap;
}

.config-line code {
  color: #101828;
  font-size: 12px;
  word-break: break-all;
}

.empty-hint {
  grid-column: 1 / -1;
  padding: 16px;
  text-align: center;
  color: #98a2b3;
  font-size: 13px;
  background: #f8fafc;
  border-radius: 10px;
}

.edit-form {
  display: grid;
  gap: 12px;
}

.field-row {
  display: grid;
  gap: 4px;
}

.field-row label {
  color: #667085;
  font-size: 13px;
}

@media (max-width: 960px) {
  .providers-grid {
    grid-template-columns: 1fr;
  }

  .config-summary {
    grid-template-columns: 1fr;
  }
}
</style>