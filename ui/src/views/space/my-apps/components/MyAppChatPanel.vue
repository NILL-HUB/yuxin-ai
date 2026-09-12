<script setup lang="ts">
/**
 * 我的应用 · 对话面板
 *
 * 直接复用现成的 agent 聊天框（ChatMessageTimeline + ChatComposer + AiMessage），
 * 与应用调试/商店预览保持一致的渲染能力（思考过程、产物、建议追问、工具确认）。
 *
 * 后端 agent = 用户长期记忆 + 该应用的工具插件/知识库/上下文
 * （由 `POST /my/apps/<app_id>/chat` → `AppDebugService.debug_chat` 提供）。
 */
import ChatComposer from '@/components/ChatComposer.vue'
import ChatMessageTimeline from '@/components/chat/ChatMessageTimeline.vue'
import ToolConfirmationCard from '@/components/ToolConfirmationCard.vue'
import { useChatQueryInput } from '@/hooks/use-chat-query-input'
import { chatWithMyApp } from '@/services/my-apps'
import { postToolConfirmationCancel, postToolConfirmationConfirm } from '@/services/tool-confirmation'
import { useAccountStore } from '@/stores/account'
import { Message } from '@arco-design/web-vue'
import { computed, nextTick, onMounted, ref, watch, type PropType } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  applyChatStreamEvent,
  withChatRenderId,
  type RenderableStreamMessage,
  type StreamEventResponse,
  type StreamState,
  type ToolConfirmationPrompt,
} from '@/views/shared/chat-stream'

type MyAppChatMessage = RenderableStreamMessage & {
  query: string
  image_urls: string[]
  suggested_questions: string[]
}

const props = defineProps({
  app: { type: Object, default: () => ({}), required: true },
  sourceLabel: { type: String, default: '' },
})

const { t } = useI18n()
const accountStore = useAccountStore()
const activeAccount = computed(() => ({
  name:
    String(accountStore.account?.name || '').trim() ||
    String(accountStore.account?.email || '').split('@')[0] ||
    '',
  avatar: String(accountStore.account?.avatar || '').trim(),
}))

const { query, queryTextareaRef, adjustQueryTextareaHeight } = useChatQueryInput({
  getDraftKey: () => `my-apps:chat-query:${String(props.app?.id ?? '')}`,
  minHeight: 32,
  maxHeight: 96,
})

const messages = ref<MyAppChatMessage[]>([])
const loading = ref(false)
const taskId = ref('')
const conversationId = ref('')
const toolConfirmationPrompt = ref<ToolConfirmationPrompt | null>(null)
const timelineRef = ref<{ scrollToBottom?: () => void } | null>(null)

const setQueryTextareaRef = (element: HTMLTextAreaElement | null) => {
  queryTextareaRef.value = element
}

const createStreamMessage = (queryText: string): MyAppChatMessage =>
  withChatRenderId(
    {
      id: '',
      conversation_id: conversationId.value,
      answer: '',
      answer_parts: [],
      artifacts: [],
      latency: 0,
      total_token_count: 0,
      agent_thoughts: [],
      query: queryText,
      image_urls: [],
      suggested_questions: [],
    },
    'my-app',
  )

const resetConversation = () => {
  messages.value = []
  conversationId.value = ''
  toolConfirmationPrompt.value = null
  query.value = ''
}

const handleSubmit = async () => {
  const currentQuery = query.value.trim()
  if (!currentQuery || loading.value) return

  const currentMessage = createStreamMessage(currentQuery)
  messages.value.unshift(currentMessage)
  await nextTick()
  void timelineRef.value?.scrollToBottom?.()

  const streamState: StreamState = {
    position: 0,
    message_id: '',
    task_id: '',
    conversation_id: conversationId.value,
    billingEvents: [],
  }
  query.value = ''
  loading.value = true
  try {
    await chatWithMyApp(
      String(props.app?.id),
      { query: currentQuery, image_urls: [], conversation_id: conversationId.value },
      (eventResponse) => {
        const streamResult = applyChatStreamEvent(
          currentMessage,
          eventResponse as StreamEventResponse,
          streamState,
        )
        streamState.position = streamResult.state.position
        streamState.message_id = streamResult.state.message_id
        streamState.task_id = streamResult.state.task_id
        taskId.value = streamResult.state.task_id
        streamState.conversation_id = streamResult.state.conversation_id
        if (streamResult.state.conversation_id) {
          conversationId.value = streamResult.state.conversation_id
        }
        if (streamResult.state.toolConfirmationPrompt) {
          toolConfirmationPrompt.value = streamResult.state.toolConfirmationPrompt
        }
        void timelineRef.value?.scrollToBottom?.()
      },
    )
  } catch (error: unknown) {
    Message.error(error instanceof Error ? error.message : t('myApps.sendFailed'))
  } finally {
    loading.value = false
    taskId.value = ''
  }
}

