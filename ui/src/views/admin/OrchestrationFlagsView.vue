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

const { t } = useI18n()
const loading = ref(false)
const flags = ref<AdminOrchestrationFlag[]>([])
const releaseCheck = ref<AdminOrchestrationReleaseCheck | null>(null)

const POOL_GOVERNANCE_PREFIX = 'ENABLE_POOL_GOVERNANCE_'
const POOL_GOVERNANCE_STAGE_ORDER: string[] = [
  'ENABLE_POOL_GOVERNANCE_OBSERVE_ONLY',
  'ENABLE_POOL_GOVERNANCE_BLOCK_SENSITIVE',
  'ENABLE_POOL_GOVERNANCE_BLOCK_ALL',
]

// 开关中文名映射
const flagName = (code: string) => {
  const key = `admin.orchestrationFlags.flagNames.${code}`
  const translated = t(key)
  return translated === key ? code : translated
}

// 开关中文说明映射
const flagDescription = (code: string) => {
  const key = `admin.orchestrationFlags.flagDesc.${code}`
  const translated = t(key)
  return translated === key ? '' : translated
}

// 回退策略中文映射
const fallbackLabel = (behavior: string) => {
  if (!behavior) return '-'
  const key = `admin.orchestrationFlags.fallback.${behavior}`
  const translated = t(key)
  return translated === key ? behavior : translated
}

// 开启后影响说明
const enableEffect = (code: string) => {
  const key = `admin.orchestrationFlags.enableEffect.${code}`
  const translated = t(key)
  return translated === key ? '' : translated
}

// 关闭后影响说明
const disableEffect = (code: string) => {
  const key = `admin.orchestrationFlags.disableEffect.${code}`
  const translated = t(key)
  return translated === key ? '' : translated
}

