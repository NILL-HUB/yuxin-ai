<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  activateSandboxBackend,
  getSandboxOverview,
  listSandboxConfigs,
  probeSandbox,
  updateSandboxConfig,
} from '@/services/admin-sandbox'
import type { SandboxCapabilityOverview, SandboxConfigItem } from '@/models/admin-sandbox'
import { getErrorMessage } from '@/utils/error'
import { useAdminStore } from '@/stores/admin'

const { t } = useI18n()
const adminStore = useAdminStore()

type ConfigDraft = { key: string; value: string }
type CredentialMeta = { keys: string[]; masked: Record<string, string> }

const loading = ref(false)
const actionLoading = ref(false)
const overview = ref<SandboxCapabilityOverview[]>([])
/** 每个能力域当前选中的（未必已激活的）后端 */
const selectedBackend = ref<Record<string, string>>({})
/** 草稿：键为 `${capability}::${backend}` */
const drafts = ref<Record<string, ConfigDraft[]>>({})
/** 探测结果：键为 capability */
const probeResults = ref<Record<string, { ok: boolean; reason: string }>>({})
/** 凭证元信息（可配键 + 掩码）：键为 `${capability}::${backend}` */
const credentialMeta = ref<Record<string, CredentialMeta>>({})
/** 凭证草稿（仅暂存待提交值）：键为 `${capability}::${backend}` */
const credentialDrafts = ref<Record<string, Record<string, string>>>({})
/** 已编辑过的凭证键：`${capability}::${backend}::${key}`（只提交被编辑项，避免误清空） */
const credentialTouched = ref<Set<string>>(new Set())

const canUpdate = computed(() => adminStore.hasPermission('sandbox:update'))

const draftKey = (capability: string, backend: string) => `${capability}::${backend}`
const draftKeyOf = (capability: string) => draftKey(capability, selectedBackend.value[capability])

/** 配置行 → 草稿项（仅含后端返回的白名单键，可直接回显编辑）。 */
const toDraft = (row: SandboxConfigItem): ConfigDraft[] =>
  Object.entries(row.configs || {}).map(([key, value]) => ({
    key,
    value: value === null || value === undefined ? '' : String(value),
  }))

const toCredentialDraft = (keys: string[]) =>
  Object.fromEntries(keys.map((key) => [key, '']))

/** 用后端返回的一行覆盖该行草稿与凭证掩码，并清除该行的凭证编辑标记。 */
const applyRowState = (row: SandboxConfigItem) => {
  const rowKey = draftKey(row.capability, row.backend)
  const credentialKeys = row.credential_keys || []
  drafts.value[rowKey] = toDraft(row)
  credentialMeta.value[rowKey] = { keys: credentialKeys, masked: row.credentials || {} }
  credentialDrafts.value[rowKey] = toCredentialDraft(credentialKeys)
  const touched = new Set(credentialTouched.value)
  for (const key of credentialKeys) touched.delete(`${rowKey}::${key}`)
  credentialTouched.value = touched
}

/** 仅刷新各能力域概览（激活态 / 可用性 / 原因），不动草稿与用户选择。 */
const refreshOverview = async () => {
  const resp = await getSandboxOverview()
  overview.value = resp.data.items || []
}

const activeBackendOf = (capability: string) =>
  overview.value.find((item) => item.capability === capability)?.active_backend

const capabilityLabel = (capability: string) => {
  const key = `admin.sandbox.capabilityLabel.${capability}`
  const label = t(key)
  return label === key ? capability : label
}

const backendLabel = (backend: string, fallback: string) => {
  const key = `admin.sandbox.backends.${backend}`
  const label = t(key)
  return label === key ? fallback || backend : label
}

const currentDraft = (capability: string) => {
  const backend = selectedBackend.value[capability]
  return drafts.value[draftKey(capability, backend)] || []
}

const currentCredentialKeys = (capability: string) =>
  credentialMeta.value[draftKeyOf(capability)]?.keys || []

const credentialPlaceholder = (capability: string, key: string) => {
  const masked = credentialMeta.value[draftKeyOf(capability)]?.masked?.[key]
  return masked || t('admin.sandbox.credentialEmpty')
}

const onCredentialInput = (capability: string, key: string, value: string) => {
  const rowKey = draftKeyOf(capability)
  if (!credentialDrafts.value[rowKey]) credentialDrafts.value[rowKey] = {}
  credentialDrafts.value[rowKey][key] = value ?? ''
  credentialTouched.value.add(`${rowKey}::${key}`)
}

