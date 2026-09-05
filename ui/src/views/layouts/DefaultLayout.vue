<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useLogout } from '@/hooks/use-auth'
import LayoutSidebar from './components/LayoutSidebar.vue'
import RecentConversationsGlobalPopover from './components/RecentConversationsGlobalPopover.vue'
import { useGetCurrentUser } from '@/hooks/use-account'
import { getMembershipSummary } from '@/services/billing'
import { type MembershipSummary } from '@/models/billing'
import { useCredentialStore } from '@/stores/credential'
import { useAccountStore } from '@/stores/account'
import LoginModal from '@/views/auth/components/LoginModal.vue'
import { AUTH_REQUIRED_EVENT } from '@/utils/request'
import { isCredentialLoggedIn } from '@/utils/auth'

import IconYuxinAI from '@/components/icons/IconYuxinAI.vue'
import ThemeSwitch from '@/components/ThemeSwitch.vue'
import { useRoute } from 'vue-router'
import { getUserAvatarUrl } from '@/utils/helper'
import type { RecentConversation } from '@/models/conversation'

const SettingModal = defineAsyncComponent(
  () => import('@/views/layouts/components/SettingModal.vue'),
)

// 1.定义页面所需数据
const settingModalVisible = ref(false)
const settingModalInitialTab = ref<'profile' | 'security' | 'bindings' | 'devices' | 'language'>(
  'profile',
)
const loginModalVisible = ref(false)
const loginRedirectPath = ref('')
const sidebarCollapsed = ref(false)
const popoverVisible = ref(false)
type RecentConversationsPopoverData = {
  conversations: RecentConversation[]
  loading: boolean
}
type RecentConversationsShowDetail = RecentConversationsPopoverData & {
  triggerRect: { top: number; right: number }
}
const popoverData = ref<RecentConversationsPopoverData | null>(null)
const popoverPosition = ref({ top: 0, left: 0 })
const RECENT_CONVERSATIONS_POPOVER_MARGIN = 12
const OAUTH_RESULT_STORAGE_KEY = 'account_oauth_result'
const router = useRouter()
const route = useRoute()
const credentialStore = useCredentialStore()
const accountStore = useAccountStore()
const { handleLogout: handleLogoutHook } = useLogout()
const { current_user, loadCurrentUser } = useGetCurrentUser()
const { t } = useI18n()
const isLoggedIn = computed(() => isCredentialLoggedIn(credentialStore.credential))
const membershipSummary = ref<MembershipSummary | null>(null)
const isMember = computed(() => membershipSummary.value?.membership?.status === 'active')

// tier：'basic' 试用/普通会员（徽章盾图标），'advanced' 付费进阶会员（宝石图标）
const memberLevel = computed<{ label: string; tier: 'basic' | 'advanced' } | null>(() => {
  const plan = membershipSummary.value?.membership?.plan
  if (!plan?.code) return null
  const code = plan.code.toUpperCase()
  if (/^(FREE|TRIAL|TRY|EXPERIENCE)/.test(code)) {
    return { label: t('layout.account.memberLevel.trial'), tier: 'basic' }
  }
  if (code.includes('PRO')) {
    return { label: t('layout.account.memberLevel.pro'), tier: 'advanced' }
  }
  if (/^(VIP|ADV|ELITE|ULTRA|PREMIUM|SUPER|GOLD)/.test(code)) {
    return { label: t('layout.account.memberLevel.advanced'), tier: 'advanced' }
  }
  return { label: t('layout.account.memberLevel.member'), tier: 'basic' }
})
const creditBalance = computed(() => membershipSummary.value?.credit_account?.balance ?? 0)
const formatCredit = (value: number) => Number(value || 0).toLocaleString()

const loadMembershipBadge = async () => {
  try {
    membershipSummary.value = await getMembershipSummary()
  } catch {
    membershipSummary.value = null
  }
}
const sidebarWidth = computed(() => (sidebarCollapsed.value ? 80 : 272))
const MOBILE_BREAKPOINT = 768
const isMobileViewport = ref(false)

const applyViewportMode = () => {
  if (typeof window === 'undefined') return
  const mobile = window.innerWidth <= MOBILE_BREAKPOINT
  isMobileViewport.value = mobile
  if (mobile && !sidebarCollapsed.value) {
    sidebarCollapsed.value = true
  }
}

const openLoginModal = (redirect = '') => {
  loginRedirectPath.value = redirect
  loginModalVisible.value = true
}

const goHomeAndOpenLogin = () => {
  openLoginModal(router.currentRoute.value.fullPath)
}

