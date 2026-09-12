<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { semanticLabel } from '@/utils/semantic-labels'
import type { PolicyChangePreview } from '@/services/admin-routing-quality-suggestion'

const props = defineProps<{
  visible: boolean
  loading: boolean
  data: PolicyChangePreview | null
}>()

const emit = defineEmits<{ (e: 'update:visible', value: boolean): void }>()

const { t } = useI18n()

const showRaw = ref(false)

const jsonText = (value: Record<string, unknown> | undefined | null): string => {
  if (!value) return '-'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return '-'
  }
}

const beforeConfig = computed<Record<string, unknown>>(
  () => (props.data?.before_config || {}) as Record<string, unknown>,
)

const afterConfig = computed<Record<string, unknown>>(
  () => (props.data?.after_config || {}) as Record<string, unknown>,
)

const current = computed<Record<string, unknown>>(
  () => ((beforeConfig.value.current_config || beforeConfig.value) || {}) as Record<string, unknown>,
)

const proposed = computed<Record<string, unknown>>(
  () => ((afterConfig.value.proposed_config || afterConfig.value) || {}) as Record<string, unknown>,
)

const impact = computed<Record<string, unknown>>(
  () => (props.data?.impact || {}) as Record<string, unknown>,
)

type FieldRow = { label: string; value: string; tone?: 'plain' | 'warn' | 'ok' }

const tierLabel = (tier: unknown): string =>
  semanticLabel('model_tier', String(tier ?? ''), String(tier ?? '-'))

const actionLabel = (action: unknown): string => {
  const map: Record<string, string> = {
    downgrade_tier: '下调模型档位',
    disable: '停用',
    downgrade_risk_level: '降低风险等级',
    upgrade_tier: '上调模型档位',
  }
  return map[String(action)] ?? String(action ?? '-')
}

const beforeRows = computed<FieldRow[]>(() => {
  const rows: FieldRow[] = []
  if (current.value.tier !== undefined && current.value.tier !== null) {
    rows.push({ label: '当前模型档位', value: tierLabel(current.value.tier) })
  }
  if (current.value.model !== undefined && current.value.model !== null) {
    rows.push({ label: '模型', value: String(current.value.model) })
  }
  if (current.value.avg_cost_credits !== undefined && current.value.avg_cost_credits !== null) {
    rows.push({ label: '平均成本（算力值）', value: String(current.value.avg_cost_credits) })
  }
  if (current.value.avg_rating !== undefined && current.value.avg_rating !== null) {
    rows.push({ label: '平均评分', value: String(current.value.avg_rating) })
  }
  if (current.value.sample_count !== undefined && current.value.sample_count !== null) {
    rows.push({ label: '样本数', value: String(current.value.sample_count) })
  }
  if (current.value.tool_pool !== undefined && current.value.tool_pool !== null) {
    rows.push({ label: '工具池', value: String(current.value.tool_pool) })
  }
  if (current.value.risk_level !== undefined && current.value.risk_level !== null) {
    rows.push({ label: '当前风险等级', value: riskLabel(current.value.risk_level) })
  }
  if (!rows.length) {
    rows.push({ label: '当前配置', value: '—', tone: 'plain' })
  }
  return rows
})

const afterRows = computed<FieldRow[]>(() => {
  const rows: FieldRow[] = []
  if (proposed.value.action !== undefined && proposed.value.action !== null) {
    rows.push({ label: '拟执行动作', value: actionLabel(proposed.value.action), tone: 'warn' })
  }
  if (proposed.value.tier !== undefined && proposed.value.tier !== null) {
    rows.push({ label: '目标模型档位', value: tierLabel(proposed.value.tier) })
  }
  if (proposed.value.expected_cost_credits !== undefined && proposed.value.expected_cost_credits !== null) {
    rows.push({ label: '预计成本（算力值）', value: String(proposed.value.expected_cost_credits) })
  }
  if (proposed.value.risk_level !== undefined && proposed.value.risk_level !== null) {
    rows.push({ label: '目标风险等级', value: riskLabel(proposed.value.risk_level), tone: 'warn' })
  }
  if (proposed.value.reason !== undefined && proposed.value.reason !== null) {
    rows.push({ label: '变更理由', value: String(proposed.value.reason) })
  }
  if (!rows.length) {
    rows.push({ label: '变更后配置', value: '—', tone: 'plain' })
  }
  return rows
})

