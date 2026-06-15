<script setup lang="ts">
import { computed } from 'vue'
import type { BillingUsageEvent } from '@/models/billing-metering'

const props = defineProps<{
  events: BillingUsageEvent[]
}>()

const latestEvent = computed(() => props.events[props.events.length - 1])
const totalCredits = computed(() => latestEvent.value?.total_credits ?? 0)
const isCancelled = computed(() => latestEvent.value?.event === 'billing_cancelled')
</script>

<template>
  <div class="inline-flex items-center gap-2 rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-700">
    <span v-if="isCancelled" class="text-orange-600">已停止</span>
    <span v-else>已消耗</span>
    <span class="font-semibold text-gray-900">{{ totalCredits }}</span>
    <span>credits</span>
  </div>
</template>
