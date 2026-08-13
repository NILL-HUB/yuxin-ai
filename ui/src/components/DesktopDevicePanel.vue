<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const desktopApi = (
  window as unknown as {
    yuxinDesktop?: {
      workersStatus: () => Promise<Record<string, { running: boolean; pid?: number }>>
      recycleList: (payload: Record<string, unknown>) => Promise<{ entries?: Array<Record<string, unknown>> }>
      recycleRestore: (payload: Record<string, unknown>) => Promise<unknown>
      wakeStatus: () => Promise<{ running: boolean }>
      wakeEnable: () => Promise<boolean>
      wakeDisable: () => Promise<boolean>
    }
  }
).yuxinDesktop

const available = computed(() => Boolean(desktopApi))
const workers = ref<Record<string, { running: boolean; pid?: number }>>({})
const recycleItems = ref<Array<Record<string, unknown>>>([])
const wakeOn = ref(false)
const restoringId = ref('')

const loadRecycle = async () => {
  if (!desktopApi) return
  try {
    const resp = await desktopApi.recycleList({ only_restorable: true })
    recycleItems.value = resp?.entries || []
  } catch {
    recycleItems.value = []
  }
}

onMounted(async () => {
  if (!desktopApi) return
  try {
    workers.value = await desktopApi.workersStatus()
    const wake = await desktopApi.wakeStatus()
    wakeOn.value = Boolean(wake?.running)
    await loadRecycle()
  } catch {
    // 桌面桥未就绪时静默降级
  }
})

const restoreEntry = async (entry: Record<string, unknown>) => {
  if (!desktopApi) return
  const entryId = String(entry.entry_id || '')
  if (!entryId) return
  restoringId.value = entryId
  try {
    await desktopApi.recycleRestore({ entry_id: entryId })
    await loadRecycle()
  } finally {
    restoringId.value = ''
  }
}

const toggleWake = async () => {
  if (!desktopApi) return
  try {
    if (wakeOn.value) {
      await desktopApi.wakeDisable()
      wakeOn.value = false
    } else {
      await desktopApi.wakeEnable()
      wakeOn.value = true
    }
  } catch {
    // 唤醒词依赖缺失时保持原状态
  }
}
</script>

<template>
  <div v-if="available" class="border rounded-lg bg-white/70 backdrop-blur px-3 py-2 text-sm">
    <div class="flex items-center justify-between gap-2">
      <div class="font-medium">{{ t('desktopDevice.title') }}</div>
      <a-button size="mini" :type="wakeOn ? 'primary' : 'text'" @click="toggleWake">
        {{ wakeOn ? t('desktopDevice.wakeOn') : t('desktopDevice.wakeOff') }}
      </a-button>
    </div>
    <div class="mt-1.5 flex flex-wrap gap-1.5">
      <span
        v-for="(worker, name) in workers"
        :key="name"
        class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs"
        :class="worker.running ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'"
      >
        {{ name }}
      </span>
    </div>
    <div v-if="recycleItems.length > 0" class="mt-2">
      <div class="mb-1 text-xs text-gray-500">{{ t('desktopDevice.recoverable') }}</div>
      <div class="max-h-32 overflow-y-auto space-y-1">
        <div
          v-for="entry in recycleItems"
          :key="String(entry.entry_id || '')"
          class="flex items-center justify-between gap-2 rounded bg-white px-2 py-1 text-xs"
        >
          <span class="truncate">{{ String(entry.original_path || entry.relative_path || '') }}</span>
          <a-button
            size="mini"
            :loading="restoringId === String(entry.entry_id || '')"
            @click="restoreEntry(entry)"
          >
            {{ t('desktopDevice.restore') }}
          </a-button>
        </div>
      </div>
    </div>
  </div>
</template>
