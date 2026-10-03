<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

// 桌面端更新弹窗：发现新版本时弹出并展示更新历程。
// 下载与安装全自动（主进程 autoDownload / autoInstallOnAppQuit），用户无需操作；
// 仅在安装包下载完成后提供「立即重启并安装」作为可选的加速入口。
const { t } = useI18n()

type UpdateStatus = 'checking' | 'available' | 'not-available' | 'downloaded' | 'error'
type UpdatePayload = {
  status: UpdateStatus
  version?: string | null
  releaseNotes?: string
  manual?: boolean
}
type DesktopApi = {
  quitAndInstall: () => Promise<{ ok: boolean; reason?: string }>
  onUpdateStatus: (callback: (payload: UpdatePayload) => void) => () => void
}
const desktopApi = (window as unknown as { yujianwoDesktop?: DesktopApi }).yujianwoDesktop

const visible = ref(false)
const status = ref<UpdateStatus>('checking')
const version = ref('')
const releaseNotes = ref('')
const installing = ref(false)
let dispose: (() => void) | null = null

const handleStatus = (payload: UpdatePayload) => {
  if (!payload || !payload.status) return
  status.value = payload.status
  if (payload.version) version.value = payload.version
  if (typeof payload.releaseNotes === 'string') releaseNotes.value = payload.releaseNotes
  // 仅在「发现新版本」时弹出；下载完成只更新弹窗内状态，避免二次打扰
  if (payload.status === 'available') visible.value = true
}

const restartNow = async () => {
  if (installing.value || !desktopApi?.quitAndInstall) return
  installing.value = true
  try {
    await desktopApi.quitAndInstall()
  } finally {
    installing.value = false
  }
}

onMounted(() => {
  if (!desktopApi?.onUpdateStatus) return
  dispose = desktopApi.onUpdateStatus(handleStatus)
})

onUnmounted(() => {
  if (dispose) dispose()
})
</script>

<template>
  <a-modal v-if="desktopApi" v-model:visible="visible" :width="520" :mask-closable="false">
    <template #title>
      {{ status === 'downloaded' ? t('desktopDevice.updateReadyTitle') : t('desktopDevice.updateFoundTitle') }}
    </template>

    <div class="flex flex-col gap-3">
      <div v-if="version" class="text-sm text-[var(--color-text-2)]">
        {{ t('desktopDevice.updateVersionLabel', { version }) }}
      </div>

      <div>
        <div class="mb-1 text-sm font-medium">{{ t('desktopDevice.updateNotesTitle') }}</div>
        <div
          v-if="releaseNotes"
          class="max-h-56 overflow-auto whitespace-pre-wrap rounded border px-3 py-2 text-sm leading-relaxed"
        >
          {{ releaseNotes }}
        </div>
        <div v-else class="text-sm text-[var(--color-text-3)]">
          {{ t('desktopDevice.updateNotesEmpty') }}
        </div>
      </div>

      <div class="text-sm text-[var(--color-text-2)]">
        {{
          status === 'downloaded'
            ? t('desktopDevice.updateReadyDesc')
            : t('desktopDevice.updateDownloadingDesc')
        }}
      </div>
    </div>

    <template #footer>
      <div class="flex justify-end gap-2">
        <a-button v-if="status === 'downloaded'" type="primary" :loading="installing" @click="restartNow">
          {{ t('desktopDevice.updateRestartNow') }}
        </a-button>
        <a-button @click="visible = false">{{ t('desktopDevice.updateLater') }}</a-button>
      </div>
    </template>
  </a-modal>
</template>