<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/utils/error'
import {
  getGlobalControlConfigs,
  saveGlobalControlSection,
} from '@/services/admin-global-control-config'
import {
  getDesktopClientConfig,
  saveDesktopClientConfig,
} from '@/services/admin-desktop-client-config'

const { t } = useI18n()

const form = reactive({
  runtime_fallback: {
    enabled: true,
    retry_attempts: 5,
  },
  media_fetch: {
    enabled: false,
    // 以 MB 输入，保存时换算为字节
    max_bytes_fallback_mb: 512,
  },
  agent_checkpoint: {
    enabled: false,
  },
  skill_catalog_sync: {
    enabled: false,
  },
  image_request_policy: {
    policy: 'strict' as 'strict' | 'auto_upgrade',
  },
  vision_fallback: {
    provider: '',
    model: '',
  },
  model_key_pool: {
    failure_threshold: 3,
    cooldown_seconds: 300,
  },
})

const apiOrigin = ref('')

const loading = ref(false)
const saving = ref(false)

const loadConfig = async () => {
  loading.value = true
  try {
    const [configs, desktop] = await Promise.all([
      getGlobalControlConfigs(),
      getDesktopClientConfig(),
    ])
    form.runtime_fallback.enabled = configs.runtime_fallback?.enabled ?? true
    form.runtime_fallback.retry_attempts = configs.runtime_fallback?.retry_attempts ?? 5
    form.media_fetch.enabled = configs.media_fetch?.enabled ?? false
    form.media_fetch.max_bytes_fallback_mb =
      Math.round((configs.media_fetch?.max_bytes_fallback ?? 536870912) / 1048576)
    form.agent_checkpoint.enabled = configs.agent_checkpoint?.enabled ?? false
    form.skill_catalog_sync.enabled = configs.skill_catalog_sync?.enabled ?? false
    form.image_request_policy.policy =
      configs.image_request_policy?.policy === 'auto_upgrade' ? 'auto_upgrade' : 'strict'
    form.vision_fallback.provider = configs.vision_fallback?.provider || ''
    form.vision_fallback.model = configs.vision_fallback?.model || ''
    form.model_key_pool.failure_threshold = configs.model_key_pool?.failure_threshold ?? 3
    form.model_key_pool.cooldown_seconds = configs.model_key_pool?.cooldown_seconds ?? 300
    apiOrigin.value = desktop.api_origin || ''
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.globalControlConfig.loadFailed')))
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  if (!Number.isFinite(form.runtime_fallback.retry_attempts) || form.runtime_fallback.retry_attempts <= 0) {
    Message.error(t('admin.globalControlConfig.fields.retryAttemptsInvalid'))
    return
  }
  if (
    !Number.isFinite(form.model_key_pool.failure_threshold) ||
    form.model_key_pool.failure_threshold <= 0
  ) {
    Message.error(t('admin.globalControlConfig.fields.failureThresholdInvalid'))
    return
  }
  if (
    !Number.isFinite(form.media_fetch.max_bytes_fallback_mb) ||
    form.media_fetch.max_bytes_fallback_mb <= 0
  ) {
    Message.error(t('admin.globalControlConfig.fields.maxBytesMbInvalid'))
    return
  }
  saving.value = true
  try {
    await Promise.all([
      saveGlobalControlSection('runtime_fallback', {
        enabled: form.runtime_fallback.enabled,
        retry_attempts: Math.round(form.runtime_fallback.retry_attempts),
      }),
      saveGlobalControlSection('media_fetch', {
        enabled: form.media_fetch.enabled,
        max_bytes_fallback: Math.round(form.media_fetch.max_bytes_fallback_mb * 1048576),
      }),
      saveGlobalControlSection('agent_checkpoint', {
        enabled: form.agent_checkpoint.enabled,
      }),
      saveGlobalControlSection('skill_catalog_sync', {
        enabled: form.skill_catalog_sync.enabled,
      }),
      saveGlobalControlSection('image_request_policy', {
        policy: form.image_request_policy.policy,
      }),
      saveGlobalControlSection('vision_fallback', {
        provider: form.vision_fallback.provider.trim(),
        model: form.vision_fallback.model.trim(),
      }),
      saveGlobalControlSection('model_key_pool', {
        failure_threshold: Math.round(form.model_key_pool.failure_threshold),
        cooldown_seconds: Math.round(form.model_key_pool.cooldown_seconds),
      }),
      saveDesktopClientConfig({ api_origin: apiOrigin.value.trim() }),
    ])
    Message.success(t('admin.globalControlConfig.saved'))
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.globalControlConfig.saveFailed')))
  } finally {
    saving.value = false
  }
}

onMounted(loadConfig)
</script>

<template>
  <section class="global-config-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">Global Control</p>
        <h2>{{ t('admin.globalControlConfig.title') }}</h2>
        <p>{{ t('admin.globalControlConfig.description') }}</p>
      </div>
    </header>

    <a-spin :loading="loading">
      <div class="config-grid">
        <!-- 模型运行时降级 -->
        <section class="config-card">
          <div class="card-header">
            <h3>{{ t('admin.globalControlConfig.sections.runtimeFallback.title') }}</h3>
            <p>{{ t('admin.globalControlConfig.sections.runtimeFallback.description') }}</p>
          </div>
          <a-form :model="form.runtime_fallback" layout="vertical">
            <a-form-item :label="t('admin.globalControlConfig.fields.enabled')" field="enabled">
              <a-switch v-model="form.runtime_fallback.enabled" />
            </a-form-item>
            <a-form-item :label="t('admin.globalControlConfig.fields.retryAttempts')" field="retry_attempts">
              <a-input-number v-model="form.runtime_fallback.retry_attempts" :min="1" :step="1" :precision="0" />
            </a-form-item>
          </a-form>
          <p class="hint-text">{{ t('admin.globalControlConfig.fields.retryAttemptsHint') }}</p>
        </section>

        <!-- 外部素材获取 -->
        <section class="config-card">
          <div class="card-header">
            <h3>{{ t('admin.globalControlConfig.sections.mediaFetch.title') }}</h3>
            <p>{{ t('admin.globalControlConfig.sections.mediaFetch.description') }}</p>
          </div>
          <a-form :model="form.media_fetch" layout="vertical">
            <a-form-item :label="t('admin.globalControlConfig.fields.enabled')" field="enabled">
              <a-switch v-model="form.media_fetch.enabled" />
            </a-form-item>
            <a-form-item :label="t('admin.globalControlConfig.fields.maxBytesMb')" field="max_bytes_fallback_mb">
              <a-input-number v-model="form.media_fetch.max_bytes_fallback_mb" :min="1" :step="1" :precision="0" />
            </a-form-item>
          </a-form>
          <p class="hint-text">{{ t('admin.globalControlConfig.fields.maxBytesMbHint') }}</p>
        </section>

        <!-- 会话 Checkpoint -->
        <section class="config-card">
          <div class="card-header">
            <h3>{{ t('admin.globalControlConfig.sections.agentCheckpoint.title') }}</h3>
            <p>{{ t('admin.globalControlConfig.sections.agentCheckpoint.description') }}</p>
          </div>
          <a-form :model="form.agent_checkpoint" layout="vertical">
            <a-form-item :label="t('admin.globalControlConfig.fields.enabled')" field="enabled">
              <a-switch v-model="form.agent_checkpoint.enabled" />
            </a-form-item>
          </a-form>
        </section>

        <!-- 技能目录同步 -->
        <section class="config-card">
          <div class="card-header">
            <h3>{{ t('admin.globalControlConfig.sections.skillCatalogSync.title') }}</h3>
            <p>{{ t('admin.globalControlConfig.sections.skillCatalogSync.description') }}</p>
          </div>
          <a-form :model="form.skill_catalog_sync" layout="vertical">
            <a-form-item :label="t('admin.globalControlConfig.fields.enabled')" field="enabled">
              <a-switch v-model="form.skill_catalog_sync.enabled" />
            </a-form-item>
          </a-form>
        </section>

        <!-- 图像请求策略 -->
        <section class="config-card">
          <div class="card-header">
            <h3>{{ t('admin.globalControlConfig.sections.imageRequestPolicy.title') }}</h3>
            <p>{{ t('admin.globalControlConfig.sections.imageRequestPolicy.description') }}</p>
          </div>
          <a-form :model="form.image_request_policy" layout="vertical">
            <a-form-item :label="t('admin.globalControlConfig.fields.policy')" field="policy">
              <a-select v-model="form.image_request_policy.policy">
                <a-option value="strict">{{ t('admin.globalControlConfig.fields.policyStrict') }}</a-option>
                <a-option value="auto_upgrade">{{ t('admin.globalControlConfig.fields.policyAutoUpgrade') }}</a-option>
              </a-select>
            </a-form-item>
          </a-form>
          <p class="hint-text">{{ t('admin.globalControlConfig.fields.policyHint') }}</p>
        </section>

        <!-- 视觉兜底模型 -->
        <section class="config-card">
          <div class="card-header">
            <h3>{{ t('admin.globalControlConfig.sections.visionFallback.title') }}</h3>
            <p>{{ t('admin.globalControlConfig.sections.visionFallback.description') }}</p>
          </div>
          <a-form :model="form.vision_fallback" layout="vertical">
            <a-form-item :label="t('admin.globalControlConfig.fields.provider')" field="provider">
              <a-input
                v-model="form.vision_fallback.provider"
                :placeholder="t('admin.globalControlConfig.fields.providerPlaceholder')"
                allow-clear
              />
            </a-form-item>
            <a-form-item :label="t('admin.globalControlConfig.fields.model')" field="model">
              <a-input
                v-model="form.vision_fallback.model"
                :placeholder="t('admin.globalControlConfig.fields.modelPlaceholder')"
                allow-clear
              />
            </a-form-item>
          </a-form>
        </section>

        <!-- 模型 Key 池 -->
        <section class="config-card">
          <div class="card-header">
            <h3>{{ t('admin.globalControlConfig.sections.modelKeyPool.title') }}</h3>
            <p>{{ t('admin.globalControlConfig.sections.modelKeyPool.description') }}</p>
          </div>
          <a-form :model="form.model_key_pool" layout="vertical">
            <a-form-item :label="t('admin.globalControlConfig.fields.failureThreshold')" field="failure_threshold">
              <a-input-number v-model="form.model_key_pool.failure_threshold" :min="1" :step="1" :precision="0" />
            </a-form-item>
            <a-form-item :label="t('admin.globalControlConfig.fields.cooldownSeconds')" field="cooldown_seconds">
              <a-input-number v-model="form.model_key_pool.cooldown_seconds" :min="1" :step="1" :precision="0" />
            </a-form-item>
          </a-form>
          <p class="hint-text">{{ t('admin.globalControlConfig.fields.failureThresholdHint') }}</p>
          <p class="hint-text">{{ t('admin.globalControlConfig.fields.cooldownSecondsHint') }}</p>
        </section>

        <!-- 桌面客户端连接 -->
        <section class="config-card">
          <div class="card-header">
            <h3>{{ t('admin.globalControlConfig.sections.desktopClient.title') }}</h3>
            <p>{{ t('admin.globalControlConfig.sections.desktopClient.description') }}</p>
          </div>
          <a-form :model="{ api_origin: apiOrigin }" layout="vertical">
            <a-form-item :label="t('admin.globalControlConfig.fields.apiOrigin')" field="api_origin">
              <a-input
                v-model="apiOrigin"
                :placeholder="t('admin.globalControlConfig.fields.apiOriginPlaceholder')"
                allow-clear
              />
            </a-form-item>
          </a-form>
        </section>
      </div>
    </a-spin>

    <div class="action-row">
      <a-button type="primary" :loading="saving" @click="handleSave">
        {{ t('admin.globalControlConfig.save') }}
      </a-button>
    </div>
  </section>
</template>

<style scoped>
.global-config-page {
  display: grid;
  gap: 20px;
}

.page-header {
  padding: 24px;
  border-radius: 22px;
  background: linear-gradient(135deg, #101828, #36527e);
  color: #fff;
  box-shadow: 0 14px 40px rgba(15, 23, 42, 0.06);
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

.config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 20px;
}

.config-card {
  padding: 24px;
  border-radius: 22px;
  background: #fff;
  box-shadow: 0 14px 40px rgba(15, 23, 42, 0.06);
}

.card-header h3 {
  font-size: 16px;
  color: #101828;
}

.card-header p {
  margin-top: 6px;
  color: #667085;
  font-size: 13px;
  line-height: 1.6;
}

.config-card :deep(.arco-form) {
  margin-top: 16px;
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
  justify-content: flex-end;
}
</style>
