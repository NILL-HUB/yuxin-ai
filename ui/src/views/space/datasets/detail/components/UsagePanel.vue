<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getStorageUsage, resolveUpgradeUrl } from '@/services/storage-usage'
import type { StorageUsage } from '@/models/storage-usage'

const { t } = useI18n()
const usage = ref<StorageUsage | null>(null)
const failed = ref(false)
const loading = ref(false)

const formatBytes = (bytes: number) => {
  if (bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const idx = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** idx).toFixed(1)} ${units[idx]}`
}

const loadUsage = async () => {
  loading.value = true
  failed.value = false
  try {
    const resp = await getStorageUsage()
    usage.value = resp.data
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

const goUpgrade = () => {
  window.location.href = resolveUpgradeUrl()
}

onMounted(loadUsage)
</script>

<template>
  <div class="flex flex-col gap-2 rounded-xl border border-border-c bg-surface-2 p-4">
    <div class="flex items-center justify-between">
      <span class="text-sm font-semibold text-text">
        {{ t('space.datasets.detail.usage.title') }}
      </span>
      <a-button size="mini" type="text" :loading="loading" @click="loadUsage">
        {{ t('space.datasets.detail.usage.refresh') }}
      </a-button>
    </div>

    <p v-if="failed" class="text-xs text-muted">
      {{ t('space.datasets.detail.usage.loadFailed') }}
    </p>

    <template v-else-if="usage">
      <a-progress
        :percent="usage.usage_percent / 100"
        :show-text="false"
        class="!w-full"
        status="normal"
      />
      <div class="flex justify-between text-xs text-text-2">
        <span>{{ formatBytes(usage.used_bytes) }} / {{ formatBytes(usage.total_bytes) }}</span>
        <span>{{ usage.usage_percent.toFixed(1) }}%</span>
      </div>
      <a-button size="small" type="primary" class="rounded-lg" @click="goUpgrade">
        {{ t('space.datasets.detail.usage.upgrade') }}
      </a-button>
    </template>

    <a-skeleton-line v-else class="!w-full" />
  </div>
</template>