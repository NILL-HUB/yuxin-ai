<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Message, Modal } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import {
  chatAgent,
  gdprDeleteMemory,
  getMemoryStats,
  listAgents,
  listConversations,
  listMemories,
  listMessages,
  type AdminAgent,
  type ChatFrame,
  type ChatMessage,
  type ConversationItem,
  type MemoryItem,
  type MemoryStats,
} from '@/services/admin-agents'
import { getErrorMessage } from '@/utils/error'
import { useAdminStore } from '@/stores/admin'
import { httpCode } from '@/config'
import { formatAgentTime } from '@/utils/admin-agent-display'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const adminStore = useAdminStore()

const agentId = String(route.params.id || '')

const agent = ref<AdminAgent | null>(null)
const conversations = ref<ConversationItem[]>([])
const currentConversationId = ref<string | null>(null)
const messages = ref<ChatMessage[]>([])
const messagesLoading = ref(false)

const input = ref('')
const streaming = ref(false)
const streamBuffer = ref<ChatMessage[]>([])

const memoryLoading = ref(false)
const memoryStats = ref<MemoryStats | null>(null)
const memories = ref<MemoryItem[]>([])
const memoryTotal = ref(0)
const memoryPage = ref(1)
const memoryPageSize = 10
const memoryClearLoading = ref(false)

const goBack = () => router.push('/admin/agents')

const loadAgent = async () => {
  try {
    const items = await listAgents()
    agent.value = items.find((item) => item.id === agentId) || null
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agents.loadFailed')))
  }
}

const loadConversations = async () => {
  try {
    conversations.value = await listConversations(agentId)
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agents.chatError')))
  }
}

const openConversation = async (conversationId: string) => {
  if (streaming.value) return
  currentConversationId.value = conversationId
  messagesLoading.value = true
  messages.value = []
  try {
    messages.value = await listMessages(conversationId)
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agents.chatError')))
  } finally {
    messagesLoading.value = false
  }
}

const newConversation = () => {
  if (streaming.value) return
  currentConversationId.value = null
  messages.value = []
  input.value = ''
}

const pushUserMessage = (text: string) => {
  messages.value.push({
    id: `local-${Date.now()}`,
    role: 'user',
    content: text,
    created_at: Math.floor(Date.now() / 1000),
  })
}

const renderToolContent = (message: ChatMessage) => {
  try {
    const parsed = typeof message.content === 'string' ? JSON.parse(message.content) : message.content
    const call = parsed?.call || {}
    return {
      name: call.name || t('admin.agents.toolCall'),
      result: typeof parsed?.result === 'string' ? parsed.result : JSON.stringify(parsed?.result || ''),
    }
  } catch {
    return { name: t('admin.agents.toolCall'), result: message.content }
  }
}

const sendMessage = async () => {
  const text = input.value.trim()
  if (!text || streaming.value) return
  if (!agent.value) {
    Message.warning(t('admin.agents.chatError'))
    return
  }
  input.value = ''
  streaming.value = true
  streamBuffer.value = []
  pushUserMessage(text)

  const onFrame = (frame: ChatFrame) => {
    if (frame.event === 'message') {
      const conversationId = frame.data.conversation_id as string
      if (conversationId && !currentConversationId.value) {
        currentConversationId.value = conversationId
      }
    } else if (frame.event === 'tool') {
      streamBuffer.value.push({
        id: `tool-${Date.now()}-${streamBuffer.value.length}`,
        role: 'tool',
        content: JSON.stringify(frame.data),
        tool_calls: [frame.data],
        created_at: Math.floor(Date.now() / 1000),
      })
    } else if (frame.event === 'answer') {
      streamBuffer.value.push({
        id: `answer-${Date.now()}`,
        role: 'assistant',
        content: String(frame.data.answer || ''),
        created_at: Math.floor(Date.now() / 1000),
      })
    } else if (frame.event === 'error') {
      Message.error(String(frame.data.error || t('admin.agents.chatError')))
    }
  }

  try {
    const result = await chatAgent(
      agentId,
      { query: text, conversation_id: currentConversationId.value },
      onFrame,
    )
    // ssePost 在服务端返回 JSON（非 SSE 流）时 resolve 出 envelope 而非抛出；
    // 校验失败/鉴权等非 success 场景在此显式报错。
    if (result && typeof result === 'object' && result.code !== httpCode.success) {
      Message.error(result.message || t('admin.agents.chatError'))
    }
    messages.value.push(...streamBuffer.value)
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agents.streamFailed')))
  } finally {
    streaming.value = false
    streamBuffer.value = []
    await loadConversations()
  }
}

