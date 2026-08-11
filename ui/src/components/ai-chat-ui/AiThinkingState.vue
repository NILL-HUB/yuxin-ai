<script setup lang="ts">
withDefaults(
  defineProps<{
    label?: string
    compact?: boolean
  }>(),
  {
    label: 'Thinking',
    compact: false,
  },
)
</script>

<template>
  <span
    class="aicss-thinking-state"
    :class="{ 'aicss-thinking-state--compact': compact }"
    data-test="ai-thinking-state"
  >
    <span class="aicss-thinking-state__dot" aria-hidden="true" />
    <span class="aicss-thinking-state__label aicss-shimmer">{{ label }}</span>
  </span>
</template>

<style scoped>
.aicss-thinking-state {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 20px;
  color: var(--aicss-muted);
  font-family: var(--aicss-font);
  font-size: 13px;
  line-height: 18px;
  font-weight: 500;
}

.aicss-thinking-state--compact {
  font-size: 12px;
  gap: 6px;
}

.aicss-thinking-state__dot {
  position: relative;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--aicss-accent);
  box-shadow: 0 0 0 0 color-mix(in srgb, var(--aicss-accent) 42%, transparent);
  animation: aicss-thinking-pulse 1.5s var(--aicss-ease) infinite;
  flex: none;
}

.aicss-thinking-state__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@keyframes aicss-thinking-pulse {
  0% {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--aicss-accent) 42%, transparent);
    transform: scale(0.92);
  }
  55% {
    box-shadow: 0 0 0 7px transparent;
    transform: scale(1);
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
    transform: scale(0.92);
  }
}

@media (prefers-reduced-motion: reduce) {
  .aicss-thinking-state__dot {
    animation: none;
  }
}
</style>