const loadAll = async () => {
  loading.value = true
  try {
    const [overviewResp, configsResp] = await Promise.all([
      getSandboxOverview(),
      listSandboxConfigs(),
    ])
    overview.value = overviewResp.data.items || []

    // 以配置行为准重建草稿（每行仅含白名单键，可直接回显编辑）
    const nextDrafts: Record<string, ConfigDraft[]> = {}
    const nextCredentialMeta: Record<string, CredentialMeta> = {}
    const nextCredentialDrafts: Record<string, Record<string, string>> = {}
    for (const row of configsResp.data.items || []) {
      const rowKey = draftKey(row.capability, row.backend)
      const credentialKeys = row.credential_keys || []
      nextDrafts[rowKey] = toDraft(row)
      nextCredentialMeta[rowKey] = { keys: credentialKeys, masked: row.credentials || {} }
      nextCredentialDrafts[rowKey] = toCredentialDraft(credentialKeys)
    }
    drafts.value = nextDrafts
    credentialMeta.value = nextCredentialMeta
    credentialDrafts.value = nextCredentialDrafts
    credentialTouched.value = new Set()

    for (const item of overview.value) {
      selectedBackend.value[item.capability] = item.active_backend
    }
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.sandbox.loadFailed')))
  } finally {
    loading.value = false
  }
}

const selectBackend = (capability: string, backend: string) => {
  selectedBackend.value[capability] = backend
}

const activate = async (capability: string) => {
  const backend = selectedBackend.value[capability]
  if (!backend) return
  actionLoading.value = true
  try {
    await activateSandboxBackend(capability, backend)
    Message.success(t('admin.sandbox.activateSuccess'))
    // 只刷新概览（激活态 / 可用性 / 原因），不重建草稿、不重置用户选择
    await refreshOverview()
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.sandbox.actionFailed')))
  } finally {
    actionLoading.value = false
  }
}

const addConfigItem = (capability: string) => {
  const backend = selectedBackend.value[capability]
  const key = draftKey(capability, backend)
  drafts.value[key] = [...(drafts.value[key] || []), { key: '', value: '' }]
}

const removeConfigItem = (capability: string, index: number) => {
  const backend = selectedBackend.value[capability]
  const key = draftKey(capability, backend)
  drafts.value[key] = (drafts.value[key] || []).filter((_item, i) => i !== index)
}

const saveConfig = async (capability: string) => {
  const backend = selectedBackend.value[capability]
  const rowKey = draftKey(capability, backend)
  const configs: Record<string, string> = {}
  for (const field of currentDraft(capability)) {
    const name = field.key.trim()
    if (!name) continue
    configs[name] = field.value
  }
  // 仅提交**被编辑过**的凭证键（含显式清空的空值），避免误清空未触碰的既有凭证
  const credentials: Record<string, string> = {}
  for (const key of Object.keys(credentialDrafts.value[rowKey] || {})) {
    if (credentialTouched.value.has(`${rowKey}::${key}`)) {
      credentials[key] = credentialDrafts.value[rowKey][key] || ''
    }
  }
  actionLoading.value = true
  try {
    const resp = await updateSandboxConfig(capability, backend, configs, credentials)
    // 只同步该行（白名单回显 + 掩码刷新），不整页重建：保留其它卡片的未保存编辑与当前选择
    applyRowState(resp.data.item)
    if (backend === activeBackendOf(capability)) {
      // 保存的是激活后端：配置变化会影响可用性展示，刷新概览
      await refreshOverview()
      Message.success(t('admin.sandbox.saveSuccess'))
    } else {
      // 保存 ≠ 切换：明确提示尚未激活，避免"保存成功即已切换"的误解
      Message.success(t('admin.sandbox.saveSuccessNotActivated'))
    }
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.sandbox.actionFailed')))
  } finally {
    actionLoading.value = false
  }
}