const handleLoginSuccess = async () => {
  await loadCurrentUser()
  accountStore.update(current_user.value)
  loadMembershipBadge()

  const redirectPath = loginRedirectPath.value
  loginRedirectPath.value = ''
  if (redirectPath && redirectPath !== router.currentRoute.value.fullPath) {
    await router.replace(redirectPath)
  }
}

// 2.退出登录按钮
const handleLogout = async () => {
  // 2.1 发起请求退出登录
  await handleLogoutHook()

  // 2.2 清空授权凭证+账号信息
  credentialStore.clear()
  accountStore.clear()

  // 2.3 回到首页
  await router.replace({ path: '/home' })
}

// 3.登录后拉取当前账号信息
watch(
  isLoggedIn,
  async (loggedIn) => {
    if (!loggedIn) {
      accountStore.clear()
      membershipSummary.value = null
      return
    }
    await loadCurrentUser()
    accountStore.update(current_user.value)
    loadMembershipBadge()
  },
  { immediate: true },
)

const handleAuthRequired = (event: Event) => {
  if (isLoggedIn.value) return
  const customEvent = event as CustomEvent<{ redirect?: string }>
  const redirectPath = customEvent.detail?.redirect || router.currentRoute.value.fullPath
  openLoginModal(redirectPath)
}

const clamp = (value: number, min: number, max: number) => {
  if (max < min) return min
  return Math.min(Math.max(value, min), max)
}

const adjustRecentConversationsPopoverPosition = async () => {
  if (typeof window === 'undefined' || !popoverVisible.value) return

  await nextTick()

  const popoverElement = document.getElementById('recent-conversations-popover')
  if (!popoverElement) return

  const { innerWidth, innerHeight } = window
  const { width, height } = popoverElement.getBoundingClientRect()

  popoverPosition.value = {
    top: clamp(
      popoverPosition.value.top,
      RECENT_CONVERSATIONS_POPOVER_MARGIN,
      innerHeight - height - RECENT_CONVERSATIONS_POPOVER_MARGIN,
    ),
    left: clamp(
      popoverPosition.value.left,
      RECENT_CONVERSATIONS_POPOVER_MARGIN,
      innerWidth - width - RECENT_CONVERSATIONS_POPOVER_MARGIN,
    ),
  }
}

const handleRecentConversationsShow = (event: Event) => {
  const customEvent = event as CustomEvent<RecentConversationsShowDetail>
  const detail = customEvent.detail
  const rect = detail.triggerRect

  popoverPosition.value = {
    top: rect.top,
    left: rect.right + RECENT_CONVERSATIONS_POPOVER_MARGIN,
  }

  popoverData.value = {
    conversations: detail.conversations,
    loading: detail.loading,
  }
  popoverVisible.value = true

  void adjustRecentConversationsPopoverPosition()
}

const handleRecentConversationsHide = () => {
  popoverVisible.value = false
}

const handleViewportResize = () => {
  void adjustRecentConversationsPopoverPosition()
  applyViewportMode()
}

const clearAccountSettingsQuery = async () => {
  if (route.query.settings !== 'account') return

  const nextQuery = { ...route.query }
  delete nextQuery.settings
  delete nextQuery.tab
  delete nextQuery.t

  await router.replace({
    path: route.path,
    query: nextQuery,
  })
}

const openSettingsFromRoute = () => {
  if (route.query.settings !== 'account') return

  const tab = String(route.query.tab || 'profile')
  if (tab === 'security' || tab === 'bindings' || tab === 'devices' || tab === 'language') {
    settingModalInitialTab.value = tab
  } else {
    settingModalInitialTab.value = 'profile'
  }
  settingModalVisible.value = true

  const oauthResultRaw = sessionStorage.getItem(OAUTH_RESULT_STORAGE_KEY)
  if (!oauthResultRaw) return

  try {
    const oauthResult = JSON.parse(oauthResultRaw)
    const providerLabel = String(oauthResult.provider || '').toLowerCase()
    const displayName =
      providerLabel === 'github'
        ? 'GitHub'
        : providerLabel === 'google'
          ? 'Google'
          : oauthResult.provider
    if (oauthResult.action === 'bind') {
      Message.success(t('layout.account.oauthBindSuccess', { provider: displayName }))
    }
  } catch {
    Message.success(t('layout.account.oauthBindSuccessFallback'))
  } finally {
    sessionStorage.removeItem(OAUTH_RESULT_STORAGE_KEY)
  }
}

