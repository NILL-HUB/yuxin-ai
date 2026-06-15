<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { chatWithMyApp } from '@/services/my-apps'
import { getErrorMessage } from '@/utils/error'

const route = useRoute()
const appId = String(route.params.app_id)
const query = ref('')
const sending = ref(false)
const messages = ref<{ role: 'user' | 'assistant'; content: string }[]>([])

const sendMessage = async () => {
  const content = query.value.trim()
  if (!content) return
  messages.value.push({ role: 'user', content })
  query.value = ''
  sending.value = true
  const assistantMessage = { role: 'assistant' as const, content: '' }
  messages.value.push(assistantMessage)
  try {
    await chatWithMyApp(appId, { query: content, image_urls: [], conversation_id: '' }, (event) => {
      const data = event.data as { answer?: string } | undefined
      if (data?.answer) assistantMessage.content += data.answer
    })
  } catch (error) {
    Message.error(getErrorMessage(error, '发送失败'))
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <section class="my-ai-chat-page">
    <header class="chat-header">
      <p class="kicker">My AI Chat</p>
      <h2>AI 功能对话</h2>
      <p>当前对话会按你的算力值账户扣减。</p>
    </header>

    <main class="chat-panel">
      <article v-for="(message, index) in messages" :key="index" :class="['message-row', `message-row--${message.role}`]">
        <strong>{{ message.role === 'user' ? '我' : 'AI' }}</strong>
        <p>{{ message.content }}</p>
      </article>
    </main>

    <footer class="composer">
      <a-textarea v-model="query" placeholder="输入你的问题" />
      <a-button type="primary" :loading="sending" @click="sendMessage">发送</a-button>
    </footer>
  </section>
</template>

<style scoped>
.my-ai-chat-page {
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto 1fr auto;
  gap: 16px;
  padding: 32px;
  background: #f4f7fb;
}

.chat-header,
.chat-panel,
.composer {
  padding: 20px;
  border-radius: 22px;
  background: #fff;
  box-shadow: 0 14px 40px rgba(15, 23, 42, 0.06);
}

.chat-header {
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
p {
  margin: 0;
}

.chat-header p:not(.kicker) {
  margin-top: 8px;
  color: #d8e4f7;
}

.chat-panel {
  display: grid;
  align-content: start;
  gap: 12px;
}

.message-row {
  max-width: 760px;
  padding: 14px 16px;
  border-radius: 16px;
  background: #f8fafc;
}

.message-row--user {
  justify-self: end;
  background: #e7f0ff;
}

.message-row p {
  margin-top: 6px;
  color: #344054;
}

.composer {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) auto;
  gap: 12px;
}
</style>
