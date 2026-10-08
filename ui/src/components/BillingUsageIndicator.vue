<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { BillingUsageEvent } from '@/models/billing-metering'

const props = withDefaults(
  defineProps<{
    events: BillingUsageEvent[]
    /** 会话级累计消耗（父组件跨轮累加）；传入时卡片主显会话总消耗（2026-10-07 产品要求）。 */
    sessionTotal?: number
  }>(),
  { sessionTotal: -1 },
)

const { t } = useI18n()
const finalEvent = computed(() => props.events.filter((e) => e.event === 'billing_final').pop() ?? null)
const summaryEvent = computed(() => props.events.filter((e) => e.event === 'billing_summary').pop() ?? null)
const latestEvent = computed(() => props.events[props.events.length - 1])
const isCancelled = computed(() => latestEvent.value?.event === 'billing_cancelled')
const displayEvent = computed(() => finalEvent.value ?? summaryEvent.value ?? latestEvent.value)
const hasSessionTotal = computed(() => props.sessionTotal >= 0)
const totalCredits = computed(() =>
  hasSessionTotal.value ? Number(props.sessionTotal) : (displayEvent.value?.total_credits ?? 0),
)
// 算力不足标记：由 billing_final 事件的 metadata 携带（2026-10-07 起后端在扣减
// insufficient 时写入），前端据此明确提示，替代此前的「静默扣 0」。
const insufficient = computed(() => {
  const metadata = (finalEvent.value as { metadata?: Record<string, unknown> } | null)?.metadata
  return Boolean(metadata && metadata.insufficient)
})
</script>

<template>
  <div
    class="inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs text-text"
    :class="insufficient ? 'bg-orange-50' : 'bg-surface-2'"
  >
    <span v-if="isCancelled" class="text-orange-600">
      {{ t('billing.usage.cancelled') }}
    </span>
    <span v-else-if="insufficient" class="text-orange-600">
      {{ t('billing.usage.insufficient') }}
    </span>
    <span v-else-if="hasSessionTotal">{{ t('billing.usage.sessionTotal') }}</span>
    <span v-else-if="finalEvent">{{ t('billing.realtime.final') }}</span>
    <span v-else-if="summaryEvent">中间汇总</span>
    <span v-else>{{ t('billing.usage.occurred') }}</span>
    <span class="font-semibold text-text">{{ totalCredits }}</span>
    <span>{{ t('billing.usage.unit') }}</span>
  </div>
</template>
