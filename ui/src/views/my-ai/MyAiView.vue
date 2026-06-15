<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { type MyApp } from '@/models/app-assignment'
import { listMyApps } from '@/services/my-apps'
import { getErrorMessage } from '@/utils/error'

const router = useRouter()
const loading = ref(false)
const apps = ref<MyApp[]>([])

const loadApps = async () => {
  loading.value = true
  try {
    const result = await listMyApps()
    apps.value = result.list
  } catch (error) {
    Message.error(getErrorMessage(error, '加载我的 AI 功能失败'))
  } finally {
    loading.value = false
  }
}

const openApp = (app: MyApp) => {
  router.push(`/my-ai/${app.id}`)
}

onMounted(loadApps)
</script>

<template>
  <section class="my-ai-page" :aria-busy="loading">
    <header class="hero-card">
      <p class="kicker">Assigned AI</p>
      <h2>我的 AI 功能</h2>
      <p>这里展示管理员分配给你的 AI 应用，使用时按你的算力值账户扣减。</p>
    </header>

    <section class="app-grid">
      <article v-for="app in apps" :key="app.id" class="app-card">
        <div class="app-icon">{{ app.icon || '🤖' }}</div>
        <div>
          <h3>{{ app.name }}</h3>
          <p>{{ app.description || '管理员分配的 AI 功能' }}</p>
        </div>
        <a-button type="primary" @click="openApp(app)">开始使用</a-button>
      </article>
    </section>

    <section v-if="!loading && apps.length === 0" class="empty-panel">
      <h3>暂无已分配 AI 功能</h3>
      <p>请联系管理员为你分配可用的 AI 应用。</p>
    </section>
  </section>
</template>

<style scoped>
.my-ai-page {
  min-height: 100vh;
  display: grid;
  gap: 20px;
  align-content: start;
  padding: 32px;
  background: #f4f7fb;
}

.hero-card,
.app-card,
.empty-panel {
  padding: 24px;
  border-radius: 22px;
  background: #fff;
  box-shadow: 0 14px 40px rgba(15, 23, 42, 0.06);
}

.hero-card {
  background: linear-gradient(135deg, #101828, #385a95);
  color: #fff;
}

.kicker {
  margin: 0 0 8px;
  color: #a9c7ff;
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

h2,
h3,
p {
  margin: 0;
}

h2 {
  font-size: 32px;
}

.hero-card p:not(.kicker) {
  margin-top: 8px;
  color: #d8e4f7;
}

.app-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}

.app-card {
  display: grid;
  gap: 14px;
}

.app-icon {
  width: 54px;
  height: 54px;
  display: grid;
  place-items: center;
  border-radius: 18px;
  background: #eef4ff;
  font-size: 28px;
}

.app-card p,
.empty-panel p {
  margin-top: 6px;
  color: #667085;
}
</style>