onMounted(() => {
  if (typeof window === 'undefined') return
  applyViewportMode()
  window.addEventListener(AUTH_REQUIRED_EVENT, handleAuthRequired as EventListener)
  window.addEventListener('recent-conversations:show', handleRecentConversationsShow)
  window.addEventListener('recent-conversations:hide', handleRecentConversationsHide)
  window.addEventListener('resize', handleViewportResize)
  openSettingsFromRoute()
})

onUnmounted(() => {
  if (typeof window === 'undefined') return
  window.removeEventListener(AUTH_REQUIRED_EVENT, handleAuthRequired as EventListener)
  window.removeEventListener('recent-conversations:show', handleRecentConversationsShow)
  window.removeEventListener('recent-conversations:hide', handleRecentConversationsHide)
  window.removeEventListener('resize', handleViewportResize)
})

watch(
  () => [route.query.settings, route.query.tab, route.query.t],
  () => {
    openSettingsFromRoute()
  },
)

watch(settingModalVisible, async (visible) => {
  if (visible) return
  await clearAccountSettingsQuery()
})
</script>

<template>
  <div class="h-full w-full overflow-hidden flex">
    <!-- 侧边栏 - 固定定位，不随右侧滚动 -->
    <a-layout-sider
      class="bg-surface border-r border-border-c p-2 shrink-0 overflow-hidden sidebar-sider"
      :class="{ 'sidebar-sider--mobile': isMobileViewport }"
      :style="{
        width: `${sidebarWidth}px`,
        minWidth: `${sidebarWidth}px`,
        maxWidth: `${sidebarWidth}px`,
        position: 'fixed',
        left: 0,
        top: 0,
        bottom: 0,
        height: '100vh',
        transform: isMobileViewport && sidebarCollapsed ? 'translateX(-100%)' : 'translateX(0)',
        zIndex: isMobileViewport ? (sidebarCollapsed ? 5 : 40) : 10,
      }"
    >
      <div
        class="flex flex-col min-h-0 overflow-hidden px-3 py-2"
        style="height: calc(100vh - 16px)"
      >
        <!-- 顶部 Logo 区 -->
        <div class="shrink-0 flex items-center justify-center">
          <!-- 展开态：Logo + 主题切换（横向） -->
          <div
            v-if="!sidebarCollapsed"
            class="h-10 flex items-center justify-between w-full gap-1.5 pb-0"
          >
            <div class="flex items-center justify-start flex-1 min-w-0 overflow-hidden pl-1">
              <IconYuxinAI type="character" :size="130" class="shrink-0" />
            </div>
            <ThemeSwitch class="!h-7 !w-7 !text-[13px]" />
          </div>
          <!-- 收起态：Logo + 主题切换（垂直线性、居中） -->
          <div v-else class="flex flex-col items-center justify-center gap-2 py-1">
            <div class="flex items-center justify-center w-10 h-10 shrink-0">
              <IconYuxinAI type="full" :size="32" class="shrink-0" />
            </div>
            <ThemeSwitch class="!h-7 !w-7 !text-[13px]" />
          </div>
        </div>
        <!-- 顶部间距 -->
        <div class="mb-3 shrink-0"></div>
        <!-- 侧边栏导航 - 中间可滚动区域 -->
        <layout-sidebar class="flex-1 min-h-0 overflow-hidden" :collapsed="sidebarCollapsed" />
        <!-- 账号设置 - 固定在底部，不随滚动 -->
        <div class="shrink-0 border-t border-border-c px-3 py-3">
          <a-dropdown v-if="isLoggedIn" position="tl" trigger="click">
            <!-- 账号区：对齐原型（头像方块 + 用户名/会员·算力 单列 + 菜单箭头） -->
            <div
              class="flex w-full cursor-pointer items-center gap-2.5 rounded-[var(--aicss-radius)] transition-colors hover:bg-surface-2"
              :class="sidebarCollapsed ? 'justify-center px-1 py-1' : 'px-2 py-2'"
            >
              <!-- 头像：粉底圆角方块 -->
              <span
                class="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-[var(--aicss-radius)] bg-linear-to-br from-brand to-brand-text text-white shadow-[var(--aicss-shadow-card)]"
              >
                <img
                  v-if="getUserAvatarUrl(accountStore.account.avatar, accountStore.account.name)"
                  :src="getUserAvatarUrl(accountStore.account.avatar, accountStore.account.name)"
                  :alt="accountStore.account.name"
                  class="h-full w-full object-cover"
                />
                <icon-user v-else class="h-5 w-5" />
              </span>

              <!-- 文本（折叠态隐藏） -->
              <div v-show="!sidebarCollapsed" class="min-w-0 flex-1">
                <p class="truncate text-sm font-medium text-text">{{ accountStore.account.name }}</p>
                <!-- 会员等级（独立一行）：试用/普通会员用「√ 徽章盾」，付费/高级会员用「宝石」 -->
                <p
                  v-if="isMember"
                  class="mt-0.5 flex items-center gap-1 whitespace-nowrap text-xs text-muted"
                >
                  <!-- √ 徽章盾（试用 / 普通会员） -->
                  <svg
                    v-if="memberLevel?.tier === 'basic'"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    class="h-3.5 w-3.5 shrink-0 text-brand-text"
                    aria-hidden="true"
                  >
                    <path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z" />
                    <path d="m9 12 2 2 4-4" />
                  </svg>
                  <!-- 宝石（Pro / 高级会员） -->
                  <svg
                    v-else
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    class="h-3.5 w-3.5 shrink-0 text-brand-text"
                    aria-hidden="true"
                  >
                    <path d="M6 3h12l4 6-10 13L2 9Z" />
                    <path d="M11 3 8 9l4 13 4-13-3-6" />
                    <path d="M2 9h20" />
                  </svg>
                  <span class="truncate font-medium text-brand-text">{{ memberLevel?.label }}</span>
                </p>
                <!-- 算力值（独立一行）· 图标与会员中心「算力值」一致（闪电） -->
                <p class="mt-0.5 flex items-center gap-1 whitespace-nowrap text-xs text-muted">
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    class="h-3.5 w-3.5 shrink-0 text-amber-500"
                    aria-hidden="true"
                  >
                    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                  </svg>
                  <span class="truncate">{{ formatCredit(creditBalance) }}</span>
                </p>
              </div>

              <!-- 菜单箭头（折叠态隐藏） -->
              <span
                v-show="!sidebarCollapsed"
                class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-text"
              >
                <icon-right class="h-4 w-4" />
              </span>
            </div>
            <template #content>
              <a-doption @click="settingModalVisible = true">
                <template #icon>
                  <icon-settings />
                </template>
                {{ $t('layout.account.settings') }}
              </a-doption>
              <a-doption @click="handleLogout">
                <template #icon>
                  <icon-poweroff />
                </template>
                {{ $t('layout.account.logout') }}
              </a-doption>
            </template>
          </a-dropdown>
          <div v-show="!isLoggedIn" class="p-1.5 w-full">
            <a-button long class="rounded-[var(--aicss-radius)]" @click="goHomeAndOpenLogin">
              {{ $t('layout.account.login') }}
            </a-button>
          </div>
        </div>
      </div>
    </a-layout-sider>
    <!-- 侧栏折叠/展开把手：贴侧栏右缘、垂直居中（桌面端） -->
    <button
      v-if="!isMobileViewport"
      type="button"
      class="sidebar-collapse-handle"
      :class="{ 'is-collapsed': sidebarCollapsed }"
      :style="{ '--sidebar-edge': `${sidebarWidth}px` }"
      :title="sidebarCollapsed ? t('layout.sidebar.expand') : t('layout.sidebar.collapse')"
      :aria-label="sidebarCollapsed ? t('layout.sidebar.expand') : t('layout.sidebar.collapse')"
      @click="sidebarCollapsed = !sidebarCollapsed"
    >
      <icon-left v-if="!sidebarCollapsed" class="h-3.5 w-3.5" style="position: relative; z-index: 1" />
      <icon-right v-else class="h-3.5 w-3.5" style="position: relative; z-index: 1" />
    </button>
    <div
      v-if="isMobileViewport && !sidebarCollapsed"
      class="sidebar-mobile-scrim"
      @click="sidebarCollapsed = true"
    />
    <!-- 移动端浮动菜单按钮（唤出侧栏抽屉） -->
    <button
      v-if="isMobileViewport && sidebarCollapsed"
      class="mobile-menu-fab"
      aria-label="打开导航菜单"
      @click="sidebarCollapsed = false"
    >
      <icon-list class="h-5 w-5" />
    </button>
    <!-- 右侧内容 -->
    <a-layout-content
      class="!bg-transparent layout-content overflow-hidden flex flex-col"
      :style="{
        marginLeft: isMobileViewport ? '0px' : `${sidebarWidth}px`,
        width: isMobileViewport ? '100vw' : `calc(100vw - ${sidebarWidth}px)`,
        height: 'auto',
        flex: '1 1 0',
        minHeight: '0',
      }"
    >
      <router-view v-slot="{ Component }">
        <keep-alive include="HomeView">
          <component :is="Component" :key="route.path" class="flex-1 min-h-0" />
        </keep-alive>
      </router-view>
    </a-layout-content>
    <login-modal v-model:visible="loginModalVisible" @success="handleLoginSuccess" />
    <!-- 设置模态窗 -->
    <setting-modal v-model:visible="settingModalVisible" :initial-tab="settingModalInitialTab" />
    <!-- 最近对话全局 Popover -->
    <recent-conversations-global-popover
      v-if="popoverVisible && popoverData"
      :conversations="popoverData.conversations"
      :loading="popoverData.loading"
      :style="{
        position: 'fixed',
        top: `${popoverPosition.top}px`,
        left: `${popoverPosition.left}px`,
      }"
    />
  </div>