const riskLabel = (level: unknown): string => {
  const map: Record<string, string> = {
    high: '高风险',
    medium: '中风险',
    low: '低风险',
  }
  return map[String(level)] ?? String(level ?? '-')
}

const impactText = computed(() => {
  const desc = impact.value.description
  const scope = String(impact.value.scope || '')
  const target = String(impact.value.target || '')
  const parts: string[] = []
  if (typeof desc === 'string' && desc) parts.push(desc)
  if (scope || target) {
    const scopeLabel: Record<string, string> = {
      model_routing: '模型路由',
      tool_policy: '工具策略',
      agent_policy: 'Agent 策略',
    }
    parts.push(`影响范围：${scopeLabel[scope] || scope}${target ? ` · ${target}` : ''}`)
  }
  return parts.join(' ')
})
</script>

<template>
  <a-modal
    :visible="visible"
    :title="t('policyChange.preview')"
    :footer="false"
    :width="680"
    @cancel="emit('update:visible', false)"
  >
    <div v-if="loading" class="py-10 text-center text-sm text-slate-400">
      {{ t('admin.routingQuality.loading') }}
    </div>
    <div v-else-if="data" class="space-y-4 text-sm">
      <div class="grid grid-cols-2 gap-3">
        <div>
          <p class="text-xs text-slate-500">{{ t('policyChange.policyType') }}</p>
          <p class="mt-0.5 font-medium text-slate-800">
            {{ semanticLabel('policy_type', data.policy_type, data.policy_type) }}
          </p>
        </div>
        <div>
          <p class="text-xs text-slate-500">{{ t('policyChange.target') }}</p>
          <p class="mt-0.5 break-all font-mono text-xs text-slate-800">{{ data.target_id }}</p>
        </div>
      </div>

      <p v-if="impactText" class="rounded-lg bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
        {{ impactText }}
      </p>

      <div class="rounded-lg border border-slate-200">
        <p class="border-b border-slate-100 px-3 py-2 text-xs font-semibold text-slate-500">
          {{ t('policyChange.beforeConfig') }}
        </p>
        <dl class="grid gap-x-6 gap-y-1.5 px-3 py-2.5 sm:grid-cols-2">
          <div v-for="row in beforeRows" :key="row.label" class="flex items-baseline justify-between gap-2">
            <dt class="text-xs text-slate-500">{{ row.label }}</dt>
            <dd class="text-slate-800">{{ row.value }}</dd>
          </div>
        </dl>
      </div>

      <div class="rounded-lg border border-emerald-200">
        <p class="border-b border-emerald-100 bg-emerald-50/50 px-3 py-2 text-xs font-semibold text-emerald-700">
          {{ t('policyChange.afterConfig') }}
        </p>
        <dl class="grid gap-x-6 gap-y-1.5 px-3 py-2.5 sm:grid-cols-2">
          <div v-for="row in afterRows" :key="row.label" class="flex items-baseline justify-between gap-2">
            <dt class="text-xs text-slate-500">{{ row.label }}</dt>
            <dd class="text-right" :class="row.tone === 'warn' ? 'font-medium text-amber-700' : row.tone === 'ok' ? 'text-emerald-700' : 'text-slate-800'">
              {{ row.value }}
            </dd>
          </div>
        </dl>
      </div>

      <div>
        <button
          type="button"
          class="text-xs font-medium text-sky-600 transition hover:text-sky-700"
          @click="showRaw = !showRaw"
        >
          {{ showRaw ? '收起技术详情' : '查看技术详情 JSON' }}
        </button>
        <template v-if="showRaw">
          <p class="mb-1 mt-2 text-xs font-medium text-slate-500">before / after / diff / impact</p>
          <pre class="max-h-56 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600">{{ jsonText(data as unknown as Record<string, unknown>) }}</pre>
        </template>
      </div>
    </div>
  </a-modal>
</template>
