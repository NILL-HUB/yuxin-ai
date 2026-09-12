<script setup lang="ts">
import LoginBanner from './components/LoginBanner.vue'
import LoginForm from './components/LoginForm.vue'
</script>

<template>
  <!-- 页面容器（标题栏毛玻璃悬浮其上，视觉保持全屏沉浸） -->
  <div class="login-page">
    <!-- 全屏粒子动画背景层 -->
    <login-banner />
    <!-- 居中登录表单 -->
    <div class="login-panel">
      <login-form />
    </div>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  overflow: hidden;
  color: var(--aicss-text);
  background:
    radial-gradient(
      1100px 700px at 88% 12%,
      var(--aicss-accent-soft) 0%,
      transparent 60%
    ),
    radial-gradient(
      980px 680px at 10% 88%,
      var(--aicss-violet-soft) 0%,
      transparent 62%
    ),
    linear-gradient(
      145deg,
      var(--aicss-bg) 0%,
      var(--aicss-surface-3) 52%,
      var(--aicss-bg-subtle) 100%
    );
}

.login-panel {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
}

@media (max-width: 768px) {
  .login-page {
    overflow-y: auto;
  }

  .login-panel {
    padding: 24px 16px;
  }
}
</style>