// ---------- 记忆面板 ----------

const loadMemory = async () => {
  memoryLoading.value = true
  try {
    const [stats, list] = await Promise.all([
      getMemoryStats(agentId),
      listMemories(agentId, { page: memoryPage.value, page_size: memoryPageSize }),
    ])
    memoryStats.value = stats
    memories.value = list.items || []
    memoryTotal.value = list.total || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agents.memoryLoadFailed')))
  } finally {
    memoryLoading.value = false
  }
}

const loadMemoryPage = async (page: number) => {
  memoryPage.value = page
  try {
    const list = await listMemories(agentId, { page, page_size: memoryPageSize })
    memories.value = list.items || []
    memoryTotal.value = list.total || 0
  } catch (error) {
    Message.error(getErrorMessage(error, t('admin.agents.memoryLoadFailed')))
  }
}

const clearMemory = () => {
  Modal.confirm({
    title: t('admin.agents.memoryClearTitle'),
    content: () => t('admin.agents.memoryClearDesc'),
    okText: t('common.actions.confirm'),
    okButtonProps: { status: 'danger' },
    cancelText: t('common.actions.cancel'),
    onBeforeOk: async () => {
      memoryClearLoading.value = true
      try {
        await gdprDeleteMemory({
          subject_type: 'admin',
          subject_id: adminStore.admin.id,
          agent_id: agentId,
        })
        Message.success(t('admin.agents.memoryClearSuccess'))
        await loadMemory()
        return true
      } catch (error) {
        Message.error(getErrorMessage(error, t('admin.agents.memoryClearFailed')))
        return false
      } finally {
        memoryClearLoading.value = false
      }
    },
  })
}

const memoryStatItems = computed(() => [
  { label: t('admin.agents.totalNodes'), value: memoryStats.value?.total_nodes ?? '-' },
  { label: t('admin.agents.episodes'), value: memoryStats.value?.episodes ?? '-' },
  { label: t('admin.agents.skills'), value: memoryStats.value?.skills ?? '-' },
])

const formatTime = (value: number | null | undefined) => formatAgentTime(value)

onMounted(async () => {
  await Promise.all([loadAgent(), loadConversations(), loadMemory()])
})
</script>

