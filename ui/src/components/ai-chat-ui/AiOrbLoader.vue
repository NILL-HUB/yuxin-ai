<script setup lang="ts">
withDefaults(
  defineProps<{
    label?: string
    variant?: 'lattice' | 'ring' | 'morph' | 'pulse'
    size?: number
  }>(),
  {
    label: '',
    variant: 'lattice',
    size: 22,
  },
)

const LATTICE_CELLS = [
  [0, 0],
  [1, 0],
  [2, 0],
  [0, 1],
  [1, 1],
  [2, 1],
  [0, 2],
  [1, 2],
  [2, 2],
] as const
</script>

<template>
  <span class="aicss-orb" :class="`aicss-orb--${variant}`" :style="{ '--orb-size': `${size}px` }">
    <span class="aicss-orb__stage" aria-hidden="true">
      <template v-if="variant === 'lattice'">
        <span
          v-for="(cell, index) in LATTICE_CELLS"
          :key="index"
          class="aicss-orb__cell"
          :style="{ '--x': cell[0], '--y': cell[1], '--i': index }"
        />
      </template>
      <template v-else-if="variant === 'ring'">
        <span class="aicss-orb__ring" />
        <span class="aicss-orb__comet" />
      </template>
      <template v-else-if="variant === 'morph'">
        <span class="aicss-orb__morph" />
      </template>
      <template v-else>
        <span class="aicss-orb__pulse" />
      </template>
    </span>
    <span v-if="label" class="aicss-orb__label">{{ label }}</span>
  </span>
</template>

<style scoped>
.aicss-orb {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: var(--aicss-font);
  font-size: 12px;
  line-height: 18px;
  color: var(--aicss-muted);
  min-width: 0;
}

.aicss-orb__stage {
  position: relative;
  width: var(--orb-size);
  height: var(--orb-size);
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.aicss-orb__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.aicss-orb--lattice .aicss-orb__stage {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  grid-template-rows: repeat(3, 1fr);
  gap: 2px;
}

.aicss-orb__cell {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--aicss-accent);
  animation: aicss-orb-lattice 1.9s var(--aicss-ease) infinite;
  animation-delay: calc(var(--i) * -120ms);
}

@keyframes aicss-orb-lattice {
  0% {
    opacity: 0.2;
    transform: scale(0.7);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
  100% {
    opacity: 0.2;
    transform: scale(0.7);
  }
}

.aicss-orb__ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 1.5px solid transparent;
  border-top-color: var(--aicss-accent);
  animation: aicss-orb-spin 1.1s linear infinite;
}

.aicss-orb__comet {
  position: absolute;
  top: -1px;
  left: 50%;
  width: 5px;
  height: 5px;
  margin-left: -2.5px;
  border-radius: 50%;
  background: var(--aicss-accent);
  box-shadow: 0 0 6px color-mix(in srgb, var(--aicss-accent) 70%, transparent);
  animation: aicss-orb-spin 1.1s linear infinite;
}

@keyframes aicss-orb-spin {
  to {
    transform: rotate(360deg);
  }
}

.aicss-orb__morph {
  width: 62%;
  height: 62%;
  border-radius: 42% 58% 60% 40% / 48% 44% 56% 52%;
  background: color-mix(in srgb, var(--aicss-accent) 78%, transparent);
  animation: aicss-orb-morph 2.4s var(--aicss-ease) infinite;
}

@keyframes aicss-orb-morph {
  0%, 100% {
    border-radius: 42% 58% 60% 40% / 48% 44% 56% 52%;
    transform: rotate(0deg) scale(0.92);
  }
  50% {
    border-radius: 58% 42% 40% 60% / 56% 58% 42% 44%;
    transform: rotate(45deg) scale(1);
  }
}

.aicss-orb__pulse {
  width: 62%;
  height: 62%;
  border-radius: 50%;
  background: var(--aicss-accent);
  box-shadow: 0 0 0 0 color-mix(in srgb, var(--aicss-accent) 40%, transparent);
  animation: aicss-orb-pulse 1.6s var(--aicss-ease) infinite;
}

@keyframes aicss-orb-pulse {
  0% {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--aicss-accent) 40%, transparent);
    transform: scale(0.88);
  }
  60% {
    box-shadow: 0 0 0 9px transparent;
    transform: scale(1);
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
    transform: scale(0.88);
  }
}

@media (prefers-reduced-motion: reduce) {
  .aicss-orb__cell,
  .aicss-orb__ring,
  .aicss-orb__comet,
  .aicss-orb__morph,
  .aicss-orb__pulse {
    animation: none;
  }
}
</style>
