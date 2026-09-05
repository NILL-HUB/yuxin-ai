<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import { getMailConfig, saveMailConfig, testMailSend, type MailConfigPayload } from '@/services/admin-message-config'

const { t } = useI18n()

const form = reactive<MailConfigPayload>({
  smtp_host: '',
  smtp_port: 587,
  use_tls: true,
  use_ssl: false,
  username: '',
  password: '',
  default_sender: '',
  from_name: '',
  timeout: 30,
})

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const testTo = ref('')
const testResult = ref<{ ok: boolean; detail?: string } | null>(null)

const toggleTls = (checked: boolean) => {
  form.use_tls = checked
  if (checked) form.use_ssl = false
}

const toggleSsl = (checked: boolean) => {
  form.use_ssl = checked
  if (checked) form.use_tls = false
}

const loadConfig = async () => {
  loading.value = true
  try {
    const configs = await getMailConfig()
    Object.assign(form, {
      ...configs,
      smtp_port: configs.smtp_port ? Number(configs.smtp_port) : 587,
      timeout: configs.timeout ? Number(configs.timeout) : 30,
    })
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.messageConfig.mail.loadFailed')))
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  saving.value = true
  try {
    const configs = await saveMailConfig({ ...form })
    Object.assign(form, configs)
    Message.success(t('admin.messageConfig.mail.saved'))
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.messageConfig.mail.saveFailed')))
  } finally {
    saving.value = false
  }
}

const handleTestSend = async () => {
  const to = testTo.value.trim()
  if (!to) {
    Message.warning(t('admin.messageConfig.mail.testToRequired'))
    return
  }
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await testMailSend(to)
  } catch (error) {
    testResult.value = { ok: false, detail: getErrorMessage(error, t('admin.messageConfig.mail.testFailed')) }
  } finally {
    testing.value = false
  }
}

onMounted(loadConfig)
</script>

<template>
  <section class="mail-config-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Mail Config</p>
        <h2>{{ t('admin.messageConfig.mail.title') }}</h2>
        <p>{{ t('admin.messageConfig.mail.description') }}</p>
      </div>
    </header>

    <section class="config-card">
      <a-spin :loading="loading">
        <a-form :model="form" layout="vertical">
          <a-form-item :label="t('admin.messageConfig.mail.smtpHost')" field="smtp_host" :rules="[{ required: true, message: t('admin.messageConfig.mail.smtpHostRequired') }]">
            <a-input v-model="form.smtp_host" :placeholder="t('admin.messageConfig.mail.smtpHostPlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('admin.messageConfig.mail.smtpPort')" field="smtp_port" :rules="[{ required: true, message: t('admin.messageConfig.mail.smtpPortRequired') }]">
            <a-input-number v-model="form.smtp_port" :min="1" :max="65535" :style="{ width: '220px' }" />
          </a-form-item>
          <a-form-item :label="t('admin.messageConfig.mail.security')">
            <div class="security-row">
              <a-switch v-model="form.use_tls" @change="toggleTls" />
              <span class="security-label">{{ t('admin.messageConfig.mail.useTls') }}</span>
              <a-switch v-model="form.use_ssl" @change="toggleSsl" />
              <span class="security-label">{{ t('admin.messageConfig.mail.useSsl') }}</span>
            </div>
          </a-form-item>
          <a-form-item :label="t('admin.messageConfig.mail.username')" field="username">
            <a-input v-model="form.username" :placeholder="t('admin.messageConfig.mail.usernamePlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('admin.messageConfig.mail.password')" field="password">
            <a-input-password v-model="form.password" :placeholder="t('admin.messageConfig.mail.passwordPlaceholder')" autocomplete="new-password" />
          </a-form-item>
          <a-form-item :label="t('admin.messageConfig.mail.defaultSender')" field="default_sender">
            <a-input v-model="form.default_sender" :placeholder="t('admin.messageConfig.mail.defaultSenderPlaceholder')" />
          </a-form-item>
          <a-form-item :label="t('admin.messageConfig.mail.fromName')" field="from_name">
            <a-input v-model="form.from_name" />
          </a-form-item>
          <a-form-item :label="t('admin.messageConfig.mail.timeout')" field="timeout">
            <a-input-number v-model="form.timeout" :min="1" :max="300" :style="{ width: '220px' }" />
          </a-form-item>
        </a-form>
      </a-spin>

      <div class="action-row">
        <a-button type="primary" :loading="saving" @click="handleSave">
          {{ t('admin.messageConfig.mail.save') }}
        </a-button>
        <a-input v-model="testTo" :placeholder="t('admin.messageConfig.mail.testToPlaceholder')" :style="{ width: '260px' }" />
        <a-button :loading="testing" @click="handleTestSend">
          {{ t('admin.messageConfig.mail.testSend') }}
        </a-button>
      </div>

      <a-alert
        v-if="testResult"
        class="test-result"
        :type="testResult.ok ? 'success' : 'error'"
      >
        {{ testResult.detail ?? (testResult.ok ? t('admin.messageConfig.mail.testSuccess') : t('admin.messageConfig.mail.testFailure')) }}
      </a-alert>
    </section>
  </section>
</template>

<style scoped>
.mail-config-page {
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

.security-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.security-label {
  margin-right: 18px;
  color: #475467;
  font-size: 14px;
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
