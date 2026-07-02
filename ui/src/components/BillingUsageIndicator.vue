<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { BillingUsageEvent } from '@/models/billing-metering'

const props = defineProps<{
  events: BillingUsageEvent[]
}>()

const { t } = useI18n()
const finalEvent = computed(() => props.events.filter((e) => e.event === 'billing_final').pop() ?? null)
const summaryEvent = computed(() => props.events.filter((e) => e.event === 'billing_summary').pop() ?? null)
const latestEvent = computed(() => props.events[props.events.length - 1])
const isCancelled = computed(() => latestEvent.value?.event === 'billing_cancelled')
const displayEvent = computed(() => finalEvent.value ?? summaryEvent.value ?? latestEvent.value)
const totalCredits = computed(() => displayEvent.value?.total_credits ?? 0)
</script>

<template>
  <div class="inline-flex items-center gap-2 rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-700">
    <span v-if="isCancelled" class="text-orange-600">
      {{ t('billing.usage.cancelled') }}
    </span>
    <span v-else-if="finalEvent">{{ t('billing.realtime.final') }}</span>
    <span v-else-if="summaryEvent">中间汇总</span>
    <span v-else>{{ t('billing.usage.occurred') }}</span>
    <span class="font-semibold text-gray-900">{{ totalCredits }}</span>
    <span>{{ t('billing.usage.unit') }}</span>
  </div>
</template>
