<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import {
  getDesktopClientConfig,
  saveDesktopClientConfig,
  type DesktopClientConfigPayload,
} from '@/services/admin-desktop-client-config'

const { t } = useI18n()

const form = reactive<DesktopClientConfigPayload>({
  api_origin: '',
})

const loading = ref(false)
const saving = ref(false)

const loadConfig = async () => {
  loading.value = true
  try {
    const configs = await getDesktopClientConfig()
    form.api_origin = configs.api_origin || ''
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.desktopClientConfig.loadFailed')))
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  saving.value = true
  try {
    const configs = await saveDesktopClientConfig({ api_origin: form.api_origin.trim() })
    form.api_origin = configs.api_origin || ''
    Message.success(t('admin.desktopClientConfig.saved'))
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.desktopClientConfig.saveFailed')))
  } finally {
    saving.value = false
  }
}

onMounted(loadConfig)
</script>

<template>
  <section class="desktop-config-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Desktop Client</p>
        <h2>{{ t('admin.desktopClientConfig.title') }}</h2>
        <p>{{ t('admin.desktopClientConfig.description') }}</p>
      </div>
    </header>

    <section class="config-card">
      <a-spin :loading="loading">
        <a-form :model="form" layout="vertical">
          <a-form-item :label="t('admin.desktopClientConfig.apiOriginLabel')" field="api_origin">
            <a-input
              v-model="form.api_origin"
              :placeholder="t('admin.desktopClientConfig.apiOriginPlaceholder')"
              allow-clear
            />
          </a-form-item>
        </a-form>
        <p class="hint-text">{{ t('admin.desktopClientConfig.emptyHint') }}</p>
      </a-spin>

      <div class="action-row">
        <a-button type="primary" :loading="saving" @click="handleSave">
          {{ t('admin.desktopClientConfig.save') }}
        </a-button>
      </div>
    </section>
  </section>
</template>

<style scoped>
.desktop-config-page {
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

.hint-text {
  margin-top: 8px;
  color: #667085;
  font-size: 13px;
}

.action-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 24px;
}
</style>
