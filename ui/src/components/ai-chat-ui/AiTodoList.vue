<script setup lang="ts">
import { computed, ref } from 'vue'

export type AiTodoItem = {
  title?: string
  content?: string
  status?: string
  [key: string]: unknown
}

const props = withDefaults(
  defineProps<{
    items?: AiTodoItem[]
    title?: string
    loading?: boolean
  }>(),
  {
    items: () => [],
    title: 'To-dos',
    loading: false,
  },
)

const collapsed = ref(false)

const normalizeStatus = (status: unknown) => {
  const normalized = String(status ?? '')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_')
  if (['completed', 'complete', 'done', 'success', 'succeeded', 'finished'].includes(normalized)) {
    return 'done'
  }
  if (['error', 'failed', 'fail', 'failure'].includes(normalized)) return 'error'
  if (['in_progress', 'progress', 'running', 'working', 'doing', 'start'].includes(normalized)) {
    return 'active'
  }
  return 'pending'
}

const normalizedItems = computed(() =>
  props.items.map((item) => {
    const content = String(
      item.content ?? item.text ?? item.description ?? item.title ?? item.name ?? '',
    ).trim()
    return {
      label: String(item.title ?? content).trim() || content,
      status: normalizeStatus(item.status),
      raw: item,
    }
  }),
)

const doneCount = computed(() => normalizedItems.value.filter((item) => item.status === 'done').length)
const totalCount = computed(() => normalizedItems.value.length)
const running = computed(() => props.loading || normalizedItems.value.some((item) => item.status === 'active'))
const allDone = computed(() => totalCount.value > 0 && doneCount.value === totalCount.value)
const progressPercent = computed(() =>
  totalCount.value === 0 ? 0 : Math.round((doneCount.value / totalCount.value) * 100),
)
</script>

<template>
  <div class="aicss-todo" data-test="ai-todo-list">
    <button
      type="button"
      class="aicss-todo__header"
      :aria-expanded="!collapsed"
      aria-label="Toggle to-dos"
      @click="collapsed = !collapsed"
    >
      <span class="aicss-todo__header-icon" aria-hidden="true">
        <svg
          v-if="allDone"
          class="aicss-todo__check"
          viewBox="0 0 24 24"
          width="16"
          height="16"
          fill="currentColor"
        >
          <path
            fill-rule="evenodd"
            clip-rule="evenodd"
            d="M2.25 12c0-5.385 4.365-9.75 9.75-9.75s9.75 4.365 9.75 9.75-4.365 9.75-9.75 9.75S2.25 17.385 2.25 12Zm13.36-1.814a.75.75 0 1 0-1.22-.872l-3.236 4.53L9.53 12.22a.75.75 0 0 0-1.06 1.06l2.25 2.25a.75.75 0 0 0 1.14-.094l3.75-5.25Z"
          />
        </svg>
        <svg
          v-else
          class="aicss-todo__list-icon"
          viewBox="0 0 24 24"
          width="16"
          height="16"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0ZM3.75 12h.007v.008H3.75V12Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm-.375 5.25h.007v.008H3.75v-.008Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z" />
        </svg>
        <svg class="aicss-todo__chevron" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="m19.5 8.25-7.5 7.5-7.5-7.5" />
        </svg>
      </span>
      <span class="aicss-todo__title">{{ title }}</span>
      <span class="aicss-todo__count">
        <span v-if="running && !allDone" class="aicss-todo__running">
          {{ progressPercent }}%
        </span>
        <span v-else>{{ doneCount }}/{{ totalCount }}</span>
      </span>
    </button>

    <div class="aicss-todo__collapsible" :class="{ 'aicss-todo__collapsible--closed': collapsed }">
      <div class="aicss-todo__inner">
        <ul class="aicss-todo__list">
          <li
            v-for="(item, index) in normalizedItems"
            :key="`${index}-${item.label}`"
            class="aicss-todo__item"
            :class="`aicss-todo__item--${item.status}`"
            :style="{ '--i': index }"
          >
            <span class="aicss-todo__icon-wrap" aria-hidden="true">
              <svg
                class="aicss-todo__icon"
                :class="{ 'aicss-todo__icon--on': item.status === 'pending' }"
                viewBox="0 0 24 24"
                width="16"
                height="16"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
              >
                <circle cx="12" cy="12" r="9" stroke-dasharray="1.8 3.6" />
              </svg>
              <svg
                class="aicss-todo__icon aicss-todo__icon--strong"
                :class="{ 'aicss-todo__icon--on': item.status === 'active' }"
                viewBox="0 0 24 24"
                width="16"
                height="16"
                fill="none"
                stroke="currentColor"
                stroke-width="1.6"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="m12.75 15 3-3m0 0-3-3m3 3h-7.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
              </svg>
              <svg
                class="aicss-todo__icon"
                :class="{ 'aicss-todo__icon--on': item.status === 'done' }"
                viewBox="0 0 24 24"
                width="16"
                height="16"
                fill="none"
                stroke="currentColor"
                stroke-width="1.6"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
              </svg>
              <svg
                v-if="item.status === 'error'"
                class="aicss-todo__icon aicss-todo__icon--on aicss-todo__icon--error"
                viewBox="0 0 24 24"
                width="16"
                height="16"
                fill="none"
                stroke="currentColor"
                stroke-width="1.6"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M12 8v4m0 4h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
              </svg>
            </span>
            <span class="aicss-todo__label">{{ item.label }}</span>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<style scoped>
