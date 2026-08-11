<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    lines?: string[]
    streaming?: boolean
    finished?: boolean
    latency?: number
    title?: string
    finishedTitle?: string
  }>(),
  {
    lines: () => [],
    streaming: false,
    finished: false,
    latency: 0,
    title: 'Thinking…',
    finishedTitle: '',
  },
)

const open = ref(true)
const viewportRef = ref<HTMLElement | null>(null)

const elapsedSeconds = computed(() => {
  if (props.latency > 0) return Math.max(1, Math.round(props.latency))
  return Math.max(1, props.lines.length)
})

const resolvedFinishedTitle = computed(() => {
  if (props.finishedTitle) return props.finishedTitle
  return `Thought for ${elapsedSeconds.value}s`
})

watch(
  () => props.finished,
  (finished) => {
    if (finished) open.value = false
  },
)

watch(
  () => props.streaming,
  (streaming) => {
    if (streaming) open.value = true
  },
)

watch(
  () => props.lines.length,
  async () => {
    if (!open.value || !viewportRef.value) return
    await nextTick()
    viewportRef.value.scrollTop = viewportRef.value.scrollHeight
  },
)
</script>

<template>
  <div class="aicss-thinking-reasoning" data-test="ai-thinking-reasoning">
    <button
      type="button"
      class="aicss-thinking-reasoning__header"
      :class="{ 'aicss-thinking-reasoning__header--clickable': finished }"
      :aria-expanded="finished ? open : true"
      aria-label="Toggle thought"
      @click="finished && (open = !open)"
    >
      <span v-if="finished" class="aicss-thinking-reasoning__label">
        <span class="aicss-thinking-reasoning__verb">Thought</span>
        <template v-if="resolvedFinishedTitle.startsWith('Thought')"> for {{ elapsedSeconds }}s</template>
        <template v-else>{{ resolvedFinishedTitle.replace(/^Thought\s*/, '') }}</template>
      </span>
      <span v-else class="aicss-thinking-reasoning__label aicss-shimmer">{{ title }}</span>
      <svg
        v-if="finished"
        class="aicss-thinking-reasoning__chevron"
        viewBox="0 0 24 24"
        width="12"
        height="12"
        aria-hidden="true"
      >
        <path d="m4.5 15.75 7.5-7.5 7.5 7.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>

    <div class="aicss-thinking-reasoning__collapsible" :class="{ 'aicss-thinking-reasoning__collapsible--closed': !open }">
      <div class="aicss-thinking-reasoning__inner">
        <div
          ref="viewportRef"
          class="aicss-thinking-reasoning__viewport"
          :class="{ 'aicss-thinking-reasoning__viewport--scroll': finished && open }"
        >
          <div class="aicss-thinking-reasoning__stream">
            <p
              v-for="(line, index) in lines"
              :key="`${index}-${line.slice(0, 24)}`"
              class="aicss-thinking-reasoning__sentence"
            >
              {{ line }}
            </p>
            <p
              v-if="streaming && lines.length === 0"
              class="aicss-thinking-reasoning__sentence aicss-thinking-reasoning__placeholder"
            >
              Working through the request…
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.aicss-thinking-reasoning {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  font-family: var(--aicss-font);
  animation: aicss-tr-in 320ms var(--aicss-ease) both;
}

@keyframes aicss-tr-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

.aicss-thinking-reasoning__header {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  align-self: flex-start;
  min-height: 20px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: default;
  max-width: 100%;
}

.aicss-thinking-reasoning__header--clickable {
  cursor: pointer;
}

.aicss-thinking-reasoning__label {
  font-size: 13px;
  line-height: 18px;
  font-weight: 500;
  color: var(--aicss-muted);
  letter-spacing: -0.005em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.aicss-thinking-reasoning__verb {
  color: var(--aicss-muted);
}

.aicss-thinking-reasoning__chevron {
  color: var(--aicss-muted);
  flex: none;
  transition: transform 280ms var(--aicss-ease);
  transform: rotate(180deg);
}

.aicss-thinking-reasoning__header[aria-expanded="true"] .aicss-thinking-reasoning__chevron {
  transform: rotate(0deg);
}

.aicss-thinking-reasoning__collapsible {
  display: grid;
  grid-template-rows: 1fr;
  opacity: 1;
  transition:
    grid-template-rows 320ms var(--aicss-ease),
    opacity 220ms ease;
}

.aicss-thinking-reasoning__collapsible--closed {
  grid-template-rows: 0fr;
  opacity: 0;
  pointer-events: none;
}

.aicss-thinking-reasoning__inner {
  min-height: 0;
  overflow: hidden;
}

.aicss-thinking-reasoning__viewport {
  margin-top: 6px;
  max-height: 196px;
  overflow: hidden;
  transition: max-height 360ms var(--aicss-ease);
  scrollbar-width: none;
}

.aicss-thinking-reasoning__viewport::-webkit-scrollbar {
  display: none;
}

.aicss-thinking-reasoning__viewport--scroll {
  overflow-y: auto;
}

.aicss-thinking-reasoning__stream {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.aicss-thinking-reasoning__sentence {
  margin: 0;
  line-height: 20px;
  font-size: 13px;
  font-weight: 425;
  color: var(--aicss-muted);
  letter-spacing: -0.005em;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  animation: aicss-tr-sentence-in 360ms var(--aicss-ease) both;
  white-space: pre-wrap;
  word-break: break-word;
}

.aicss-thinking-reasoning__placeholder {
  color: var(--aicss-subtle);
}

@keyframes aicss-tr-sentence-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .aicss-thinking-reasoning__sentence {
    animation: none;
  }
}
</style>