const handleConfirmTool = async (id: string) => {
  try {
    const response = await postToolConfirmationConfirm(id)
    const confirmation = response?.data
    if (toolConfirmationPrompt.value) {
      toolConfirmationPrompt.value.status = confirmation?.status || 'confirmed'
      toolConfirmationPrompt.value.execution_summary = confirmation?.execution_summary || ''
    }
  } catch {
    if (toolConfirmationPrompt.value) {
      toolConfirmationPrompt.value.status = 'cancelled'
    }
  }
}

const handleCancelTool = async (id: string) => {
  try {
    await postToolConfirmationCancel(id)
    if (toolConfirmationPrompt.value) {
      toolConfirmationPrompt.value.status = 'cancelled'
    }
  } catch {
    // 取消失败不阻塞用户体验
  }
}

const handleDismissToolConfirmation = () => {
  toolConfirmationPrompt.value = null
}

const handleQueryKeydown = (event: KeyboardEvent) => {
  const isSubmitShortcut =
    event.key === 'Enter' &&
    !event.shiftKey &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.altKey &&
    !event.isComposing
  if (!isSubmitShortcut) return
  event.preventDefault()
  void handleSubmit()
}

watch(query, () => adjustQueryTextareaHeight())

// 切换应用时重置会话，避免把上一个应用的上下文带过来
watch(
  () => String(props.app?.id ?? ''),
  () => resetConversation(),
)

onMounted(() => {
  void nextTick(() => adjustQueryTextareaHeight())
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col overflow-hidden">
    <div class="flex-1 min-h-0 flex flex-col overflow-hidden">
      <div v-if="messages.length > 0" class="flex-1 min-h-0 overflow-hidden flex flex-col px-4 sm:px-6">
        <chat-message-timeline
          ref="timelineRef"
          class="flex-1 min-h-0"
          :messages="messages"
          :account="activeAccount"
          :app="props.app"
          :loading="loading"
          :text-to-speech-enable="false"
        />
      </div>
      <div
        v-else
        class="flex-1 min-h-0 flex flex-col gap-3 items-center justify-center overflow-hidden px-6"
      >
        <a-avatar :size="48" shape="square" class="rounded-lg" :image-url="props.app?.icon" />
        <div class="text-lg text-text-2">{{ props.app?.name }}</div>
        <p class="text-sm text-muted">{{ t('myApps.chatEmpty') }}</p>
        <span v-if="props.sourceLabel" class="my-chat-source-chip">{{ props.sourceLabel }}</span>
      </div>
    </div>

    <div class="w-full flex flex-col shrink-0 border-t border-border-c bg-surface/70 backdrop-blur">
      <div
        v-if="toolConfirmationPrompt"
        class="w-full max-w-[600px] mx-auto px-4 sm:px-6 pb-2 flex justify-center"
      >
        <ToolConfirmationCard
          :prompt="toolConfirmationPrompt"
          @confirm="handleConfirmTool"
          @cancel="handleCancelTool"
          @dismiss="handleDismissToolConfirmation"
        />
      </div>
      <div class="px-4 sm:px-6 pt-4">
        <chat-composer
          v-model="query"
          size="compact"
          :textarea-ref-setter="setQueryTextareaRef"
          :show-upload-button="false"
          :show-voice-button="false"
          :show-clear-button="true"
          :clear-disabled="messages.length === 0"
          :submit-loading="loading"
          :clear-title="t('myApps.clearSession')"
          :placeholder="t('myApps.inputPlaceholder')"
          @clear="resetConversation"
          @input="() => adjustQueryTextareaHeight()"
          @keydown="(event) => handleQueryKeydown(event)"
          @submit="handleSubmit"
        />
      </div>
      <div class="text-center text-muted text-xs py-4">
        {{ t('chat.messages.aiGeneratedDisclaimer') }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.my-chat-source-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  background: var(--aicss-surface-2);
  color: var(--aicss-text-2);
  padding: 2px 10px;
  font-size: 12px;
}
</style>
