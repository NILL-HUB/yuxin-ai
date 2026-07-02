<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { adminLogin } from '@/services/admin-auth'
import { getErrorMessage } from '@/utils/error'
import AdminLoginBackground from '@/components/admin/AdminLoginBackground.vue'
import IconOpenAgent from '@/components/icons/IconOpenAgent.vue'

defineOptions({ name: 'AdminLoginView' })

const router = useRouter()
const identifier = ref('')
const password = ref('')
const showPassword = ref(false)
const remember = ref(false)
const loading = ref(false)
const errorMessage = ref('')

const canSubmit = computed(
  () => identifier.value.trim().length > 0 && password.value.length > 0 && !loading.value,
)

/**
 * 恢复上一次记住的管理员账号，避免改变现有登录习惯。
 */
function restoreRememberedIdentifier() {
  const saved = localStorage.getItem('admin_remember_identifier')
  if (!saved) return

  identifier.value = saved
  remember.value = true
}

/**
 * 提交管理员登录请求，并保持既有的错误提示与记住账号行为。
 */
async function handleLogin() {
  errorMessage.value = ''

  if (!identifier.value.trim() || !password.value) {
    errorMessage.value = '请输入管理员账号或邮箱和密码'
    return
  }

  try {
    loading.value = true
    await adminLogin(identifier.value.trim(), password.value)

    if (remember.value) {
      localStorage.setItem('admin_remember_identifier', identifier.value.trim())
    } else {
      localStorage.removeItem('admin_remember_identifier')
    }

    await router.replace('/admin')
  } catch (error) {
    errorMessage.value = getErrorMessage(error, '登录失败，请检查账号或邮箱和密码')
    Message.error(errorMessage.value)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  restoreRememberedIdentifier()
})
</script>

<template>
  <main class="admin-shell">
    <section class="admin-stage">
      <AdminLoginBackground />

      <div class="stage-grid">
        <section class="brand-panel">
          <div class="brand-mark">
            <IconOpenAgent class="hero-logo" />
            <span class="brand-name">OpenAgent</span>
          </div>

          <p class="hero-eyebrow">Admin Console</p>
          <h1 class="hero-title">管理控制台</h1>
          <p class="hero-desc">
            独立的管理员入口，聚焦权限控制、操作审计与系统级配置。<br />
            保持更稳的后台气质，也让登录页更有品牌识别度。
          </p>

          <div class="hero-tags">
            <span class="hero-tag">独立凭证</span>
            <span class="hero-tag">权限审计</span>
            <span class="hero-tag">系统入口</span>
          </div>

          <div class="hero-panel">
            <div class="hero-panel-label">Secure Access</div>
            <div class="hero-panel-title">后台能力与用户侧登录完全隔离</div>
            <p class="hero-panel-text">
              使用管理员身份完成登录后，可进入配置、审计、角色与系统级管理操作。
            </p>
          </div>
        </section>

        <section class="login-panel">
          <div class="login-panel-overlay"></div>

          <div class="form-card">
            <header class="form-header">
              <div class="header-badge">SECURE</div>
              <h2 class="form-title">管理员登录</h2>
              <p class="form-subtitle">仅限系统管理员访问，请使用管理员凭证</p>
            </header>

            <form class="form-body" @submit.prevent="handleLogin">
              <label class="field">
                <span class="field-label">管理员账号或邮箱</span>
                <div class="field-control">
                  <icon-user class="field-icon" />
                  <input
                    v-model="identifier"
                    type="text"
                    autocomplete="username"
                    placeholder="输入管理员账号或邮箱"
                    @keyup.enter="handleLogin"
                  />
                </div>
              </label>

              <label class="field">
                <span class="field-label">管理员密码</span>
                <div class="field-control">
                  <icon-lock class="field-icon" />
                  <input
                    v-model="password"
                    :type="showPassword ? 'text' : 'password'"
                    autocomplete="current-password"
                    placeholder="输入管理员密码"
                    @keyup.enter="handleLogin"
                  />
                  <button
                    type="button"
                    class="field-toggle"
                    :title="showPassword ? '隐藏密码' : '显示密码'"
                    @click="showPassword = !showPassword"
                  >
                    <icon-eye v-if="showPassword" />
                    <icon-eye-invisible v-else />
                  </button>
                </div>
              </label>

              <div class="form-options">
                <label class="remember">
                  <input v-model="remember" type="checkbox" />
                  <span>记住账号</span>
                </label>
              </div>

              <transition name="fade">
                <div v-if="errorMessage" class="form-error">
                  <icon-close-circle-fill />
                  <span>{{ errorMessage }}</span>
                </div>
              </transition>

              <button type="submit" class="submit-btn" :disabled="!canSubmit">
                <span v-if="!loading">进入管理后台</span>
                <span v-else class="loading-text">
                  <span class="spinner"></span>
                  正在验证...
                </span>
              </button>
            </form>

            <footer class="form-footer">
              <span class="footer-hint">本入口与用户端登录完全隔离</span>
            </footer>
          </div>
        </section>
      </div>
    </section>
  </main>