<template>
  <section class="flex h-full min-h-0 flex-col">
    <header class="mb-4 flex items-center justify-between gap-3">
      <div class="flex items-center gap-3">
        <a-button size="mini" @click="goBack">
          <template #icon><icon-left /></template>
          {{ t('admin.agents.chatBack') }}
        </a-button>
        <div>
          <h1 class="text-xl font-semibold text-slate-900">{{ t('admin.agents.chatTitle') }}：{{ agent?.name || '-' }}</h1>
          <p v-if="agent?.description" class="mt-0.5 text-xs text-slate-400">{{ agent.description }}</p>
        </div>
      </div>
      <a-button size="mini" type="outline" :disabled="streaming" @click="newConversation">
        <template #icon><icon-plus /></template>
        {{ t('admin.agents.newConversation') }}
      </a-button>
    </header>

    <div class="grid min-h-0 flex-1 gap-4" :class="'grid-cols-[240px_1fr_320px]'">
      <!-- 会话列表 -->
      <aside class="flex min-h-0 flex-col rounded-xl border border-slate-200 bg-white p-3">
        <div class="mb-2 flex items-center justify-between">
          <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">{{ t('admin.agents.conversation') }}</p>
          <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">
            {{ conversations.length }}
          </span>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto">
          <a-empty v-if="!conversations.length" :description="t('admin.agents.conversationEmpty')" :image-simple="true" />
          <div v-else class="space-y-1">
            <button
              v-for="item in conversations"
              :key="item.id"
              class="block w-full rounded-lg px-2.5 py-2 text-left transition"
              :class="item.id === currentConversationId ? 'bg-blue-50 text-blue-700' : 'text-slate-600 hover:bg-slate-50'"
              @click="openConversation(item.id)"
            >
              <div class="truncate text-sm" :class="item.id === currentConversationId ? 'font-medium' : ''">{{ item.title }}</div>
              <div class="mt-0.5 text-[10px] text-slate-400">{{ formatTime(item.updated_at) }}</div>
            </button>
          </div>
        </div>
      </aside>

      <!-- 对话区 -->
      <main class="flex min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div class="flex-1 space-y-3 overflow-y-auto p-4" :class="messagesLoading || streaming ? 'opacity-70' : ''">
          <a-spin v-if="messagesLoading" style="width: 100%" />
          <a-empty
            v-else-if="!messages.length && !streaming"
            :description="t('admin.agents.chatEmpty')"
            class="py-16"
          />
          <div
            v-for="message in messages"
            :key="message.id"
            class="flex"
            :class="message.role === 'user' ? 'justify-end' : 'justify-start'"
          >
            <div
              class="max-w-[80%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm shadow-sm"
              :class="message.role === 'user' ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-800'"
            >
              <div v-if="message.role === 'tool'" class="text-xs">
                <div class="mb-1 flex items-center gap-1.5 text-slate-500">
                  <icon-code-square />
                  <span class="font-medium">{{ renderToolContent(message).name }}</span>
                </div>
                <pre class="max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-white p-2 text-slate-600">{{ renderToolContent(message).result }}</pre>
              </div>
              <template v-else>{{ message.content || '…' }}</template>
            </div>
          </div>
          <div v-if="streaming" class="flex items-center gap-2 text-sm text-slate-400">
            <a-spin :size="14" />
            {{ t('admin.agents.sending') }}
          </div>
        </div>
        <div class="border-t border-slate-200 p-3">
          <div class="flex items-end gap-2">
            <a-textarea
              v-model="input"
              :placeholder="t('admin.agents.chatPlaceholder')"
              :auto-size="{ minRows: 1, maxRows: 5 }"
              :disabled="streaming"
              @press-enter="sendMessage"
            />
            <a-button type="primary" :loading="streaming" @click="sendMessage">
              <template #icon><icon-send /></template>
              {{ t('admin.agents.send') }}
            </a-button>
          </div>
        </div>
      </main>

      <!-- 记忆面板 -->
      <aside class="flex min-h-0 flex-col gap-3 overflow-y-auto">
        <div class="rounded-xl border border-slate-200 bg-white p-3">
          <div class="mb-2 flex items-center justify-between">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">{{ t('admin.agents.memoryStats') }}</p>
            <a-button size="mini" status="danger" :loading="memoryClearLoading" @click="clearMemory">{{ t('admin.agents.memoryClear') }}</a-button>
          </div>
          <a-spin :loading="memoryLoading" style="width: 100%">
            <div class="grid grid-cols-3 gap-2">
              <div v-for="item in memoryStatItems" :key="item.label" class="rounded-lg bg-slate-50 p-2 text-center">
                <div class="text-lg font-semibold text-slate-900">{{ item.value }}</div>
                <div class="text-[10px] text-slate-400">{{ item.label }}</div>
              </div>
            </div>
          </a-spin>
        </div>

        <div class="flex min-h-0 flex-col rounded-xl border border-slate-200 bg-white p-3">
          <p class="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">{{ t('admin.agents.memoryList') }}</p>
          <a-spin :loading="memoryLoading" style="width: 100%">
            <a-empty v-if="!memories.length" :description="t('admin.agents.memoryEmpty')" :image-simple="true" />
            <div v-else class="space-y-2">
              <div v-for="item in memories" :key="item.id" class="rounded-lg bg-slate-50 p-2.5">
                <div class="text-sm font-medium text-slate-800">{{ item.title || t('admin.agents.memoryEmpty') }}</div>
                <div class="mt-0.5 line-clamp-3 text-xs text-slate-500">{{ item.content }}</div>
                <div class="mt-1 text-[10px] text-slate-400">{{ formatTime(item.updated_at) }}</div>
              </div>
            </div>
          </a-spin>
          <a-pagination
            v-if="memoryTotal > memoryPageSize"
            class="mt-3"
            :total="memoryTotal"
            :current="memoryPage"
            :page-size="memoryPageSize"
            size="mini"
            @change="loadMemoryPage"
          />
        </div>
      </aside>
    </div>
  </section>
</template>
