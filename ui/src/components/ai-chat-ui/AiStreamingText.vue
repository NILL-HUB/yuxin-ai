<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    text: string
    streaming?: boolean
    streamStep?: number
  }>(),
  {
    text: '',
    streaming: false,
    streamStep: 2,
  },
)

const isStillStreaming = computed(() => props.streaming && Boolean(props.text))
</script>

<template>
  <span class="aicss-streaming-text" data-test="ai-streaming-text">
    <slot :text="text">{{ text }}</slot>
    <span
      v-if="isStillStreaming || streaming"
      class="aicss-streaming-text__caret"
      :class="{ 'aicss-streaming-text__caret--steady': isStillStreaming }"
      aria-hidden="true"
    />
  </span>
</template>

<style scoped>
.aicss-streaming-text {
  position: relative;
  display: inline;
  font-family: var(--aicss-font);
  color: var(--aicss-text);
}

.aicss-streaming-text__caret {
  display: inline-block;
  width: 7px;
  height: 1.02em;
  margin-left: 2px;
  background: var(--aicss-accent);
  vertical-align: text-bottom;
  animation: aicss-caret-blink 1s step-end infinite;
}

.aicss-streaming-text__caret--steady {
  animation: none;
}

@keyframes aicss-caret-blink {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .aicss-streaming-text__caret {
    animation: none;
  }
}
</style>
