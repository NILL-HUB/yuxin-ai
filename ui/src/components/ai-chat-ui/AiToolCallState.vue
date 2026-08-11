<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AiToolRow } from './types'

const props = withDefaults(
  defineProps<{
    kind?: 'web-search' | 'file-diff' | 'image-generation' | 'tool'
    title?: string
    status?: 'loading' | 'done' | 'error'
    latency?: number
    query?: string
    file?: string
    rows?: AiToolRow[]
    details?: string
  }>(),
  {
    kind: 'tool',
    title: '',
    status: 'loading',
    latency: 0,
    query: '',
    file: '',
    rows: () => [],
    details: '',
  },
)

const open = ref(true)

const isDone = computed(() => props.status === 'done')
const isError = computed(() => props.status === 'error')
const addedCount = computed(() => props.rows.filter((row) => row.type === 'add').length)
const removedCount = computed(() => props.rows.filter((row) => row.type === 'del').length)

const iconName = computed(() => {
  if (props.kind === 'web-search') return 'search'
  if (props.kind === 'file-diff') return 'diff'
  if (props.kind === 'image-generation') return 'image'
  return 'tool'
})

const resolvedTitle = computed(() => {
  if (props.title) return props.title
  const titles: Record<string, string> = {
    'web-search': 'Searching',
    'file-diff': 'File diff',
    'image-generation': 'Generating image',
    tool: 'Tool call',
  }
  return titles[props.kind]
})

</script>

<template>
  <div
    class="aicss-tool-call"
    :class="[
      `aicss-tool-call--${kind}`,
      `aicss-tool-call--${status}`,
      { 'aicss-tool-call--open': open },
    ]"
    data-test="ai-tool-call"
  >
    <div class="aicss-tool-call__header">
      <span class="aicss-tool-call__icon" aria-hidden="true">
        <svg
          v-if="iconName === 'search'"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
        </svg>
        <svg
          v-else-if="iconName === 'diff'"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M17.25 6.75 22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3-4.5 16.5" />
        </svg>
        <svg
          v-else-if="iconName === 'image'"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <rect x="3" y="3" width="18" height="18" rx="2.5" />
          <circle cx="8.5" cy="8.5" r="1.5" />
          <path d="m21 15-4.5-4.5L7 20" />
        </svg>
        <svg
          v-else
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M14.7 6.3a4.5 4.5 0 0 0 6 6L13 20H4v-9l7.7-7.7a4.5 4.5 0 0 0 3 3Z" />
          <path d="M19 5v6" />
        </svg>
      </span>

      <span class="aicss-tool-call__status-dot" aria-hidden="true" />
      <span
        class="aicss-tool-call__label"
        :class="{ 'aicss-shimmer': !isDone && !isError }"
      >
        {{ resolvedTitle }}
        <span v-if="kind === 'web-search' && query" class="aicss-tool-call__query">
          “{{ query }}”
        </span>
        <span v-else-if="kind === 'file-diff' && file" class="aicss-tool-call__query">
          {{ file }}
        </span>
      </span>

      <span
        v-if="kind === 'file-diff' && (addedCount > 0 || removedCount > 0)"
        class="aicss-tool-call__stat"
      >
        <span class="aicss-tool-call__add">+{{ addedCount }}</span>
        <span class="aicss-tool-call__del">-{{ removedCount }}</span>
      </span>

      <span v-if="latency > 0" class="aicss-tool-call__latency">{{ latency.toFixed(2) }}s</span>
      <button
        v-if="rows.length > 0 || details"
        type="button"
        class="aicss-tool-call__chevron"
        :aria-expanded="open"
        :aria-label="open ? 'Collapse details' : 'Expand details'"
        @click="open = !open"
      >
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="m4.5 15.75 7.5-7.5 7.5 7.5" />
        </svg>
      </button>
    </div>

    <div class="aicss-tool-call__collapsible" :class="{ 'aicss-tool-call__collapsible--closed': !open }">
      <div class="aicss-tool-call__inner">
        <div v-if="rows.length > 0 && kind === 'file-diff'" class="aicss-tool-call__diff">
          <div
            v-for="(row, index) in rows"
            :key="index"
            class="aicss-tool-call__diff-row"
            :class="`aicss-tool-call__diff-row--${row.type || 'ctx'}`"
          >
            <span class="aicss-tool-call__ln aicss-tool-call__ln--old">{{ row.old ?? '' }}</span>
            <span class="aicss-tool-call__ln aicss-tool-call__ln--new">{{ row.cur ?? '' }}</span>
            <span class="aicss-tool-call__sign">
              {{ row.type === 'add' ? '+' : row.type === 'del' ? '-' : '' }}
            </span>
            <code>{{ row.text }}</code>
          </div>
        </div>

        <ul v-else-if="rows.length > 0" class="aicss-tool-call__list">
          <li
            v-for="(row, index) in rows"
            :key="index"
            class="aicss-tool-call__site"
            :data-state="row.status || 'pending'"
          >
            <span class="aicss-tool-call__bullet">
              <svg class="aicss-tool-call__dots" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor">
                <circle cx="12" cy="12" r="9" stroke-width="1.8" stroke-dasharray="1.8 3.6" stroke-linecap="round" />
              </svg>
              <svg class="aicss-tool-call__check" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                <path d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
              </svg>
            </span>
            <span class="aicss-tool-call__site-title">{{ row.title }}</span>
            <span v-if="row.url" class="aicss-tool-call__site-url">{{ row.url }}</span>
          </li>
        </ul>

        <pre v-else-if="details" class="aicss-tool-call__details">{{ details }}</pre>
      </div>
    </div>
  </div>