</template>

<style scoped>
.sidebar-sider {
  transition:
    width 1000ms cubic-bezier(0.4, 0, 0.2, 1),
    transform 240ms cubic-bezier(0.32, 0.72, 0, 1);
}

/* 侧栏折叠/展开把手：左端骑住侧栏右缘边线，与侧栏融为一体 */
.sidebar-collapse-handle {
  position: fixed;
  top: 50%;
  left: calc(var(--sidebar-edge, 272px) - 1px);
  transform: translateY(-50%);
  z-index: 20;
  display: flex;
  height: 44px;
  width: 22px;
  align-items: center;
  justify-content: center;
  border-radius: 0 var(--aicss-radius) var(--aicss-radius) 0;
  border: 1px solid var(--aicss-border);
  border-left: none;
  /* 不透明白底与侧栏同色，盖住被把手覆盖的那一段侧栏边线 */
  background: var(--aicss-surface);
  color: var(--aicss-muted);
  cursor: pointer;
  box-shadow: 2px 0 8px rgba(233, 30, 99, 0.08);
  transition:
    color 0.18s var(--aicss-ease),
    border-color 0.18s var(--aicss-ease),
    box-shadow 0.18s var(--aicss-ease);
  padding: 0;
}
.sidebar-collapse-handle::before {
  /* 悬停渐显层：从透明渐变到浅粉，箭头使用深粉保持对比 */
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  border-radius: 0 var(--aicss-radius) var(--aicss-radius) 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    color-mix(in srgb, var(--aicss-accent) 14%, transparent) 35%,
    color-mix(in srgb, var(--aicss-accent) 30%, white) 100%
  );
  opacity: 0;
  transition: opacity 0.18s var(--aicss-ease);
  pointer-events: none;
}
.sidebar-collapse-handle:hover::before {
  opacity: 1;
}
.sidebar-collapse-handle:hover {
  border-color: color-mix(in srgb, var(--aicss-accent) 40%, white);
  color: var(--aicss-accent-text);
  box-shadow: 2px 0 10px color-mix(in srgb, var(--aicss-accent) 20%, transparent);
}
.sidebar-collapse-handle:focus-visible {
  outline: 2px solid var(--aicss-accent-soft);
  outline-offset: 2px;
}