const stageArrow = computed(() =>
  POOL_GOVERNANCE_STAGE_ORDER.map((code) => flagName(code)).join(' → '),
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

const enabledCount = computed(() => flags.value.filter((f) => f.enabled).length)

const groupTitle = (key: string) =>
  key === 'poolGovernance'
    ? t('admin.orchestrationFlags.poolGovernanceGroup')
    : t('admin.orchestrationFlags.otherGroup')

const riskColor = (level: string) => {
  switch (level) {
    case 'high':
      return 'red'
    case 'medium':
      return 'orange'
    case 'low':
      return 'green'
    default:
      return 'gray'
  }
}

const riskLabel = (level: string) => {
  const key = `admin.orchestrationFlags.riskLevels.${level}`
  const translated = t(key)
  return translated === key ? level : translated
}

// ===== 切换确认弹窗 =====
const confirmVisible = ref(false)
const confirmFlag = ref<AdminOrchestrationFlag | null>(null)
const confirmNextVal = ref(false)
const confirming = ref(false)

const confirmTitle = computed(() => {
  if (!confirmFlag.value) return ''
  const name = flagName(confirmFlag.value.code)
  const key = confirmNextVal.value
    ? 'admin.orchestrationFlags.confirm.enableTitle'
    : 'admin.orchestrationFlags.confirm.disableTitle'
  return t(key, { name })
})

const confirmEffectText = computed(() => {
  if (!confirmFlag.value) return ''
  return confirmNextVal.value
    ? enableEffect(confirmFlag.value.code)
    : disableEffect(confirmFlag.value.code)
})

const confirmTipText = computed(() =>
  confirmNextVal.value
    ? t('admin.orchestrationFlags.confirm.enableTip')
    : t('admin.orchestrationFlags.confirm.disableTip'),
)

const confirmActionText = computed(() =>
  confirmNextVal.value
    ? t('admin.orchestrationFlags.confirm.enableAction')
    : t('admin.orchestrationFlags.confirm.disableAction'),
)

const confirmActionColor = computed(() =>
  confirmNextVal.value ? '#00b42a' : '#f53f3f',
)

const openConfirm = (flag: AdminOrchestrationFlag, nextVal: boolean) => {
  confirmFlag.value = flag
  confirmNextVal.value = nextVal
  confirmVisible.value = true
}

const handleConfirm = async () => {
  if (!confirmFlag.value) return
  confirming.value = true
  try {
    const updated = await updateAdminOrchestrationFlag(confirmFlag.value.code, {
      enabled: confirmNextVal.value,
    })
    const target = flags.value.find((f) => f.code === confirmFlag.value!.code)
    if (target) target.enabled = updated.enabled
    confirmVisible.value = false
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.orchestrationFlags.updateFailed')))
  } finally {
    confirming.value = false
  }
}

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

const tableColumns = computed(() => [
  { title: t('admin.orchestrationFlags.name'), dataIndex: 'name', slotName: 'name' },
  { title: t('admin.orchestrationFlags.descriptionLabel'), dataIndex: 'description', slotName: 'description' },
  { title: t('admin.orchestrationFlags.riskLevel'), slotName: 'risk' },
  { title: t('admin.orchestrationFlags.fallbackBehavior'), dataIndex: 'fallback_behavior', slotName: 'fallback' },
  { title: t('admin.orchestrationFlags.enabled'), slotName: 'enabled', width: 100 },
])

onMounted(loadData)
</script>

<template>
  <section class="flags-page">
    <header class="flags-header">
      <div class="header-left">
        <h1>{{ t('admin.orchestrationFlags.title') }}</h1>
        <p>{{ t('admin.orchestrationFlags.description') }}</p>
      </div>
      <div class="header-badge">
        <span class="badge-dot" />
        <span>{{ enabledCount }} / {{ flags.length }}</span>
      </div>
    </header>

    <div class="stats-grid">
      <article class="stat-card">
        <div class="stat-icon stat-icon--blue">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z" />
          </svg>
        </div>
        <div class="stat-body">
          <p class="stat-label">{{ t('admin.orchestrationFlags.flagCount') }}</p>
          <strong class="stat-value">{{ flags.length }}</strong>
        </div>
      </article>
      <article class="stat-card">
        <div class="stat-icon stat-icon--amber">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            <path d="M12 9v4M12 17h.01" />
          </svg>
        </div>
        <div class="stat-body">
          <p class="stat-label">{{ t('admin.orchestrationFlags.warningCount') }}</p>
          <strong class="stat-value" :class="{ 'stat-value--warn': (releaseCheck?.warnings.length || 0) > 0 }">
            {{ releaseCheck?.warnings.length || 0 }}
          </strong>
        </div>
      </article>
      <article class="stat-card">
        <div class="stat-icon stat-icon--green">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 14L4 9l-2 2 7 7L20 6l-2-2z" />
          </svg>
        </div>
        <div class="stat-body">
          <p class="stat-label">{{ t('admin.orchestrationFlags.rollback') }}</p>
          <strong class="stat-value stat-value--sm">{{ releaseCheck?.rollback_plan.primary_action || '-' }}</strong>
        </div>
      </article>
    </div>

    <a-spin :loading="loading" style="display: block">
      <a-collapse
        v-model:active-key="activeKeys"
        :bordered="false"
        class="flags-collapse"
      >
        <a-collapse-item
          v-for="group in groups"
          :key="group.key"
        >
          <template #header>
            <div class="group-header-inner">
              <span class="group-header-title">{{ groupTitle(group.key) }}</span>
              <a-tag size="small" color="gray" bordered>{{ group.flags.length }}</a-tag>
              <span
                v-if="group.key === 'poolGovernance'"
                class="group-header-desc"
              >
                {{ t('admin.orchestrationFlags.poolGovernanceGroupDesc') }}
              </span>
            </div>
          </template>

          <div
            v-if="group.key === 'poolGovernance'"
            class="stage-hint"
          >
            <p class="stage-arrow">{{ stageArrow }}</p>
            <p class="stage-priority">
              {{ t('admin.orchestrationFlags.priorityHint') }}
            </p>
          </div>

          <a-table
            :columns="tableColumns"
            :data="group.flags"
            :pagination="false"
            row-key="code"
            :bordered="{ wrapper: true, cell: true }"
            size="medium"
            class="flags-table"
          >
            <template #name="{ record }">
              <div class="flag-name-cell">
                <span class="flag-name-text">{{ flagName(record.code) }}</span>
                <a-tooltip :content="record.code" position="top" mini>
                  <code class="flag-code">{{ record.code }}</code>
                </a-tooltip>
              </div>
            </template>
            <template #description="{ record }">
              <span class="flag-desc-text">{{ flagDescription(record.code) || record.description }}</span>
            </template>
            <template #risk="{ record }">
              <a-tag :color="riskColor(record.risk_level)" size="small" bordered>
                {{ riskLabel(record.risk_level) }}
              </a-tag>
            </template>
            <template #fallback="{ record }">
              <span class="flag-fallback-text">{{ fallbackLabel(record.fallback_behavior) }}</span>
            </template>
            <template #enabled="{ record }">
              <a-switch
                :model-value="record.enabled"
                :loading="loading"
                @change="(val: string | number | boolean) => openConfirm(record, !!val)"
              />
            </template>
          </a-table>
        </a-collapse-item>
      </a-collapse>
    </a-spin>

    <!-- 切换确认弹窗 -->
    <a-modal
      v-model:visible="confirmVisible"
      :title="confirmTitle"
      :ok-text="confirmActionText"
      :cancel-text="t('admin.orchestrationFlags.confirm.cancel')"
      :ok-loading="confirming"
      :mask-closable="false"
      :width="520"
      @ok="handleConfirm"
    >
      <div v-if="confirmFlag" class="confirm-body">
        <div class="confirm-row">
          <span class="confirm-label">{{ t('admin.orchestrationFlags.confirm.actionLabel') }}</span>
          <a-tag :color="confirmActionColor" size="small" bordered>
            {{ confirmActionText }}
          </a-tag>
        </div>
        <div class="confirm-row">
          <span class="confirm-label">{{ t('admin.orchestrationFlags.riskLevel') }}</span>
          <a-tag :color="riskColor(confirmFlag.risk_level)" size="small" bordered>
            {{ riskLabel(confirmFlag.risk_level) }}
          </a-tag>
        </div>
        <div class="confirm-row">
          <span class="confirm-label">{{ t('admin.orchestrationFlags.confirm.fallbackLabel') }}</span>
          <span class="confirm-value">{{ fallbackLabel(confirmFlag.fallback_behavior) }}</span>
        </div>
        <a-divider class="confirm-divider" />
        <div class="confirm-effect">
          <p class="confirm-effect-tip">{{ confirmTipText }}</p>
          <p class="confirm-effect-text">{{ confirmEffectText }}</p>
        </div>
      </div>
    </a-modal>
  </section>
</template>

<style scoped>
.flags-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
  width: 100%;
}

