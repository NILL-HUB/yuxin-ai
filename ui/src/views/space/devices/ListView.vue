<template>
  <div class="mx-auto flex w-full max-w-4xl flex-col gap-4 px-4 py-6">
    <header class="flex items-start justify-between gap-4">
      <div>
        <h1 class="text-lg font-semibold text-primary">{{ t('devices.title') }}</h1>
        <p class="mt-1 text-sm text-muted">{{ t('devices.subtitle') }}</p>
      </div>
      <a-button size="small" :loading="loading" @click="load">
        {{ t('devices.refresh') }}
      </a-button>
    </header>

    <a-spin :loading="loading" class="w-full">
      <div v-if="!devices.length" class="rounded-lg border border-dashed border-[var(--color-border)] p-8 text-center">
        <p class="text-sm font-medium text-primary">{{ t('devices.empty') }}</p>
        <p class="mt-1 text-xs text-muted">{{ t('devices.emptyHint') }}</p>
      </div>

      <div v-else class="flex flex-col gap-3">
        <article
          v-for="device in devices"
          :key="device.device_id"
          class="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-2)] p-4"
        >
          <div class="flex flex-wrap items-center gap-2">
            <icon-computer class="shrink-0 text-muted" />
            <template v-if="renamingId === device.device_id">
              <a-input
                v-model="renameDraft"
                size="small"
                class="max-w-56"
                :placeholder="t('devices.renamePlaceholder')"
                @press-enter="submitRename(device)"
              />
              <a-button size="mini" type="primary" :loading="actionLoading" @click="submitRename(device)">
                {{ t('devices.renameSave') }}
              </a-button>
              <a-button size="mini" @click="cancelRename">{{ t('devices.renameCancel') }}</a-button>
            </template>
            <template v-else>
              <span class="font-medium text-primary">{{ device.name || device.device_id }}</span>
              <a-tag v-if="device.is_default" size="small">{{ t('devices.defaultBadge') }}</a-tag>
            </template>
            <a-tag :color="statusColor(device.status)" size="small">
              {{ statusLabel(device.status) }}
            </a-tag>
          </div>

          <div class="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted">
            <span>{{ t('devices.platform') }}: {{ device.platform || t('devices.never') }}</span>
            <span>{{ t('devices.lastSeen') }}: {{ device.last_seen_at || t('devices.never') }}</span>
          </div>

          <p v-if="device.status === 'offline'" class="text-xs text-amber-600">
            {{ t('devices.offlineHint') }}
          </p>

          <div class="flex flex-wrap gap-2">
            <a-button
              size="small"
              type="primary"
              :disabled="device.status === 'revoked'"
              @click="useDevice(device)"
            >
              {{ t('devices.use') }}
            </a-button>
            <a-button size="small" :disabled="device.status === 'revoked'" @click="startRename(device)">
              {{ t('devices.rename') }}
            </a-button>
            <a-button
              size="small"
              :disabled="device.is_default || device.status === 'revoked'"
              :loading="actionLoading"
              @click="setDefault(device)"
            >
              {{ t('devices.setDefault') }}
            </a-button>
            <a-popconfirm :content="t('devices.revokeConfirm')" @ok="revoke(device)">
              <a-button size="small" status="danger" :disabled="device.status === 'revoked'">
                {{ t('devices.revoke') }}
              </a-button>
            </a-popconfirm>
          </div>
        </article>
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import {
  listDesktopDevices,
  revokeDesktopDevice,
  updateDesktopDevice,
  type DesktopDeviceItem,
} from '@/services/desktop-device'

const { t } = useI18n()
const router = useRouter()

const devices = ref<DesktopDeviceItem[]>([])
const loading = ref(false)
const actionLoading = ref(false)
const renamingId = ref('')
const renameDraft = ref('')

const load = async () => {
  loading.value = true
  try {
    const resp = await listDesktopDevices()
    devices.value = resp.data || []
  } catch {
    Message.error(t('devices.loadFailed'))
  } finally {
    loading.value = false
  }
}

const statusLabel = (status: string) => {
  if (status === 'online') return t('devices.statusOnline')
  if (status === 'revoked') return t('devices.statusRevoked')
  return t('devices.statusOffline')
}

const statusColor = (status: string) => {
  if (status === 'online') return 'green'
  if (status === 'revoked') return 'gray'
  return 'orange'
}

// 选择设备后进入对话：device_id 经 URL 查询参数下传，HomeView 在发送时
// 透传给 /assistant-agent/chat，由服务端写入会话绑定（会话内本机操作随该设备执行）。
const useDevice = (device: DesktopDeviceItem) => {
  router.push({ path: '/home', query: { device_id: device.device_id } })
}

const startRename = (device: DesktopDeviceItem) => {
  renamingId.value = device.device_id
  renameDraft.value = device.name || ''
}

const cancelRename = () => {
  renamingId.value = ''
  renameDraft.value = ''
}

const applyUpdate = (deviceId: string, updated?: DesktopDeviceItem) => {
  if (!updated) return
  devices.value = devices.value.map((item) =>
    item.device_id === deviceId ? { ...item, ...updated } : item,
  )
}

const submitRename = async (device: DesktopDeviceItem) => {
  const name = renameDraft.value.trim()
  if (!name) {
    Message.warning(t('devices.nameRequired'))
    return
  }
  if (name.length > 128) {
    Message.warning(t('devices.nameTooLong'))
    return
  }
  actionLoading.value = true
  try {
    const resp = await updateDesktopDevice(device.device_id, { name })
    applyUpdate(device.device_id, resp.data)
    cancelRename()
    Message.success(t('devices.renamed'))
  } catch {
    Message.error(t('devices.actionFailed'))
  } finally {
    actionLoading.value = false
  }
}

const setDefault = async (device: DesktopDeviceItem) => {
  actionLoading.value = true
  try {
    const resp = await updateDesktopDevice(device.device_id, { is_default: true })
    applyUpdate(device.device_id, resp.data)
    // 默认设备互斥：服务端会把其他设备置为非默认，刷新一次保证列表一致
    await load()
    Message.success(t('devices.defaultSet'))
  } catch {
    Message.error(t('devices.actionFailed'))
  } finally {
    actionLoading.value = false
  }
}

const revoke = async (device: DesktopDeviceItem) => {
  actionLoading.value = true
  try {
    await revokeDesktopDevice(device.device_id)
    await load()
    Message.success(t('devices.revokeOk'))
  } catch {
    Message.error(t('devices.actionFailed'))
  } finally {
    actionLoading.value = false
  }
}

onMounted(load)
</script>
