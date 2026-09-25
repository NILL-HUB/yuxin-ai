<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted, type Ref } from 'vue'
import DocumentIndexNotification from '@/components/DocumentIndexNotification.vue'
import AgentNotification from '@/components/AgentNotification.vue'
import DesktopTitleBar from '@/components/DesktopTitleBar.vue'
import { useDocumentIndexNotificationWebSocket } from '@/hooks/use-document-index-notification-websocket'
import { useDocumentIndexNotificationPolling } from '@/hooks/use-document-index-notification-polling'
import { useAgentNotificationWebSocket } from '@/hooks/use-agent-notification-websocket'
import { useAgentNotificationPolling } from '@/hooks/use-agent-notification-polling'
import {
  useArtifactNotificationWebSocket,
  type ArtifactReadyPayload,
} from '@/hooks/use-artifact-notification-websocket'
import { useArtifactBackfillStore } from '@/stores/artifact-backfill'
import type { DocumentIndexNotification as DocumentNotificationType } from '@/models/notification'
import type { AgentNotification as AgentNotificationType } from '@/models/agent-notification'
import { useI18n } from 'vue-i18n'
import arcoEnUS from '@arco-design/web-vue/es/locale/lang/en-us'
import arcoZhCN from '@arco-design/web-vue/es/locale/lang/zh-cn'
import { useTheme } from '@/theme'
import { useRealm } from '@/hooks/use-realm'

// 初始化主题系统（响应式应用 data-theme / arco-theme）
useTheme()

// 桌面环境（Electron）：窗口采用 titleBarStyle:hidden，自绘标题栏占 44px。
// Web 部署无标题栏，CSS 变量归零，布局不受影响。
const isDesktop =
  typeof window !== 'undefined' &&
  Boolean((window as unknown as { __DESKTOP_CONFIG__?: unknown }).__DESKTOP_CONFIG__)
const titlebarHeight = computed(() => (isDesktop ? '44px' : '0px'))

// 获取通知组件的引用
const documentNotificationRef = ref<InstanceType<typeof DocumentIndexNotification>>()
const agentNotificationRef = ref<InstanceType<typeof AgentNotification>>()
const POLLING_FALLBACK_DELAY = 3000
const { locale } = useI18n()
const arcoLocale = computed(() => (locale.value === 'en-US' ? arcoEnUS : arcoZhCN))

// 初始化文档索引通知 WebSocket 监听
// 通知通道（文档索引 / Agent 构建 / 成品就绪）是用户域能力，admin 上下文下
// 既无展示位、又会拿用户域 token 去握手，故按 realm 门控，仅在非 admin 时启用。
const { isAdmin } = useRealm()
const notificationGateOpen = computed(() => !isAdmin.value)

const {
  subscribeToNotifications,
  isEnabled: isDocumentNotificationEnabled,
  isReady: isDocumentNotificationReady,
} = useDocumentIndexNotificationWebSocket(notificationGateOpen)

// 初始化文档索引通知轮询备选方案
const { startPolling, stopPolling } = useDocumentIndexNotificationPolling()

// 初始化 Agent 通知 WebSocket 监听
const {
  subscribeToNotifications: subscribeToAgentNotifications,
  isEnabled: isAgentNotificationEnabled,
  isReady: isAgentNotificationReady,
} = useAgentNotificationWebSocket(notificationGateOpen)

// 初始化「成品就绪」回填监听：异步渲染/剪辑完成后把播放器插回原消息。
// 无需轮询兜底——产物已持久化到消息（刷新后由历史接口带回），本通道只负责即时补挂。
// 同属用户域通道，admin 上下文下按 realm 门控不建立连接。
const { subscribeToNotifications: subscribeToArtifactNotifications } =
  useArtifactNotificationWebSocket(notificationGateOpen)
const artifactBackfillStore = useArtifactBackfillStore()

// 初始化 Agent 通知轮询备选方案
const { startPolling: startAgentPolling, stopPolling: stopAgentPolling } =
  useAgentNotificationPolling()

const handleDocumentNotifications = (notifications: DocumentNotificationType[]) => {
  notifications.forEach((notification) => {
    documentNotificationRef.value?.addNotification(notification)
  })
}

const handleAgentNotifications = (notifications: AgentNotificationType[]) => {
  notifications.forEach((notification) => {
    agentNotificationRef.value?.addNotification(notification)
  })
}

const createPollingFallbackController = (
  isEnabled: Ref<boolean>,
  isReady: Ref<boolean>,
  start: () => void,
  stop: () => void,
) => {
  let fallbackTimer: ReturnType<typeof setTimeout> | null = null
  let hasBeenReady = false

  const clearFallbackTimer = () => {
    if (!fallbackTimer) {
      return
    }

    clearTimeout(fallbackTimer)
    fallbackTimer = null
  }

  const startFallback = () => {
    if (hasBeenReady) {
      start()
      return
    }

    if (fallbackTimer) {
      return
    }

    fallbackTimer = setTimeout(() => {
      fallbackTimer = null
      if (!isReady.value) {
        start()
      }
    }, POLLING_FALLBACK_DELAY)
  }

  const stopFallback = () => {
    clearFallbackTimer()
    stop()

    if (isReady.value) {
      hasBeenReady = true
    }
  }

  watch(
    [isEnabled, isReady],
    ([enabled, ready]) => {
      if (!enabled) {
        stopFallback()
        return
      }

      if (ready) {
        stopFallback()
        return
      }

      startFallback()
    },
    { immediate: true },
  )

  return () => {
    clearFallbackTimer()
    stop()
  }
}

const stopDocumentPollingFallback = createPollingFallbackController(
  isDocumentNotificationEnabled,
  isDocumentNotificationReady,
  () => {
    startPolling(handleDocumentNotifications)
  },
  stopPolling,
)

const stopAgentPollingFallback = createPollingFallbackController(
  isAgentNotificationEnabled,
  isAgentNotificationReady,
  () => {
    startAgentPolling(handleAgentNotifications)
  },
  stopAgentPolling,
)

onMounted(() => {
  // 订阅文档索引完成通知（WebSocket 优先）
  subscribeToNotifications((notification: DocumentNotificationType) => {
    documentNotificationRef.value?.addNotification(notification)
  })

  // 订阅 Agent 完成通知
  subscribeToAgentNotifications((notification: AgentNotificationType) => {
    agentNotificationRef.value?.addNotification(notification)
  })

  // 订阅「成品就绪」回填：把产物寄存到 store，由渲染该消息的组件按 message_id 取用
  subscribeToArtifactNotifications((payload: ArtifactReadyPayload) => {
    const artifact = payload?.artifact
    if (!artifact || !payload?.message_id)
      return
    artifactBackfillStore.addArtifact(String(payload.message_id), artifact)
  })
})

onUnmounted(() => {
  stopDocumentPollingFallback()
  stopAgentPollingFallback()
})
</script>

<template>
  <a-config-provider :locale="arcoLocale">
    <div
      class="h-full w-full flex flex-col"
      :style="{ '--desktop-titlebar-h': titlebarHeight }"
    >
      <!-- 文档索引完成通知组件 -->
      <document-index-notification ref="documentNotificationRef" />

      <!-- Agent 构建完成通知组件 -->
      <agent-notification ref="agentNotificationRef" />

      <!-- 路由视图（桌面端各页面自行用 calc 扣除标题栏高度） -->
      <router-view />
    </div>
    <!-- 桌面自绘标题栏：fixed 悬浮于窗口顶部（仅 Electron 环境渲染） -->
    <desktop-title-bar v-if="isDesktop" />
  </a-config-provider>
</template>

<style scoped></style>