.flags-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.header-left h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: #1d2129;
  letter-spacing: -0.02em;
}

.header-left p {
  margin: 4px 0 0;
  font-size: 13px;
  color: #86909c;
}

.header-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 999px;
  background: #f2f3f5;
  font-size: 13px;
  font-weight: 600;
  color: #4e5969;
  white-space: nowrap;
}

.badge-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #00b42a;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #e5e6eb;
  transition: box-shadow 0.2s ease;
}

.stat-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
}

.stat-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  min-width: 40px;
  border-radius: 10px;
}

.stat-icon--blue {
  background: #e8f3ff;
  color: #165dff;
}

.stat-icon--amber {
  background: #fff7e8;
  color: #ff7d00;
}

.stat-icon--green {
  background: #e8ffea;
  color: #00b42a;
}

.stat-label {
  margin: 0;
  font-size: 12px;
  color: #86909c;
}

.stat-value {
  display: block;
  margin-top: 2px;
  font-size: 22px;
  font-weight: 700;
  color: #1d2129;
}

.stat-value--sm {
  font-size: 14px;
  word-break: break-all;
}

.stat-value--warn {
  color: #ff7d00;
}

.flags-collapse {
  background: #fff;
  border-radius: 12px;
  border: 1px solid #e5e6eb;
  overflow: hidden;
}

.group-header-inner {
  display: flex;
  align-items: center;
  gap: 8px;
}

.group-header-title {
  font-weight: 600;
  font-size: 14px;
  color: #1d2129;
}

.group-header-desc {
  font-size: 12px;
  color: #86909c;
}

.stage-hint {
  margin-bottom: 12px;
  padding: 12px 16px;
  border-radius: 8px;
  background: #f7f8fa;
  border-left: 3px solid #165dff;
}

.stage-arrow {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: #4e5969;
}

.stage-priority {
  margin: 4px 0 0;
  font-size: 12px;
  color: #86909c;
}

.flags-table {
  border-radius: 8px;
  overflow: hidden;
}

.flag-name-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.flag-name-text {
  font-weight: 600;
  font-size: 13px;
  color: #1d2129;
}

.flag-desc-text {
  font-size: 12px;
  color: #4e5969;
}

.flag-fallback-text {
  font-size: 12px;
  color: #86909c;
}

.flag-code {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 11px;
  color: #86909c;
  background: #f2f3f5;
  padding: 1px 6px;
  border-radius: 3px;
  display: inline-block;
  width: fit-content;
}

/* 切换确认弹窗 */
.confirm-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.confirm-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.confirm-label {
  min-width: 70px;
  font-size: 13px;
  color: #86909c;
}

.confirm-value {
  font-size: 13px;
  color: #1d2129;
}

.confirm-divider {
  margin: 4px 0;
}

.confirm-effect {
  padding: 12px 14px;
  border-radius: 8px;
  background: #f7f8fa;
  border-left: 3px solid #165dff;
}

.confirm-effect-tip {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: #4e5969;
}

.confirm-effect-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #1d2129;
}

@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .flags-header {
    flex-direction: column;
  }
}
</style>
