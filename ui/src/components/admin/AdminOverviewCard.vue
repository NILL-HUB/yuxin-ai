<script setup lang="ts">
/**
 * 后台概览卡片，负责展示单个统计指标的标题、数值与说明。
 */
defineProps<{
  title: string
  value: number | string
  description: string
  loading?: boolean
}>()
</script>

<template>
  <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
    <p class="text-sm font-medium text-slate-500">{{ title }}</p>
    <div class="mt-3 min-h-[2.75rem]">
      <div
        v-if="loading"
        class="h-11 w-20 animate-pulse rounded-xl bg-slate-100"
        aria-hidden="true"
      />
      <strong v-else class="block text-3xl font-semibold tracking-tight text-slate-900">
        {{ value }}
      </strong>
    </div>
    <p class="mt-3 text-sm leading-6 text-slate-500">{{ description }}</p>
  </article>
</template>