</template>

<style scoped>
.admin-shell {
  min-height: 100vh;
  background: #050814;
  color: #eaf1ff;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.admin-stage {
  position: relative;
  min-height: 100vh;
  overflow: hidden;
}

.stage-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 0.92fr) minmax(620px, 760px);
  min-height: 100vh;
  gap: 0;
}

.brand-panel,
.login-panel {
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.brand-panel {
  padding: 88px 24px 88px 72px;
}

.login-panel {
  position: relative;
  padding: 42px 64px 42px 0;
}

.login-panel-overlay {
  position: absolute;
  inset: 0 0 0 -160px;
  background:
    linear-gradient(
      90deg,
      rgba(255, 255, 255, 0) 0%,
      rgba(20, 28, 48, 0.14) 14%,
      rgba(12, 18, 34, 0.34) 28%,
      rgba(10, 16, 30, 0.6) 46%,
      rgba(8, 13, 24, 0.78) 66%,
      rgba(7, 11, 20, 0.94) 100%
    );
  backdrop-filter: blur(20px) saturate(124%);
  border-left: 1px solid rgba(159, 185, 255, 0.14);
  mask-image: linear-gradient(90deg, transparent 0%, rgba(0, 0, 0, 0.96) 12%);
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 34px;
}

.hero-logo {
  width: 36px;
  height: 36px;
}

.brand-name {
  font-size: 20px;
  font-weight: 700;
  color: #ffffff;
}

.hero-eyebrow {
  margin: 0 0 18px;
  font-size: 12px;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  color: #95abff;
}

.hero-title {
  margin: 0;
  font-size: clamp(48px, 6vw, 84px);
  line-height: 0.96;
  letter-spacing: -0.06em;
  font-weight: 800;
  background: linear-gradient(135deg, #ffffff 18%, #bfd3ff 48%, #8edcff 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero-desc {
  max-width: 580px;
  margin: 26px 0 0;
  font-size: 16px;
  line-height: 1.9;
  color: #a8b6d5;
}

.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 30px;
}

.hero-tag {
  display: inline-flex;
  align-items: center;
  padding: 9px 14px;
  border-radius: 999px;
  border: 1px solid rgba(146, 171, 255, 0.24);
  background: rgba(86, 114, 214, 0.08);
  color: #d7e1ff;
  font-size: 13px;
}

.hero-panel {
  width: min(100%, 520px);
  margin-top: 38px;
  padding: 22px 24px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 22px;
  background: rgba(9, 14, 26, 0.46);
  backdrop-filter: blur(12px);
  box-shadow: 0 24px 56px rgba(0, 0, 0, 0.22);
}

.hero-panel-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #91a8ff;
}

.hero-panel-title {
  margin-top: 12px;
  font-size: 24px;
  font-weight: 700;
  line-height: 1.3;
  color: #f7f9ff;
}

.hero-panel-text {
  margin: 10px 0 0;
  font-size: 14px;
  line-height: 1.8;
  color: #a6b2cb;
}