const probe = async (capability: string) => {
  actionLoading.value = true
  try {
    const resp = await probeSandbox(capability)
    const result = resp.data
    probeResults.value[capability] = { ok: result.ok, reason: result.reason || '' }
    if (result.ok) {
      Message.success(t('admin.sandbox.probeOk'))
    } else {
      Message.warning(t('admin.sandbox.probeFail', { reason: result.reason || '-' }))
    }
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.sandbox.actionFailed')))
  } finally {
    actionLoading.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="space-y-4">
    <a-card :bordered="false">
      <div class="flex items-start justify-between gap-4">
        <div>
          <h2 class="text-lg font-medium">{{ t('admin.sandbox.title') }}</h2>
          <p class="text-sm text-gray-500 mt-1">{{ t('admin.sandbox.subtitle') }}</p>
        </div>
        <a-button :loading="loading" @click="loadAll">
          {{ t('common.actions.refresh') }}
        </a-button>
      </div>
    </a-card>

    <a-card v-for="item in overview" :key="item.capability" :bordered="false">
      <template #title>
        <div class="flex items-center gap-3">
          <span>{{ capabilityLabel(item.capability) }}</span>
          <a-tag :color="item.enabled ? 'green' : 'red'">
            {{ item.enabled ? t('admin.sandbox.statusEnabled') : t('admin.sandbox.statusDisabled') }}
          </a-tag>
        </div>
      </template>

      <div class="space-y-3">
        <div class="text-sm text-gray-600">
          <span>{{ t('admin.sandbox.activeBackend') }}：</span>
          <span class="font-medium">{{ item.active_backend }}</span>
          <span v-if="!item.enabled" class="ml-3 text-red-600">
            {{ t('admin.sandbox.reasonLabel') }}：{{ item.reason || t('admin.sandbox.noReason') }}
          </span>
        </div>

        <a-radio-group
          :model-value="selectedBackend[item.capability]"
          :disabled="!canUpdate"
          @change="(value: string | number | boolean) => selectBackend(item.capability, String(value))"
        >
          <a-radio v-for="option in item.backends" :key="option.backend" :value="option.backend">
            {{ backendLabel(option.backend, option.label) }}
          </a-radio>
        </a-radio-group>

        <div class="flex items-center gap-2">
          <a-button
            type="primary"
            size="small"
            :disabled="!canUpdate"
            :loading="actionLoading"
            @click="activate(item.capability)"
          >
            {{ t('admin.sandbox.activate') }}
          </a-button>
          <a-button size="small" :loading="actionLoading" @click="probe(item.capability)">
            {{ t('admin.sandbox.probe') }}
          </a-button>
          <span
            v-if="probeResults[item.capability]"
            :class="probeResults[item.capability].ok ? 'text-green-600' : 'text-red-600'"
            class="text-xs"
          >
            {{ probeResults[item.capability].ok ? t('admin.sandbox.probeOk') : probeResults[item.capability].reason }}
          </span>
        </div>

        <div class="border-t pt-3">
          <div class="text-sm font-medium mb-2">{{ t('admin.sandbox.configTitle') }}</div>
          <div v-if="!currentDraft(item.capability).length" class="text-xs text-gray-400">
            {{ t('admin.sandbox.noConfigItems') }}
          </div>
          <div
            v-for="(field, index) in currentDraft(item.capability)"
            :key="`${field.key}-${index}`"
            class="flex items-center gap-2 mb-2"
          >
            <a-input
              v-model="field.key"
              :disabled="!canUpdate"
              :placeholder="t('admin.sandbox.keyPlaceholder')"
              class="w-48"
            />
            <a-input
              v-model="field.value"
              :disabled="!canUpdate"
              :placeholder="t('admin.sandbox.valuePlaceholder')"
              class="w-72"
            />
            <a-button v-if="canUpdate" size="mini" type="text" @click="removeConfigItem(item.capability, index)">
              {{ t('admin.sandbox.removeConfigItem') }}
            </a-button>
          </div>
          <div v-if="canUpdate" class="flex items-center gap-2">
            <a-button size="mini" @click="addConfigItem(item.capability)">
              {{ t('admin.sandbox.addConfigItem') }}
            </a-button>
            <a-button size="mini" type="primary" :loading="actionLoading" @click="saveConfig(item.capability)">
              {{ t('admin.sandbox.saveConfig') }}
            </a-button>
          </div>
        </div>

        <div class="border-t pt-3">
          <div class="text-sm font-medium mb-2">{{ t('admin.sandbox.credentialTitle') }}</div>
          <div class="text-xs text-gray-500 mb-2 leading-5">
            {{ t('admin.sandbox.credentialHint') }}
          </div>
          <div v-if="!currentCredentialKeys(item.capability).length" class="text-xs text-gray-400">
            {{ t('admin.sandbox.noCredentialKeys') }}
          </div>
          <div
            v-for="key in currentCredentialKeys(item.capability)"
            :key="key"
            class="flex items-center gap-2 mb-2"
          >
            <span class="w-48 font-mono text-xs text-gray-600">{{ key }}</span>
            <a-input
              :model-value="credentialDrafts[draftKeyOf(item.capability)]?.[key] || ''"
              :disabled="!canUpdate"
              :placeholder="credentialPlaceholder(item.capability, key)"
              class="w-72"
              allow-clear
              @update:model-value="(v: string) => onCredentialInput(item.capability, key, v)"
            />
          </div>
        </div>
      </div>
    </a-card>
  </div>
</template>
