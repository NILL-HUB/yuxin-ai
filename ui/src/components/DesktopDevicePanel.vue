<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

type WorkerInfo = { running: boolean; pid?: number; version?: string | null }
type DesktopApi = {
  workersStatus: () => Promise<Record<string, WorkerInfo>>
  getWorkerVersions: () => Promise<Record<string, WorkerInfo>>
  getLaunchAtLogin: () => Promise<boolean>
  setLaunchAtLogin: (enabled: boolean) => Promise<unknown>
  checkForUpdates: () => Promise<{ ok: boolean; reason?: string }>
  recycleList: (payload: Record<string, unknown>) => Promise<{ entries?: Array<Record<string, unknown>> }>
  recycleRestore: (payload: Record<string, unknown>) => Promise<unknown>
  wakeStatus: () => Promise<{ running: boolean }>
  wakeEnable: () => Promise<boolean>
  wakeDisable: () => Promise<boolean>
}
const desktopApi = (window as unknown as { yuxinDesktop?: DesktopApi }).yuxinDesktop

const available = computed(() => Boolean(desktopApi))
const workers = ref<Record<string, WorkerInfo>>({})
const recycleItems = ref<Array<Record<string, unknown>>>([])
const wakeOn = ref(false)
const restoringId = ref('')
const launchAtLogin = ref(false)
const updating = ref(false)
const updateNote = ref('')

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
    const [status, versions, launch] = await Promise.all([
      desktopApi.workersStatus(),
      desktopApi.getWorkerVersions(),
      desktopApi.getLaunchAtLogin(),
    ])
    for (const [name, info] of Object.entries(status || {})) {
      workers.value[name] = { ...info }
    }
    for (const [name, info] of Object.entries(versions || {})) {
      const merged = { ...(workers.value[name] || {}), ...info }
      workers.value[name] = merged
    }
    launchAtLogin.value = Boolean(launch)
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

const toggleLaunchAtLogin = async () => {
  if (!desktopApi) return
  const next = !launchAtLogin.value
  try {
    await desktopApi.setLaunchAtLogin(next)
    launchAtLogin.value = next
  } catch {
    // 设置失败时保持原状态
  }
}

const checkUpdate = async () => {
  if (!desktopApi || updating.value) return
  updating.value = true
  updateNote.value = t('desktopDevice.updateChecking')
  try {
    const result = await desktopApi.checkForUpdates()
    if (!result?.ok) {
      updateNote.value =
        result?.reason === 'updater_disabled' ? t('desktopDevice.updateUnavailable') : t('desktopDevice.updateCheckFailed')
      return
    }
    updateNote.value = t('desktopDevice.updateChecking')
  } catch {
    updateNote.value = t('desktopDevice.updateCheckFailed')
  } finally {
    updating.value = false
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
    <div class="mt-1.5 flex flex-col gap-1.5">
      <div
        v-for="(worker, name) in workers"
        :key="name"
        class="flex items-center justify-between gap-2 rounded px-1.5 py-0.5 text-xs"
        :class="worker.running ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'"
      >
        <span class="flex items-center gap-1">
          <span class="font-medium">{{ name }}</span>
          <span v-if="worker.version">{{ t('desktopDevice.version') }} {{ worker.version }}</span>
          <span v-if="!worker.running">{{ t('desktopDevice.stopped') }}</span>
        </span>
        <span v-if="worker.pid" class="text-[10px] opacity-70">pid {{ worker.pid }}</span>
      </div>
    </div>
    <div class="mt-2 flex items-center justify-between gap-2 rounded bg-white/60 px-2 py-1.5 text-xs">
      <span>{{ t('desktopDevice.launchAtLogin') }}</span>
      <a-switch size="small" :model-value="launchAtLogin" @change="toggleLaunchAtLogin" />
    </div>
    <div class="mt-2 flex items-center justify-between gap-2 rounded bg-white/60 px-2 py-1.5 text-xs">
      <a-button size="mini" :loading="updating" @click="checkUpdate">
        {{ t('desktopDevice.checkUpdate') }}
      </a-button>
      <span v-if="updateNote" class="text-[10px] text-gray-500">{{ updateNote }}</span>
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
