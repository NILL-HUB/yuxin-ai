<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import type {
  AdminOrchestrationFlag,
  AdminOrchestrationReleaseCheck,
} from '@/models/admin-orchestration-flag'
import {
  getAdminOrchestrationReleaseCheck,
  listAdminOrchestrationFlags,
  updateAdminOrchestrationFlag,
} from '@/services/admin-orchestration-flags'
import { getErrorMessage } from '@/utils/error'

const { t, locale } = useI18n()
const loading = ref(false)
const flags = ref<AdminOrchestrationFlag[]>([])
const releaseCheck = ref<AdminOrchestrationReleaseCheck | null>(null)

const POOL_GOVERNANCE_PREFIX = 'ENABLE_POOL_GOVERNANCE_'
const POOL_GOVERNANCE_STAGE_ORDER: string[] = [
  'ENABLE_POOL_GOVERNANCE_OBSERVE_ONLY',
  'ENABLE_POOL_GOVERNANCE_BLOCK_SENSITIVE',
  'ENABLE_POOL_GOVERNANCE_BLOCK_ALL',
]
const stageLabels: Record<string, { zh: string; en: string }> = {
  ENABLE_POOL_GOVERNANCE_OBSERVE_ONLY: { zh: '观测期', en: 'Observe only' },
  ENABLE_POOL_GOVERNANCE_BLOCK_SENSITIVE: { zh: '敏感阻断', en: 'Block sensitive' },
  ENABLE_POOL_GOVERNANCE_BLOCK_ALL: { zh: '全量启用', en: 'Block all' },
}

const stageArrow = computed(() =>
  POOL_GOVERNANCE_STAGE_ORDER.map((code) => {
    const lang = locale?.value?.startsWith('zh') ? 'zh' : 'en'
    const label = stageLabels[code]?.[lang] ?? code
    return `${label}(${code.replace(POOL_GOVERNANCE_PREFIX, '')})`
  }).join(' → '),
)

const poolGovernanceFlags = computed(() =>
  flags.value
    .filter((f) => f.code.startsWith(POOL_GOVERNANCE_PREFIX))
    .sort(
      (a, b) =>
        POOL_GOVERNANCE_STAGE_ORDER.indexOf(a.code) -
        POOL_GOVERNANCE_STAGE_ORDER.indexOf(b.code),
    ),
)

const otherFlags = computed(() =>
  flags.value.filter((f) => !f.code.startsWith(POOL_GOVERNANCE_PREFIX)),
)

const groups = computed(() => {
  const result: { key: string; flags: AdminOrchestrationFlag[] }[] = []
  if (poolGovernanceFlags.value.length > 0) {
    result.push({ key: 'poolGovernance', flags: poolGovernanceFlags.value })
  }
  if (otherFlags.value.length > 0) {
    result.push({ key: 'other', flags: otherFlags.value })
  }
  return result
})

const activeKeys = ref<string[]>(['poolGovernance', 'other'])

const groupTitle = (key: string) =>
  key === 'poolGovernance'
    ? t('admin.orchestrationFlags.poolGovernanceGroup')
    : t('admin.orchestrationFlags.otherGroup')

const loadData = async () => {
  loading.value = true
  try {
    const [flagResult, releaseResult] = await Promise.all([
      listAdminOrchestrationFlags(),
      getAdminOrchestrationReleaseCheck(),
    ])
    flags.value = flagResult
    releaseCheck.value = releaseResult
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.orchestrationFlags.loadFailed')))
  } finally {
    loading.value = false
  }
}

const toggleFlag = async (flag: AdminOrchestrationFlag) => {
  const nextEnabled = !flag.enabled
  try {
    const updated = await updateAdminOrchestrationFlag(flag.code, {
      enabled: nextEnabled,
    })
    flag.enabled = updated.enabled
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.orchestrationFlags.updateFailed')))
  }
}

onMounted(loadData)
</script>

<template>
  <section class="space-y-6 p-6">
    <header>
      <h1 class="text-2xl font-semibold text-gray-900">
        {{ t('admin.orchestrationFlags.title') }}
      </h1>
      <p class="mt-1 text-sm text-gray-500">
        {{ t('admin.orchestrationFlags.description') }}
      </p>
    </header>

    <div class="grid gap-4 md:grid-cols-3">
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.orchestrationFlags.flagCount') }}</p>
        <strong class="text-xl">{{ flags.length }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.orchestrationFlags.warningCount') }}</p>
        <strong class="text-xl">{{ releaseCheck?.warnings.length || 0 }}</strong>
      </article>
      <article class="rounded-lg border bg-white p-4">
        <p class="text-sm text-gray-500">{{ t('admin.orchestrationFlags.rollback') }}</p>
        <strong class="text-xl">{{ releaseCheck?.rollback_plan.primary_action || '-' }}</strong>
      </article>
    </div>

    <a-collapse
      v-model:active-key="activeKeys"
      :bordered="false"
      class="bg-transparent"
    >
      <a-collapse-item
        v-for="group in groups"
        :key="group.key"
      >
        <template #header>
          <span class="font-medium">{{ groupTitle(group.key) }}</span>
          <span
            v-if="group.key === 'poolGovernance'"
            class="ml-2 text-xs font-normal text-gray-400"
          >
            {{ t('admin.orchestrationFlags.poolGovernanceGroupDesc') }}
          </span>
        </template>

        <div
          v-if="group.key === 'poolGovernance'"
          class="mb-3 rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-600"
        >
          <p class="font-medium text-gray-700">{{ stageArrow }}</p>
          <p class="mt-1 text-gray-500">
            {{ t('admin.orchestrationFlags.priorityHint') }}
          </p>
        </div>

        <div class="overflow-hidden rounded-lg border bg-white">
          <table class="w-full text-left text-sm">
            <thead class="bg-gray-50 text-gray-500">
              <tr>
                <th class="p-3">{{ t('admin.orchestrationFlags.code') }}</th>
                <th class="p-3">{{ t('admin.orchestrationFlags.name') }}</th>
                <th class="p-3">{{ t('admin.orchestrationFlags.descriptionLabel') }}</th>
                <th class="p-3">{{ t('admin.orchestrationFlags.riskLevel') }}</th>
                <th class="p-3">{{ t('admin.orchestrationFlags.fallbackBehavior') }}</th>
                <th class="p-3">{{ t('admin.orchestrationFlags.enabled') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="flag in group.flags" :key="flag.code" class="border-t">
                <td class="p-3 font-mono">{{ flag.code }}</td>
                <td class="p-3">{{ flag.name }}</td>
                <td class="p-3">{{ flag.description }}</td>
                <td class="p-3">{{ flag.risk_level }}</td>
                <td class="p-3">{{ flag.fallback_behavior }}</td>
                <td class="p-3">
                  <button type="button" :disabled="loading" @click="toggleFlag(flag)">
                    {{ flag.enabled ? t('admin.orchestrationFlags.on') : t('admin.orchestrationFlags.off') }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </a-collapse-item>
    </a-collapse>
  </section>
</template>
