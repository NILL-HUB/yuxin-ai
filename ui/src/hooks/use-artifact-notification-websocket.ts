import type { ChatArtifact } from '@/views/shared/chat-output'
import { createNotificationWebSocket } from '@/hooks/use-notification-websocket'

/**
 * 成品就绪回填：异步渲染/剪辑任务完成后，把可播放地址推回原对话消息。
 *
 * 与「文档索引通知」共用同一套连接工厂，只是事件名与订阅事件不同——
 * 前者弹 toast 提示去知识库看，本通道则把播放器直接插进那条消息。
 */
export type ArtifactReadyPayload = {
  message_id?: string
  conversation_id?: string
  artifact?: ChatArtifact
  tool?: string
  title?: string
}

export const useArtifactNotificationWebSocket =
  createNotificationWebSocket<ArtifactReadyPayload>({
    connectLogMessage: '[WebSocket] Connected for artifact notifications',
    notificationEvent: 'artifact_ready',
    receiveLogMessage: '[WebSocket] Received artifact ready:',
    subscribeEvent: 'subscribe_artifact_notification',
    subscribeFailureLogMessage: '[WebSocket] Failed to subscribe artifact notifications:',
    unsubscribeEvent: 'unsubscribe_artifact_notification',
  })
