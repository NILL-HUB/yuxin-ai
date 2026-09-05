<script setup lang="ts">
import InteractiveParticleCanvas from '@/components/InteractiveParticleCanvas.vue'
</script>

<template>
  <div class="login-banner relative overflow-hidden bg-surface text-white flex items-center justify-center">
    <!-- 交互粒子背景 -->
    <interactive-particle-canvas class="absolute inset-0 w-full h-full z-0" />

    <!-- 内容 -->
    <div class="relative z-10 text-center px-10">
      <h1 class="text-4xl font-extrabold tracking-wider animate-glow">
        AI Agent 应用开发平台
      </h1>
      <p class="mt-4 text-lg font-extrabold animate-glow leading-relaxed ">
        用AI Agent驱动自动化革命
      </p>
    </div>
  </div>
</template>

<style scoped>
@keyframes glow {
  0%, 100% {
    text-shadow: 0 0 10px var(--aicss-accent), 0 0 20px var(--aicss-violet), 0 0 30px var(--aicss-violet);
  }
  50% {
    text-shadow: 0 0 20px var(--aicss-violet), 0 0 30px var(--aicss-accent), 0 0 50px var(--aicss-accent-text);
  }
}

@keyframes fade-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.animate-glow {
  animation: glow 3s infinite ease-in-out;
}
.animate-fade-in {
  animation: fade-in 1.5s ease-out;
}
.login-banner {
  width: min(700px, 46vw);
  height: 100%;
}

@media (max-width: 768px) {
  .login-banner {
    width: 100%;
    height: 180px;
  }

  .login-banner h1 {
    font-size: 24px;
  }

  .login-banner p {
    font-size: 15px;
  }
}
</style>
