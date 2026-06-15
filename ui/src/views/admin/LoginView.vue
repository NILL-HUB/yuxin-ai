<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { adminLogin } from '@/services/admin-auth'
import { getErrorMessage } from '@/utils/error'

const router = useRouter()
const form = ref({ identifier: '', password: '' })
const loading = ref(false)
const errorMessage = ref('')

const handleLogin = async () => {
  errorMessage.value = ''
  if (!form.value.identifier.trim() || !form.value.password) {
    errorMessage.value = '请输入管理员账号或邮箱和密码'
    return
  }
  try {
    loading.value = true
    await adminLogin(form.value.identifier.trim(), form.value.password)
    await router.replace('/admin')
  } catch (error) {
    errorMessage.value = getErrorMessage(error, '登录失败，请检查账号或邮箱和密码')
    Message.error(errorMessage.value)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="admin-login-shell">
    <section class="admin-login-hero">
      <div class="hero-orbit hero-orbit-one"></div>
      <div class="hero-orbit hero-orbit-two"></div>
      <div class="hero-content">
        <p class="eyebrow">OpenAgent Admin</p>
        <h1>管理控制台</h1>
        <p class="hero-copy">独立管理员身份、角色权限和后台审计入口。客户账号凭证不会在这里生效。</p>
      </div>
    </section>
    <section class="admin-login-panel">
      <div class="panel-card">
        <div>
          <p class="panel-kicker">Secure entrance</p>
          <h2>管理员登录</h2>
        </div>
        <div class="form-stack">
          <a-input v-model="form.identifier" placeholder="管理员账号或邮箱" size="large">
            <template #prefix><icon-user /></template>
          </a-input>
          <a-input-password v-model="form.password" placeholder="管理员密码" size="large" @keyup.enter="handleLogin">
            <template #prefix><icon-lock /></template>
          </a-input-password>
          <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>
          <a-button type="primary" size="large" long :loading="loading" @click="handleLogin">进入管理后台</a-button>
        </div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.admin-login-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(420px, 0.95fr);
  background: #070b13;
  color: #eef4ff;
}

.admin-login-hero {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: flex-end;
  padding: 72px;
  background:
    radial-gradient(circle at 25% 25%, rgba(70, 132, 255, 0.36), transparent 32%),
    linear-gradient(135deg, #08111f 0%, #0b1426 45%, #172033 100%);
}

.hero-orbit {
  position: absolute;
  border: 1px solid rgba(132, 171, 255, 0.22);
  border-radius: 999px;
  transform: rotate(-18deg);
}

.hero-orbit-one {
  width: 620px;
  height: 220px;
  right: -140px;
  top: 120px;
}

.hero-orbit-two {
  width: 460px;
  height: 160px;
  right: 80px;
  top: 210px;
}

.hero-content {
  position: relative;
  max-width: 640px;
}

.eyebrow,
.panel-kicker {
  margin: 0 0 14px;
  color: #91b4ff;
  font-size: 12px;
  letter-spacing: 0.22em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: clamp(48px, 7vw, 96px);
  line-height: 0.94;
  letter-spacing: -0.08em;
}

.hero-copy {
  max-width: 520px;
  margin: 28px 0 0;
  color: #b9c7dd;
  font-size: 17px;
  line-height: 1.8;
}

.admin-login-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.035), rgba(255, 255, 255, 0.015));
}

.panel-card {
  width: min(100%, 440px);
  padding: 42px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 28px;
  background: rgba(15, 23, 42, 0.76);
  box-shadow: 0 30px 100px rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(18px);
}

h2 {
  margin: 0 0 32px;
  font-size: 32px;
  letter-spacing: -0.04em;
}

.form-stack {
  display: grid;
  gap: 18px;
}

.error-message {
  margin: -4px 0 0;
  color: #ff9c9c;
  font-size: 13px;
}

:deep(.arco-input-wrapper),
:deep(.arco-input-password) {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.12);
  color: #eef4ff;
}

:deep(.arco-input),
:deep(.arco-input::placeholder) {
  color: #c9d4e8;
}

:deep(.arco-btn-primary) {
  height: 48px;
  border: 0;
  background: linear-gradient(135deg, #5f8cff, #8f6dff);
  font-weight: 700;
}

@media (max-width: 900px) {
  .admin-login-shell {
    grid-template-columns: 1fr;
  }

  .admin-login-hero {
    min-height: 360px;
    padding: 40px;
  }

  .admin-login-panel {
    padding: 28px;
  }
}
</style>
