<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

type WindowControlsBridge = {
  minimize: () => void
  toggleMaximize: () => void
  close: () => void
  isMaximized: () => Promise<boolean>
  getOverlayState: () => Promise<{ overlay: boolean }>
  onMaximizedChanged: (cb: (isMaximized: boolean) => void) => () => void
}

const bridge = (window as unknown as { windowControls?: WindowControlsBridge }).windowControls
const isDesktop = computed(() => Boolean(bridge))
const isMaximized = ref(false)
const overlayEnabled = ref(false)
const overlayWidth = ref(0)
const appName = ref('钰心AI')

const resolveAppName = () => {
  if (typeof window === 'undefined') return
  const cfg = (window as unknown as { __DESKTOP_CONFIG__?: { appName?: string } }).__DESKTOP_CONFIG__
  if (cfg?.appName) {
    appName.value = cfg.appName
    return
  }
  const title = document.title
  if (title && title !== '%APP_TITLE%') {
    appName.value = title
  }
}

// Windows titleBarOverlay：系统原生 min/max/close 按钮区域（右上角）。
// 精确宽度经 WCO API 读取，避免标题栏内容被按钮遮挡。
const updateOverlayWidth = () => {
  try {
    const nav = navigator as Navigator & {
      windowControlsOverlay?: { getTitlebarAreaRect: () => DOMRect; visible: boolean }
    }
    if (nav.windowControlsOverlay) {
      const rect = nav.windowControlsOverlay.getTitlebarAreaRect()
      overlayWidth.value = rect.width || 0
      overlayEnabled.value = nav.windowControlsOverlay.visible !== false
    }
  } catch {
    overlayEnabled.value = false
  }
}

let unsubscribeMaximized: (() => void) | null = null
let unsubscribeOverlayChange: (() => void) | null = null

onMounted(async () => {
  if (!bridge) return
  resolveAppName()
  try {
    isMaximized.value = await bridge.isMaximized()
    updateOverlayWidth()
  } catch {
    // bridge 未就绪时保持默认
  }
  unsubscribeMaximized = bridge.onMaximizedChanged((value) => {
    isMaximized.value = value
  })
  try {
    const nav = navigator as Navigator & {
      windowControlsOverlay?: {
        addEventListener: (type: string, cb: () => void) => void
        removeEventListener: (type: string, cb: () => void) => void
      }
    }
    if (nav.windowControlsOverlay?.addEventListener) {
      const onChange = () => updateOverlayWidth()
      nav.windowControlsOverlay.addEventListener('geometrychange', onChange)
      unsubscribeOverlayChange = () => nav.windowControlsOverlay?.removeEventListener('geometrychange', onChange)
    }
  } catch {
    // WCO 不可用时忽略
  }
})

onUnmounted(() => {
  unsubscribeMaximized?.()
  unsubscribeOverlayChange?.()
})

const maximizeIcon = computed(() => (isMaximized.value ? 'restore' : 'maximize'))
const controlsAreaStyle = computed(() => ({
  width: overlayEnabled.value && overlayWidth.value > 0 ? `${overlayWidth.value}px` : '138px',
}))
</script>

<template>
  <div
    v-if="isDesktop"
    class="desktop-titlebar fixed left-0 right-0 top-0 z-[100] flex h-11 items-center border-b border-border-c select-none"
    :style="{
      background: 'var(--aicss-bg, rgba(255,255,255,0.85))',
      backdropFilter: 'saturate(180%) blur(20px)',
      WebkitBackdropFilter: 'saturate(180%) blur(20px)',
    }"
    data-desktop-titlebar
  >
    <!-- 拖拽区（品牌区）：-webkit-app-region drag；双击切换最大化 -->
    <div
      class="flex h-full flex-1 items-center gap-2 pl-3 app-region-drag"
      :title="t('desktopTitleBar.doubleClickHint')"
      @dblclick="bridge?.toggleMaximize()"
    >
      <span class="text-[13px] font-medium text-text">{{ appName }}</span>
    </div>
    <!-- 窗口控制：Windows titleBarOverlay 开启时系统原生渲染 min/max/close 于右上角，
         此处仅预留同宽空间避免标题栏内容被系统按钮遮挡；overlay 关闭时回退到自绘按钮 -->
    <div v-if="overlayEnabled" class="overlay-placeholder h-full shrink-0" :style="controlsAreaStyle" />
    <div v-else class="window-controls flex h-full shrink-0 app-region-no-drag">
      <button
        type="button"
        class="flex h-full w-11 items-center justify-center text-muted transition-colors hover:bg-surface-2 hover:text-text"
        :aria-label="t('desktopTitleBar.minimize')"
        @click="bridge?.minimize()"
      >
        <svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true"><path d="M0 5h10" stroke="currentColor" stroke-width="1.2" /></svg>
      </button>
      <button
        type="button"
        class="flex h-full w-11 items-center justify-center text-muted transition-colors hover:bg-surface-2 hover:text-text"
        :aria-label="isMaximized ? t('desktopTitleBar.restore') : t('desktopTitleBar.maximize')"
        @click="bridge?.toggleMaximize()"
      >
        <svg v-if="maximizeIcon === 'maximize'" viewBox="0 0 10 10" width="10" height="10" aria-hidden="true">
          <rect x="0.5" y="0.5" width="9" height="9" fill="none" stroke="currentColor" stroke-width="1.2" />
        </svg>
        <svg v-else viewBox="0 0 10 10" width="10" height="10" aria-hidden="true">
          <path d="M2.5 2.5h7v7h-7z" fill="none" stroke="currentColor" stroke-width="1.2" />
          <path d="M0.5 7.5v-7h7" fill="none" stroke="currentColor" stroke-width="1.2" />
        </svg>
      </button>
      <button
        type="button"
        class="flex h-full w-11 items-center justify-center text-muted transition-colors hover:bg-red-500 hover:text-white"
        :aria-label="t('desktopTitleBar.close')"
        @click="bridge?.close()"
      >
        <svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true">
          <path d="M0.5 0.5l9 9M9.5 0.5l-9 9" stroke="currentColor" stroke-width="1.2" />
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
/* 拖拽区：-webkit-app-region 是窗口拖动关键 */
.app-region-drag {
  -webkit-app-region: drag;
}
.app-region-no-drag,
.app-region-no-drag * {
  -webkit-app-region: no-drag;
}
/* Windows titleBarOverlay：右侧预留原生窗口按钮宽度，由 windowControlsOverlay API 动态提供 */
.overlay-placeholder {
  -webkit-app-region: no-drag;
}
</style>
