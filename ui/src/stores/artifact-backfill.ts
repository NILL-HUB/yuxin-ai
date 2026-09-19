import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ChatArtifact } from '@/views/shared/chat-output'

/**
 * 成品就绪回填池：承接「异步任务完成后推回来的产物」。
 *
 * **为什么需要独立 store**：推送到达时，前端并不知道用户当前是否停留在
 * 那条消息所在的对话/视图里（HomeView、我的应用等多个入口都渲染消息）。
 * 若让推送处理器直接去改某个视图的 messages 数组，就要在每个入口重复接一遍。
 * 故这里只做「按 message_id 寄存」，由渲染消息的组件按自身 message_id 取用——
 * 一处接收，各处生效。
 *
 * 刷新后不丢：产物已由后端持久化到 message_agent_thought（见
 * `artifact_notification_service._persist_artifact_thought`），
 * 历史接口会把 artifacts 一并返回，本 store 只负责「在线那一刻」的即时补挂。
 */
export const useArtifactBackfillStore = defineStore('artifact-backfill', () => {
  // message_id -> artifacts
  const artifactsByMessage = ref<Record<string, ChatArtifact[]>>({})

  const addArtifact = (messageId: string, artifact: ChatArtifact) => {
    const normalizedMessageId = String(messageId || '').trim()
    const url = String(artifact?.url || '').trim()
    if (!normalizedMessageId || !url)
      return

    const existing = artifactsByMessage.value[normalizedMessageId] || []
    if (existing.some(item => String(item.url || '').trim() === url))
      return

    artifactsByMessage.value = {
      ...artifactsByMessage.value,
      [normalizedMessageId]: [...existing, artifact],
    }
  }

  const artifactsForMessage = (messageId: string): ChatArtifact[] => {
    const normalizedMessageId = String(messageId || '').trim()
    if (!normalizedMessageId)
      return []
    return artifactsByMessage.value[normalizedMessageId] || []
  }

  const clear = () => {
    artifactsByMessage.value = {}
  }

  return { artifactsByMessage, addArtifact, artifactsForMessage, clear }
})