</template>

<style scoped>
.aicss-tool-call {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  border-radius: 10px;
  border: 1px solid var(--aicss-border);
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
  font-family: var(--aicss-font);
  font-size: 13px;
  line-height: 1.45;
  color: var(--aicss-text);
  overflow: hidden;
  transition:
    border-color 0.18s var(--aicss-ease),
    box-shadow 0.18s var(--aicss-ease);
}

.aicss-tool-call--done {
  border-color: color-mix(in srgb, var(--aicss-success) 26%, var(--aicss-border));
}

.aicss-tool-call--error {
  border-color: color-mix(in srgb, var(--aicss-danger) 36%, var(--aicss-border));
}

.aicss-tool-call__header {
  display: flex;
  align-items: center;
  gap: 7px;
  min-height: 36px;
  padding: 8px 10px;
  min-width: 0;
}

.aicss-tool-call__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  flex: none;
  color: var(--aicss-muted);
}

.aicss-tool-call--done .aicss-tool-call__icon {
  color: var(--aicss-success);
}

.aicss-tool-call--error .aicss-tool-call__icon {
  color: var(--aicss-danger);
}

.aicss-tool-call__label {
  min-width: 0;
  font-weight: 550;
  color: var(--aicss-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.aicss-tool-call__status-dot {
  width: 7px;
  height: 7px;
  flex: none;
  border-radius: 50%;
  background: var(--aicss-subtle);
}

.aicss-tool-call--loading .aicss-tool-call__status-dot {
  background: var(--aicss-accent);
  animation: aicss-tool-state-pulse 1.2s var(--aicss-ease) infinite;
}

.aicss-tool-call--done .aicss-tool-call__status-dot {
  background: var(--aicss-success);
}

.aicss-tool-call--error .aicss-tool-call__status-dot {
  background: var(--aicss-danger);
}

.aicss-tool-call__query {
  color: var(--aicss-muted);
  font-weight: 450;
}

.aicss-tool-call__stat {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-left: auto;
  flex: none;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.aicss-tool-call__add {
  color: var(--aicss-success);
}

.aicss-tool-call__del {
  color: var(--aicss-danger);
}

.aicss-tool-call__latency {
  flex: none;
  margin-left: auto;
  font-size: 11px;
  color: var(--aicss-muted);
  font-variant-numeric: tabular-nums;
}

.aicss-tool-call__chevron {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex: none;
  border: 0;
  background: transparent;
  color: var(--aicss-subtle);
  border-radius: 5px;
  cursor: pointer;
  transition:
    color 0.16s var(--aicss-ease),
    transform 0.24s var(--aicss-ease),
    background-color 0.16s var(--aicss-ease);
}

.aicss-tool-call__chevron:hover {
  color: var(--aicss-text-2);
  background: var(--aicss-surface-2);
}

.aicss-tool-call__chevron[aria-expanded="false"] {
  transform: rotate(-90deg);
}

.aicss-tool-call__collapsible {
  display: grid;
  grid-template-rows: 1fr;
  opacity: 1;
  transition:
    grid-template-rows 0.28s var(--aicss-ease),
    opacity 0.2s var(--aicss-ease);
}

.aicss-tool-call__collapsible--closed {
  grid-template-rows: 0fr;
  opacity: 0;
  pointer-events: none;
}

.aicss-tool-call__inner {
  min-height: 0;
  overflow: hidden;
}

.aicss-tool-call__diff {
  border-top: 1px solid var(--aicss-border);
  font-family: var(--aicss-mono);
  font-size: 12px;
  line-height: 20px;
  overflow-x: auto;
  scrollbar-width: none;
}

.aicss-tool-call__diff::-webkit-scrollbar {
  display: none;
}

.aicss-tool-call__diff-row {
  display: grid;
  grid-template-columns: 32px 32px 18px minmax(max-content, 1fr);
  align-items: stretch;
}

.aicss-tool-call__ln {
  padding: 0 7px;
  text-align: right;
  color: var(--aicss-subtle);
  font-size: 11px;
  user-select: none;
}

.aicss-tool-call__sign {
  text-align: center;
  color: var(--aicss-subtle);
  font-size: 11px;
  user-select: none;
}

.aicss-tool-call__diff-row code {
  padding: 0 12px 0 8px;
  white-space: pre;
  color: var(--aicss-muted);
}

.aicss-tool-call__diff-row--add {
  background: var(--aicss-success-soft);
}

.aicss-tool-call__diff-row--add .aicss-tool-call__sign,
.aicss-tool-call__diff-row--add .aicss-tool-call__ln--new {
  color: var(--aicss-success);
}

.aicss-tool-call__diff-row--add code {
  color: var(--aicss-text);
}

.aicss-tool-call__diff-row--del {
  background: var(--aicss-danger-soft);
}

.aicss-tool-call__diff-row--del .aicss-tool-call__sign,
.aicss-tool-call__diff-row--del .aicss-tool-call__ln--old {
  color: var(--aicss-danger);
}

.aicss-tool-call__diff-row--del code {
  color: var(--aicss-text);
}

.aicss-tool-call__list {
  list-style: none;
  margin: 0;
  padding: 6px 10px 8px 18px;
  border-top: 1px solid var(--aicss-border);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.aicss-tool-call__site {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  font-size: 12px;
  color: var(--aicss-muted);
}

.aicss-tool-call__bullet {
  position: relative;
  width: 14px;
  height: 14px;
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.aicss-tool-call__dots,
.aicss-tool-call__check {
  position: absolute;
  inset: 0;
  transition: opacity 0.24s var(--aicss-ease), transform 0.24s var(--aicss-ease);
}

.aicss-tool-call__check {
  color: var(--aicss-success);
  opacity: 0;
  transform: scale(1.2);
}

.aicss-tool-call__site[data-state="done"] .aicss-tool-call__dots {
  opacity: 0;
}

.aicss-tool-call__site[data-state="done"] .aicss-tool-call__check {
  opacity: 1;
  transform: scale(1);
}

.aicss-tool-call__site-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--aicss-text-2);
  font-weight: 500;
}

.aicss-tool-call__site[data-state="pending"] .aicss-tool-call__site-title {
  color: var(--aicss-muted);
}

.aicss-tool-call__site-url {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--aicss-muted);
}

.aicss-tool-call__details {
  margin: 0;
  padding: 10px 12px;
  border-top: 1px solid var(--aicss-border);
  background: var(--aicss-bg-subtle);
  color: var(--aicss-text-2);
  font-family: var(--aicss-mono);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 220px;
  overflow-y: auto;
}

@keyframes aicss-tool-state-pulse {
  0%, 100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.55;
    transform: scale(0.78);
  }
}

@media (prefers-reduced-motion: reduce) {
  .aicss-tool-call--loading .aicss-tool-call__state::before {
    animation: none;
  }
}
</style>