.aicss-todo {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  padding: 6px 12px 12px;
  border-radius: 8px;
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
  color: var(--aicss-text);
  font-family: var(--aicss-font);
  font-size: 13px;
}

.aicss-todo__header {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 8px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  color: var(--aicss-text);
  font-size: 13px;
  min-height: 22px;
}

.aicss-todo__header-icon {
  position: relative;
  width: 16px;
  height: 16px;
  flex: none;
  color: var(--aicss-muted);
}

.aicss-todo__list-icon,
.aicss-todo__chevron,
.aicss-todo__check {
  position: absolute;
  inset: 0;
  margin: auto;
  transition: opacity 140ms ease, transform 220ms ease;
}

.aicss-todo__list-icon,
.aicss-todo__chevron {
  width: 13px;
  height: 13px;
}

.aicss-todo__check {
  width: 16px;
  height: 16px;
  color: var(--aicss-success);
}

.aicss-todo__chevron {
  opacity: 0;
}

.aicss-todo__header[aria-expanded="false"] .aicss-todo__chevron {
  transform: rotate(-90deg);
}

.aicss-todo__header:hover .aicss-todo__list-icon,
.aicss-todo__header:hover .aicss-todo__check {
  opacity: 0;
}

.aicss-todo__header:hover .aicss-todo__chevron {
  opacity: 1;
}

.aicss-todo__title {
  font-weight: 500;
}

.aicss-todo__count {
  margin-left: auto;
  color: var(--aicss-muted);
  font-variant-numeric: tabular-nums;
  font-size: 12px;
}

.aicss-todo__running {
  color: var(--aicss-accent);
}

.aicss-todo__collapsible {
  display: grid;
  grid-template-rows: 1fr;
  opacity: 1;
  transition:
    grid-template-rows 280ms ease,
    opacity 200ms ease;
}

.aicss-todo__collapsible--closed {
  grid-template-rows: 0fr;
  opacity: 0;
  pointer-events: none;
}

.aicss-todo__inner {
  min-height: 0;
  overflow: hidden;
}

.aicss-todo__list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 10px 0 0;
}

.aicss-todo__item {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  line-height: 18px;
  color: var(--aicss-muted);
  animation: aicss-todo-item-in 360ms ease backwards;
  animation-delay: calc(var(--i, 0) * 45ms);
}

@keyframes aicss-todo-item-in {
  from {
    opacity: 0;
    transform: translateY(-6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.aicss-todo__icon-wrap {
  position: relative;
  width: 16px;
  height: 16px;
  flex: none;
  margin-top: 1px;
}

.aicss-todo__icon {
  position: absolute;
  inset: 0;
  width: 16px;
  height: 16px;
  color: var(--aicss-muted);
  opacity: 0;
  transition: opacity 320ms ease;
}

.aicss-todo__icon--on {
  opacity: 1;
}

.aicss-todo__icon--strong {
  color: var(--aicss-accent);
}

.aicss-todo__icon--error {
  color: var(--aicss-danger);
}

.aicss-todo__label {
  min-width: 0;
  font-weight: 400;
  color: var(--aicss-muted);
  transition: color 320ms ease;
  overflow-wrap: anywhere;
}

.aicss-todo__item--active .aicss-todo__label {
  color: var(--aicss-text);
}

.aicss-todo__item--done .aicss-todo__label {
  color: var(--aicss-muted);
  text-decoration: line-through;
}

.aicss-todo__item--error .aicss-todo__label {
  color: var(--aicss-danger);
}

@media (prefers-reduced-motion: reduce) {
  .aicss-todo__item {
    animation: none;
  }
}
</style>
