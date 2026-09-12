<script setup lang="ts">
import InteractiveParticleCanvas from '@/components/InteractiveParticleCanvas.vue'
</script>

<template>
  <!-- 全屏粒子动画背景层（交互动效保持原样） -->
  <div class="login-banner">
    <interactive-particle-canvas class="absolute inset-0 w-full h-full z-0" />
  </div>
</template>

<style scoped>
.login-banner {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
  pointer-events: none;
}
</style>
