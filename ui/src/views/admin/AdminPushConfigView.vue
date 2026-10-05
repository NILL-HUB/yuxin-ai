<template>
  <section class="push-config-page">
    <header class="page-header">
      <div>
        <h2>{{ t('admin.pushConfig.title') }}</h2>
        <p>{{ t('admin.pushConfig.description') }}</p>
        <p class="hint">{{ t('admin.pushConfig.qualificationHint') }}</p>
      </div>
    </header>

    <section class="config-card">
      <a-spin :loading="loading">
        <a-form :model="form" layout="vertical">
          <a-form-item :label="t('admin.pushConfig.enabled')" field="enabled">
            <a-switch v-model="form.enabled" />
            <span class="field-hint">{{ t('admin.pushConfig.enabledHint') }}</span>
          </a-form-item>
          <a-form-item :label="t('admin.pushConfig.primaryProvider')" field="primary_provider">
            <a-radio-group v-model="form.primary_provider" type="button">
              <a-radio value="getui">{{ t('admin.pushConfig.providerGetui') }}</a-radio>
              <a-radio value="umeng">{{ t('admin.pushConfig.providerUmeng') }}</a-radio>
            </a-radio-group>
          </a-form-item>
          <a-form-item field="fallback_enabled">
            <a-checkbox v-model="form.fallback_enabled">
              {{ t('admin.pushConfig.fallbackEnabled') }}
            </a-checkbox>
          </a-form-item>

          <a-divider>{{ t('admin.pushConfig.getuiTitle') }}</a-divider>
          <div class="grid">
            <a-form-item :label="t('admin.pushConfig.getuiAppId')" field="getui.app_id">
              <a-input v-model="form.getui.app_id" />
            </a-form-item>
            <a-form-item :label="t('admin.pushConfig.getuiAppKey')" field="getui.app_key">
              <a-input v-model="form.getui.app_key" />
            </a-form-item>
            <a-form-item :label="t('admin.pushConfig.getuiAppSecret')" field="getui.app_secret">
              <a-input-password
                v-model="form.getui.app_secret"
                :placeholder="t('admin.pushConfig.secretPlaceholder')"
                autocomplete="new-password"
              />
            </a-form-item>
            <a-form-item :label="t('admin.pushConfig.getuiMasterSecret')" field="getui.master_secret">
              <a-input-password
                v-model="form.getui.master_secret"
                :placeholder="t('admin.pushConfig.secretPlaceholder')"
                autocomplete="new-password"
              />
            </a-form-item>
          </div>

          <a-divider>{{ t('admin.pushConfig.umengTitle') }}</a-divider>
          <div class="grid">
            <a-form-item :label="t('admin.pushConfig.umengAppKey')" field="umeng.app_key">
              <a-input v-model="form.umeng.app_key" />
            </a-form-item>
            <a-form-item :label="t('admin.pushConfig.umengAppMasterSecret')" field="umeng.app_master_secret">
              <a-input-password
                v-model="form.umeng.app_master_secret"
                :placeholder="t('admin.pushConfig.secretPlaceholder')"
                autocomplete="new-password"
              />
            </a-form-item>
            <a-form-item :label="t('admin.pushConfig.umengProductionMode')" field="umeng.production_mode">
              <a-switch v-model="form.umeng.production_mode" />
              <span class="field-hint">{{ t('admin.pushConfig.umengProductionHint') }}</span>
            </a-form-item>
          </div>
        </a-form>
      </a-spin>

      <div class="action-row">
        <a-button type="primary" :loading="saving" @click="handleSave">
          {{ t('admin.pushConfig.save') }}
        </a-button>
      </div>
    </section>

    <section class="config-card">
      <h3>{{ t('admin.pushConfig.testTitle') }}</h3>
      <div class="action-row">
        <a-radio-group v-model="testProvider" type="button">
          <a-radio value="getui">{{ t('admin.pushConfig.providerGetui') }}</a-radio>
          <a-radio value="umeng">{{ t('admin.pushConfig.providerUmeng') }}</a-radio>
        </a-radio-group>
        <a-input
          v-model="testDeviceToken"
          :placeholder="t('admin.pushConfig.testDeviceTokenPlaceholder')"
          :style="{ width: '320px' }"
        />
        <a-button :loading="testing" @click="handleTestSend">
          {{ t('admin.pushConfig.testSend') }}
        </a-button>
      </div>

      <a-alert v-if="testResult" class="test-result" :type="testResult.ok ? 'success' : 'error'">
        {{
          testResult.detail ??
          (testResult.ok ? t('admin.pushConfig.testSuccess') : t('admin.pushConfig.testFailure'))
        }}
      </a-alert>
    </section>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import {
  getPushConfig,
  savePushConfig,
  testPushSend,
  type PushConfigPayload,
  type PushProvider,
  type PushTestResult,
} from '@/services/admin-push-config'

const { t } = useI18n()

const form = reactive<PushConfigPayload>({
  enabled: false,
  primary_provider: 'getui',
  fallback_enabled: true,
  getui: { app_id: '', app_key: '', app_secret: '', master_secret: '' },
  umeng: { app_key: '', app_master_secret: '', production_mode: true },
})

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const testProvider = ref<PushProvider>('getui')
const testDeviceToken = ref('')
const testResult = ref<PushTestResult | null>(null)

const loadConfig = async () => {
  loading.value = true
  try {
    const configs = await getPushConfig()
    Object.assign(form, configs)
    testProvider.value = configs.primary_provider || 'getui'
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.pushConfig.loadFailed')))
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  saving.value = true
  try {
    const configs = await savePushConfig({ ...form })
    Object.assign(form, configs)
    Message.success(t('admin.pushConfig.saved'))
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.pushConfig.saveFailed')))
  } finally {
    saving.value = false
  }
}

const handleTestSend = async () => {
  const token = testDeviceToken.value.trim()
  if (!token) {
    Message.warning(t('admin.pushConfig.testTokenRequired'))
    return
  }
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await testPushSend(testProvider.value, token)
  } catch (error) {
    testResult.value = { ok: false, detail: getErrorMessage(error, t('admin.pushConfig.testFailure')) }
  } finally {
    testing.value = false
  }
}

onMounted(loadConfig)
</script>

<style scoped>
.push-config-page {
  display: grid;
  gap: 20px;
}

.page-header,
.config-card {
  padding: 24px;
  border-radius: 22px;
  background: #fff;
  box-shadow: 0 14px 40px rgba(15, 23, 42, 0.06);
}

.page-header {
  background: linear-gradient(135deg, #101828, #36527e);
  color: #fff;
}

.page-header p {
  margin: 8px 0 0;
  opacity: 0.85;
}

.page-header .hint {
  font-size: 12px;
  opacity: 0.7;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 0 16px;
}

.field-hint {
  margin-left: 8px;
  font-size: 12px;
  color: #86909c;
}

.action-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
}

.test-result {
  margin-top: 12px;
}
</style>