.form-card {
  position: relative;
  z-index: 1;
  width: min(100%, 580px);
  margin-left: auto;
  padding: 42px 42px 36px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 28px;
  background:
    linear-gradient(180deg, rgba(18, 26, 45, 0.84) 0%, rgba(10, 16, 30, 0.74) 100%);
  backdrop-filter: blur(22px);
  box-shadow:
    0 32px 80px rgba(0, 0, 0, 0.36),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.form-header {
  margin-bottom: 28px;
}

.header-badge {
  display: inline-block;
  padding: 5px 10px;
  margin-bottom: 16px;
  border: 1px solid rgba(136, 167, 255, 0.24);
  border-radius: 999px;
  background: rgba(136, 167, 255, 0.08);
  color: #95abff;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.18em;
}

.form-title {
  margin: 0;
  font-size: 30px;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: #ffffff;
}

.form-subtitle {
  margin: 8px 0 0;
  font-size: 14px;
  line-height: 1.7;
  color: #8c9bb8;
}

.form-body {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-label {
  font-size: 13px;
  font-weight: 600;
  color: #c8d3ea;
}

.field-control {
  position: relative;
  display: flex;
  align-items: center;
  height: 50px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.04);
  transition:
    border-color 0.2s ease,
    background 0.2s ease,
    box-shadow 0.2s ease;
}

.field-control:focus-within {
  border-color: rgba(144, 174, 255, 0.48);
  background: rgba(92, 124, 220, 0.1);
  box-shadow: 0 0 0 4px rgba(92, 124, 220, 0.12);
}

.field-icon {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  margin-left: 14px;
  color: #7184a8;
}

.field-control input {
  flex: 1;
  height: 100%;
  padding: 0 14px;
  border: 0;
  background: transparent;
  color: #eef3ff;
  font-size: 15px;
  outline: none;
}

.field-control input::placeholder {
  color: #627392;
}

.field-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 100%;
  border: 0;
  background: transparent;
  color: #7184a8;
  cursor: pointer;
  transition: color 0.2s ease;
}

.field-toggle:hover {
  color: #b6cbff;
}

.form-options {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.remember {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #93a0ba;
  font-size: 13px;
  cursor: pointer;
  user-select: none;
}

.remember input {
  width: 16px;
  height: 16px;
  accent-color: #6c90ff;
}

.form-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border: 1px solid rgba(255, 112, 112, 0.22);
  border-radius: 12px;
  background: rgba(255, 92, 92, 0.08);
  color: #ffb0b0;
  font-size: 13px;
}

.submit-btn {
  height: 52px;
  margin-top: 4px;
  border: 0;
  border-radius: 16px;
  background: linear-gradient(135deg, #6785ff 0%, #54cbff 100%);
  color: #ffffff;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.02em;
  cursor: pointer;
  transition:
    transform 0.16s ease,
    box-shadow 0.2s ease,
    opacity 0.2s ease;
}

.submit-btn:not(:disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 20px 38px rgba(92, 131, 255, 0.34);
}

.submit-btn:disabled {
  opacity: 0.54;
  cursor: not-allowed;
}

.loading-text {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.28);
  border-top-color: #ffffff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

.form-footer {
  margin-top: 24px;
  text-align: center;
}

.footer-hint {
  color: #6e7f9f;
  font-size: 12px;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1080px) {
  .stage-grid {
    grid-template-columns: minmax(0, 0.95fr) minmax(540px, 620px);
  }

  .brand-panel {
    padding-left: 48px;
  }

  .login-panel {
    padding-right: 32px;
  }

  .login-panel-overlay {
    left: -110px;
  }
}

@media (max-width: 900px) {
  .stage-grid {
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .brand-panel {
    padding: 48px 24px 8px;
  }

  .login-panel {
    padding: 0 24px 32px;
  }

  .login-panel-overlay {
    inset: 0;
    background:
      linear-gradient(
        180deg,
        rgba(12, 18, 34, 0.18) 0%,
        rgba(9, 13, 25, 0.52) 32%,
        rgba(7, 11, 20, 0.88) 100%
      );
    border-left: 0;
    border-top: 1px solid rgba(159, 185, 255, 0.14);
    mask-image: linear-gradient(180deg, transparent 0%, rgba(0, 0, 0, 0.96) 16%);
  }

  .hero-title {
    font-size: clamp(38px, 11vw, 64px);
  }

  .hero-panel {
    margin-top: 28px;
  }

  .form-card {
    width: 100%;
    margin-left: 0;
  }
}
</style>
