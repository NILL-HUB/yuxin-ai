<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import { getSmsConfig, saveSmsConfig, testSmsSend, type SmsConfigPayload } from '@/services/admin-message-config'

const { t } = useI18n()

const form = reactive<SmsConfigPayload>({
  provider: '',
  access_key: '',
  access_secret: '',
  sign_name: '',
  region: '',
  sdk_app_id: '',
  verify_code_template: '',
})

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const testPhone = ref('')
const testResult = ref<{ ok: boolean; detail?: string } | null>(null)

const isProviderEnabled = computed(() => Boolean(form.provider))

const loadConfig = async () => {
  loading.value = true
  try {
    const configs = await getSmsConfig()
    Object.assign(form, configs)
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.messageConfig.sms.loadFailed')))
  } finally {
    loading.value = false
  }
}

const validateProviderFields = (): boolean => {
  if (!form.provider) return true
  const missing = [
    !form.access_key.trim(),
    !form.access_secret.trim(),
    !form.sign_name.trim(),
    !form.verify_code_template.trim(),
  ]
  if (missing.some(Boolean)) {
    Message.warning(t('admin.messageConfig.sms.providerFieldsRequired'))
    return false
  }
  return true
}

const handleSave = async () => {
  if (!validateProviderFields()) return
  saving.value = true
  try {
    const configs = await saveSmsConfig({ ...form })
    Object.assign(form, configs)
    Message.success(t('admin.messageConfig.sms.saved'))
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.messageConfig.sms.saveFailed')))
  } finally {
    saving.value = false
  }
}

const handleTestSend = async () => {
  const phone = testPhone.value.trim()
  if (!phone) {
    Message.warning(t('admin.messageConfig.sms.testPhoneRequired'))
    return
  }
  if (!validateProviderFields()) return
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await testSmsSend(phone)
  } catch (error) {
    testResult.value = { ok: false, detail: getErrorMessage(error, t('admin.messageConfig.sms.testFailed')) }
  } finally {
    testing.value = false
  }
}

onMounted(loadConfig)
</script>

<template>
  <section class="sms-config-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">SMS Config</p>
        <h2>{{ t('admin.messageConfig.sms.title') }}</h2>
        <p>{{ t('admin.messageConfig.sms.description') }}</p>
      </div>
    </header>

    <section class="config-card">
      <a-spin :loading="loading">
        <a-form :model="form" layout="vertical">
          <a-form-item :label="t('admin.messageConfig.sms.provider')" field="provider">
            <a-radio-group v-model="form.provider" type="button">
              <a-radio value="">{{ t('admin.messageConfig.sms.providerNone') }}</a-radio>
              <a-radio value="aliyun">{{ t('admin.messageConfig.sms.providerAliyun') }}</a-radio>
              <a-radio value="tencent">{{ t('admin.messageConfig.sms.providerTencent') }}</a-radio>
            </a-radio-group>
          </a-form-item>
          <a-form-item :label="t('admin.messageConfig.sms.accessKey')" field="access_key">
            <a-input v-model="form.access_key" :placeholder="t('admin.messageConfig.sms.accessKeyPlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('admin.messageConfig.sms.accessSecret')" field="access_secret">
            <a-input-password v-model="form.access_secret" :placeholder="t('admin.messageConfig.sms.accessSecretPlaceholder')" autocomplete="new-password" />
          </a-form-item>
          <a-form-item :label="t('admin.messageConfig.sms.signName')" field="sign_name">
            <a-input v-model="form.sign_name" :placeholder="t('admin.messageConfig.sms.signNamePlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('admin.messageConfig.sms.region')" field="region">
            <a-input v-model="form.region" :placeholder="t('admin.messageConfig.sms.regionPlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('admin.messageConfig.sms.sdkAppId')" field="sdk_app_id">
            <a-input v-model="form.sdk_app_id" :placeholder="t('admin.messageConfig.sms.sdkAppIdPlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('admin.messageConfig.sms.verifyCodeTemplate')" field="verify_code_template">
            <a-input v-model="form.verify_code_template" :placeholder="t('admin.messageConfig.sms.verifyCodeTemplatePlaceholder')" />
          </a-form-item>
        </a-form>
      </a-spin>

      <div class="action-row">
        <a-button type="primary" :loading="saving" @click="handleSave">
          {{ t('admin.messageConfig.sms.save') }}
        </a-button>
        <a-input v-model="testPhone" :placeholder="t('admin.messageConfig.sms.testPhonePlaceholder')" :style="{ width: '260px' }" />
        <a-button :loading="testing" @click="handleTestSend">
          {{ t('admin.messageConfig.sms.testSend') }}
        </a-button>
      </div>

      <a-alert
        v-if="testResult"
        class="test-result"
        :type="testResult.ok ? 'success' : 'error'"
      >
        {{ testResult.detail ?? (testResult.ok ? t('admin.messageConfig.sms.testSuccess') : t('admin.messageConfig.sms.testFailure')) }}
      </a-alert>
    </section>
  </section>
</template>

<style scoped>
.sms-config-page {
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

.page-kicker {
  margin: 0 0 8px;
  color: #a9c7ff;
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

h2,
p {
  margin: 0;
}

.page-header p:not(.page-kicker) {
  margin-top: 8px;
  color: #d8e4f7;
}

.action-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 24px;
}

.test-result {
  margin-top: 16px;
}
</style>
