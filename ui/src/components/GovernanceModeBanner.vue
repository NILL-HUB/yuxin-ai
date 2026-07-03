<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { listAdminOrchestrationFlags } from '@/services/admin-orchestration-flags'
import type { AdminOrchestrationFlag } from '@/models/admin-orchestration-flag'

const { t } = useI18n()

const loading = ref(false)
const loadFailed = ref(false)
const flags = ref<AdminOrchestrationFlag[]>([])

// 池治理相关开关编码（与后端 POOL_GOVERNANCE 开关一致）
const BLOCK_ALL_CODE = 'ENABLE_POOL_GOVERNANCE_BLOCK_ALL'
const BLOCK_SENSITIVE_CODE = 'ENABLE_POOL_GOVERNANCE_BLOCK_SENSITIVE'
const OBSERVE_ONLY_CODE = 'ENABLE_POOL_GOVERNANCE_OBSERVE_ONLY'

const isFlagEnabled = (code: string) =>
  flags.value.find((f) => f.code === code)?.enabled === true

const blockAllEnabled = computed(() => isFlagEnabled(BLOCK_ALL_CODE))
const blockSensitiveEnabled = computed(() => isFlagEnabled(BLOCK_SENSITIVE_CODE))
const observeOnlyEnabled = computed(() => isFlagEnabled(OBSERVE_ONLY_CODE))

type ModeKey = 'blockAll' | 'blockSensitive' | 'observeOnly' | 'notEnabled' | 'error'

const mode = computed<ModeKey>(() => {
  if (loadFailed.value) return 'error'
  // 优先级：全量阻断 > 敏感工具阻断 > 观测期 > 未启用
  if (blockAllEnabled.value) return 'blockAll'
  if (blockSensitiveEnabled.value) return 'blockSensitive'
  if (observeOnlyEnabled.value) return 'observeOnly'
  return 'notEnabled'
})

const alertType = computed<'error' | 'warning' | 'info' | 'success'>(() => {
  switch (mode.value) {
    case 'blockAll':
      return 'error'
    case 'blockSensitive':
      return 'warning'
    case 'observeOnly':
      return 'info'
    case 'notEnabled':
      return 'success'
    default:
      return 'info'
  }
})

const modeLabel = computed(() => {
  switch (mode.value) {
    case 'blockAll':
      return t('admin.governanceMode.blockAll')
    case 'blockSensitive':
      return t('admin.governanceMode.blockSensitive')
    case 'observeOnly':
      return t('admin.governanceMode.observeOnly')
    case 'notEnabled':
      return t('admin.governanceMode.notEnabled')
    default:
      return t('admin.governanceMode.loadFailed')
  }
})

const loadFlags = async () => {
  loading.value = true
  try {
    const result = await listAdminOrchestrationFlags()
    const list = Array.isArray(result) ? result : []
    // 前端过滤 POOL_GOVERNANCE 相关开关
    flags.value = list.filter((f) => f.code.startsWith('ENABLE_POOL_GOVERNANCE'))
    loadFailed.value = false
  } catch {
    flags.value = []
    loadFailed.value = true
  } finally {
    loading.value = false
  }
}

onMounted(loadFlags)
</script>

<template>
  <a-alert :type="alertType" :loading="loading" class="governance-mode-banner" show-icon>
    <template #title>
      <span class="font-medium">{{ t('admin.governanceMode.currentMode') }}：</span>
      <span class="font-semibold">{{ modeLabel }}</span>
    </template>
    <div class="mt-1 flex flex-wrap items-center gap-4 text-sm">
      <router-link to="/admin/orchestration-flags" class="text-blue-600 hover:underline">
        {{ t('admin.governanceMode.switchMode') }}
      </router-link>
      <router-link to="/admin/routing-logs" class="text-blue-600 hover:underline">
        {{ t('admin.governanceMode.viewLogs') }}
      </router-link>
    </div>
  </a-alert>
</template>

<style scoped>
.governance-mode-banner {
  border-radius: 0.5rem;
}
</style>