/* 移动端浮动菜单按钮 */
.mobile-menu-fab {
  position: fixed;
  left: 12px;
  bottom: 24px;
  z-index: 25;
  display: flex;
  height: 44px;
  width: 44px;
  align-items: center;
  justify-content: center;
  border-radius: var(--aicss-radius);
  background: var(--aicss-accent);
  color: #fff;
  box-shadow: var(--aicss-shadow-elevated);
  border: none;
  cursor: pointer;
  transition:
    background-color 0.18s var(--aicss-ease),
    transform 0.18s var(--aicss-ease);
}
.mobile-menu-fab:hover {
  background: var(--aicss-accent-text);
}
.mobile-menu-fab:active {
  transform: scale(0.94);
}
.mobile-menu-fab:focus-visible {
  outline: 2px solid var(--aicss-ring, var(--aicss-accent));
  outline-offset: 2px;
}

.sidebar-sider--mobile {
  box-shadow: 4px 0 24px rgba(233, 30, 99, 0.08);
}

.sidebar-mobile-scrim {
  position: fixed;
  inset: 0;
  z-index: 30;
  background: rgba(233, 30, 99, 0.2);
  -webkit-backdrop-filter: blur(2px);
  backdrop-filter: blur(2px);
}

.layout-content {
  will-change: margin-left;
  height: auto !important;
  flex: 1 1 0 !important;
  min-height: 0 !important;
}

/* 隐藏滚条 */
.scrollbar-hide::-webkit-scrollbar {
  display: none;
}

.scrollbar-hide {
  -ms-overflow-style: none;
  scrollbar-width: none;
}
</style>
