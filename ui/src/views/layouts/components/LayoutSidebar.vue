<script setup lang="ts">
import type { RecentConversation } from '@/models/conversation'
import { useDeleteConversation, useGetRecentConversations } from '@/hooks/use-conversation'
import { useCredentialStore } from '@/stores/credential'
import { isCredentialLoggedIn } from '@/utils/auth'
import UpdateConversationNameModal from '@/views/layouts/components/UpdateConversationNameModal.vue'
import UserRecycleBinDeleteModal from '@/components/recycle-bin/UserRecycleBinDeleteModal.vue'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { buildHomeNewConversationQuery } from '@/views/pages/home-new-conversation'

interface Props {
  collapsed?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  collapsed: false,
})
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const credentialStore = useCredentialStore()
const isLoggedIn = computed(() => isCredentialLoggedIn(credentialStore.credential))
const selectedConversationId = computed(() => String(route.query.conversation_id || '').trim())
const isNewConversationRoute = computed(() => route.path === '/home' && !selectedConversationId.value)
const currentAppId = computed(() => {
  if (!route.path.startsWith('/space/apps/')) return ''
  return String(route.params?.app_id || '').trim()
})
type SidebarNavItem = {
  key: string
  label: string
  to: string
  icon: string
  active: boolean
}
type SidebarNavSection = {
  key: string
  label: string
  items: SidebarNavItem[]
}
const navSections = computed<SidebarNavSection[]>(() => [
  {
    key: 'workspace',
    label: t('layout.sidebar.workspace'),
    items: [
      {
        key: 'search',
        label: t('layout.sidebar.search'),
        to: '/search',
        icon: 'icon-search',
        active: route.path === '/search',
      },
      {
        key: 'memory',
        label: t('layout.sidebar.memory'),
        to: '/memory',
        icon: 'icon-bookmark',
        active: route.path.startsWith('/memory'),
      },
      {
        key: 'my-knowledge',
        label: t('layout.sidebar.myKnowledge'),
        to: '/my-knowledge',
        icon: 'icon-book',
        active: route.path.startsWith('/my-knowledge'),
      },
      {
        key: 'my-apps',
        label: t('layout.sidebar.myApps'),
        to: '/my-apps',
        icon: 'icon-apps',
        active: route.path.startsWith('/my-apps'),
      },
      {
        key: 'recycle-bin',
        label: t('layout.sidebar.recycleBin'),
        to: '/recycle-bin',
        icon: 'icon-delete',
        active: route.path.startsWith('/recycle-bin'),
      },
    ],
  },
  {
    key: 'services',
    label: t('layout.sidebar.services'),
    items: [
      {
        key: 'schedules',
        label: t('layout.sidebar.schedules'),
        to: '/schedules',
        icon: 'icon-schedule',
        active: route.path.startsWith('/schedules'),
      },
      {
        key: 'membership',
        label: t('layout.sidebar.membership'),
        to: '/membership',
        icon: 'icon-user',
        active: route.path.startsWith('/membership'),
      },
      {
        key: 'studio',
        label: t('layout.sidebar.studio'),
        to: '/studio',
        icon: 'icon-edit',
        active: route.path.startsWith('/studio'),
      },
      {
        key: 'store',
        label: t('layout.sidebar.store'),
        to: '/store/public-apps',
        icon: 'icon-apps',
        active: route.path.startsWith('/store'),
      },
    ],
  },
])

const navItemClass = (item: SidebarNavItem) => {
  const base = 'group relative flex h-9 items-center rounded-[var(--aicss-radius)] text-sm transition-all duration-200 shrink-0'
  const size = props.collapsed ? 'justify-center w-9' : 'gap-2.5 px-2.5'
  const state = item.active
    ? 'bg-brand-soft text-brand-text'
    : 'text-muted hover:bg-surface-2 hover:text-text'
  return `${base} ${size} ${state}`
}

const {
  loading: getRecentConversationsLoading,
  conversations: recentConversations,
  loadRecentConversations: loadRecentConversationsHook,
} = useGetRecentConversations()
const {
  deleteTarget: conversationDeleteTarget,
  deleteLoading: conversationDeleteLoading,
  handleDeleteConversation,
  confirmDeleteConversation,
} = useDeleteConversation()
const updateConversationNameVisible = ref(false)
const updateConversationNameId = ref('')
const updateConversationName = ref('')
const DEFAULT_RECENT_CONVERSATIONS_LIMIT = 20
const RECENT_CONVERSATIONS_LOAD_STEP = 20
const MAX_RECENT_CONVERSATIONS_LIMIT = 1000
const recentConversationsLimit = ref(DEFAULT_RECENT_CONVERSATIONS_LIMIT)
const hasMoreRecentConversations = ref(true)
const recentConversationsBottomLocked = ref(false)

// 2.定义加载最近会话列表函数
const loadRecentConversations = async (reset = false) => {
  if (!isLoggedIn.value) {
    recentConversations.value = []
    recentConversationsLimit.value = DEFAULT_RECENT_CONVERSATIONS_LIMIT
    hasMoreRecentConversations.value = true
    recentConversationsBottomLocked.value = false
    return
  }

  if (reset) {
    recentConversationsLimit.value = DEFAULT_RECENT_CONVERSATIONS_LIMIT
    hasMoreRecentConversations.value = true
    recentConversationsBottomLocked.value = false
  }

  const limit = Math.min(recentConversationsLimit.value, MAX_RECENT_CONVERSATIONS_LIMIT)
  recentConversationsLimit.value = limit
  await loadRecentConversationsHook(limit)
  hasMoreRecentConversations.value =
    limit < MAX_RECENT_CONVERSATIONS_LIMIT && recentConversations.value.length >= limit
  if (!hasMoreRecentConversations.value) {
    recentConversationsBottomLocked.value = false
  }
}

const loadMoreRecentConversations = async () => {
  if (
    getRecentConversationsLoading.value ||
    !hasMoreRecentConversations.value ||
    recentConversationsBottomLocked.value
  ) {
    return
  }
  recentConversationsBottomLocked.value = true
  const previousLimit = recentConversationsLimit.value
  const nextLimit = Math.min(
    previousLimit + RECENT_CONVERSATIONS_LOAD_STEP,
    MAX_RECENT_CONVERSATIONS_LIMIT,
  )
  if (nextLimit === recentConversationsLimit.value) {
    hasMoreRecentConversations.value = false
    recentConversationsBottomLocked.value = false
    return
  }
  recentConversationsLimit.value = nextLimit
  try {
    await loadRecentConversations(false)
    if (!hasMoreRecentConversations.value) {
      recentConversationsBottomLocked.value = false
    }
  } catch (error) {
    recentConversationsLimit.value = previousLimit
    recentConversationsBottomLocked.value = false
    console.error('Failed to load more recent conversations:', error)
  }
}

// 3.定义会话点击切换函数
const changeConversation = async (conversation: RecentConversation) => {
  if (!conversation.id) return

  if (conversation.invoke_from === 'schedule') {
    Message.info(t('chat.schedules.conversationNotOpenable'))
    return
  }

  if (conversation.source_type === 'assistant_agent') {
    await router.push({
      path: '/home',
      query: { conversation_id: conversation.id },
    })
    return
  }

  if (conversation.source_type === 'public_app' && conversation.app_id) {
    await router.push({
      path: `/store/public-apps/${conversation.app_id}/preview`,
      query: {
        conversation_id: conversation.id,
        message_id: conversation.message_id,
      },
    })
    return
  }

  if (conversation.source_type === 'app_debugger' && conversation.app_id) {
    Message.info(t('chat.schedules.conversationNotOpenable'))
    return
  }
}

const handleNewConversationNavigation = async () => {
  if (!isLoggedIn.value) {
    await router.push('/home')
    return
  }

  await router.push({
    path: '/home',
    query: buildHomeNewConversationQuery(),
  })
}

const isConversationActive = (conversation: RecentConversation) => {
  const currentConversationId = selectedConversationId.value
  if (!currentConversationId) return false
  if (currentConversationId !== conversation.id) return false

  if (route.path.startsWith('/home')) {
    return conversation.source_type === 'assistant_agent'
  }

  if (currentAppId.value) {
    return conversation.source_type === 'app_debugger' && conversation.app_id === currentAppId.value
  }

  if (route.path.startsWith('/store/public-apps/')) {
    return (
      conversation.source_type === 'public_app' &&
      conversation.app_id === String(route.params?.app_id || '').trim()
    )
  }

  return false
}

// 4.定义打开重命名会话弹窗函数
const openUpdateNameModal = (conversation: RecentConversation) => {
  updateConversationNameId.value = conversation.id
  updateConversationName.value = conversation.name
  updateConversationNameVisible.value = true
}

// 5.定义重命名成功回调函数
const updateConversationNameSuccess = (conversation_id: string, name: string) => {
  const idx = recentConversations.value.findIndex((item) => item.id === conversation_id)
  if (idx !== -1) {
    recentConversations.value[idx].name = name
  }
}

// 6.定义删除会话函数
const deleteRecentConversation = (conversation: RecentConversation) => {
  handleDeleteConversation(
    conversation.id,
    async () => {
      recentConversations.value = recentConversations.value.filter(
        (item) => item.id !== conversation.id,
      )

      if (selectedConversationId.value === conversation.id) {
        if (conversation.source_type === 'assistant_agent') {
          await router.replace({ path: '/home' })
        } else if (conversation.source_type === 'public_app' && conversation.app_id) {
          await router.replace({ path: `/store/public-apps/${conversation.app_id}/preview` })
        } else if (conversation.source_type === 'app_debugger' && conversation.app_id) {
          await router.replace({ path: '/home' })
        }
      }
      await loadRecentConversations()
    },
    conversation.name,
  )
}

const handleRecentConversationsRefresh = () => {
  void loadRecentConversations()
}

const handleRecentConversationsScroll = (event: Event) => {
  const target = event.target as HTMLElement | null
  if (!target) return
  const reachedBottom = target.scrollTop + target.clientHeight >= target.scrollHeight - 12
  if (!reachedBottom) {
    recentConversationsBottomLocked.value = false
    return
  }
  void loadMoreRecentConversations()
}

/** 统一滚动容器：仅展开态下滚到底时加载更多最近对话 */
const onSidebarScroll = (event: Event) => {
  if (props.collapsed) return
  if (!isLoggedIn.value) return
  handleRecentConversationsScroll(event)
}

// 处理最近对话按钮 hover
const handleRecentConversationsHover = (event: MouseEvent) => {
  const target = event.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()

  // 触发全局事件，传递按钮位置和数据
  window.dispatchEvent(
    new CustomEvent('recent-conversations:show', {
      detail: {
        conversations: recentConversations.value,
        loading: getRecentConversationsLoading.value,
        triggerRect: {
          top: rect.top,
          left: rect.left,
          right: rect.right,
          bottom: rect.bottom,
          width: rect.width,
          height: rect.height,
        },
      },
    }),
  )
}

const handleRecentConversationsLeave = () => {
  // 按钮离开时不立即隐藏，让 Popover 自己决定
}

watch(
  () => isLoggedIn.value,
  async (loggedIn) => {
    if (!loggedIn) {
      recentConversations.value = []
      recentConversationsLimit.value = DEFAULT_RECENT_CONVERSATIONS_LIMIT
      hasMoreRecentConversations.value = true
      recentConversationsBottomLocked.value = false
      return
    }
    await loadRecentConversations(true)
  },
  { immediate: true },
)

onMounted(() => {
  if (typeof window === 'undefined') return
  window.addEventListener('recent-conversations:refresh', handleRecentConversationsRefresh)
})

onUnmounted(() => {
  if (typeof window === 'undefined') return
  window.removeEventListener('recent-conversations:refresh', handleRecentConversationsRefresh)
})
</script>

<template>
  <!-- 整个侧边栏内容（菜单 + 最近对话）统一放进一个滚动容器，
       展开与收起状态均支持下滑查看全部内容，不与底部账号卡互相挤压 -->
  <div
    class="sidebar-scroll h-full min-h-0 w-full overflow-y-auto"
    :class="{ 'px-1': props.collapsed }"
    @scroll.passive="onSidebarScroll"
  >
    <!-- 新建对话按钮 -->
    <div
      :class="`flex flex-col shrink-0 ${props.collapsed ? 'items-center' : ''}`"
    >
      <button
        type="button"
        data-testid="sidebar-new-conversation"
        :class="`group relative flex h-10 items-center rounded-[var(--aicss-radius)] transition-all duration-200 shrink-0 shadow-[var(--aicss-shadow-card)] ${props.collapsed ? 'justify-center w-9' : 'gap-2.5 px-2.5'} ${isNewConversationRoute ? 'bg-brand text-white ring-2 ring-brand-soft' : 'bg-brand text-white hover:bg-brand-hover'}`"
        :title="t('layout.sidebar.newConversation')"
        @click="handleNewConversationNavigation"
      >
        <span class="grid h-6 w-6 place-items-center rounded-[var(--aicss-radius)] bg-white/15">
          <icon-plus class="shrink-0 w-4 h-4" />
        </span>
        <span v-if="!props.collapsed" class="truncate text-sm font-medium">
          {{ $t('layout.sidebar.newConversation') }}
        </span>
      </button>

      <template v-for="section in navSections" :key="section.key">
        <div
          v-if="!props.collapsed"
          class="mt-3 px-2.5 text-[11px] font-semibold tracking-wide text-subtle"
        >
          {{ section.label }}
        </div>
        <div :class="`flex flex-col gap-0.5 ${props.collapsed ? 'items-center mt-2' : 'mt-1'}`">
          <router-link
            v-for="item in section.items"
            :key="item.key"
            :to="item.to"
            :class="navItemClass(item)"
            :title="item.label"
          >
            <component :is="item.icon" class="shrink-0 w-4 h-4" />
            <span v-if="!props.collapsed" class="truncate text-sm">
              {{ item.label }}
            </span>
          </router-link>
        </div>
      </template>
    </div>

    <!-- 最近对话区域 -->
    <div v-if="isLoggedIn" class="flex flex-col">
      <!-- 展开态：标题 + 列表 -->
      <template v-if="!props.collapsed">
        <div class="mt-4 pt-3 flex items-center gap-1.5 px-1 mb-1 shrink-0 border-t border-border-c">
          <icon-history class="w-3.5 h-3.5 text-subtle shrink-0" />
          <div class="text-xs font-semibold tracking-wide text-subtle">
            {{ $t('layout.sidebar.recentConversations') }}
          </div>
          <div class="flex-1 h-px bg-surface-2"></div>
        </div>

        <div v-if="recentConversations.length === 0" class="text-xs text-subtle px-2 py-1">
          {{ $t('layout.sidebar.noRecentConversations') }}
        </div>
        <div v-else class="flex flex-col gap-0.5 pb-2">
          <div
            v-for="conversation in recentConversations"
            :key="conversation.id"
            :class="`group flex items-center gap-1 h-8 leading-8 pl-2 pr-1 text-text-2 rounded-[var(--aicss-radius)] cursor-pointer ${isConversationActive(conversation) ? 'bg-brand-soft !text-brand-text' : ''} hover:bg-brand-soft hover:text-brand-text`"
            @click="() => changeConversation(conversation)"
          >
            <div class="flex-1 min-w-0 flex items-center gap-1.5">
              <icon-schedule
                v-if="conversation.invoke_from === 'schedule'"
                class="text-orange-400 group-hover:text-current shrink-0"
              />
              <icon-message
                v-else-if="conversation.source_type === 'assistant_agent'"
                class="text-subtle group-hover:text-current shrink-0"
              />
              <icon-apps v-else class="text-subtle group-hover:text-current shrink-0" />
              <div class="flex-1 line-clamp-1 break-all">{{ conversation.name }}</div>
              <a-tag
                v-if="conversation.invoke_from === 'schedule'"
                size="small"
                color="orange"
                class="shrink-0 !mr-0"
              >
                {{ t('chat.schedules.shortLabel') }}
              </a-tag>
            </div>
            <a-dropdown position="br">
              <a-button
                size="mini"
                type="text"
                class="!text-inherit !bg-transparent invisible group-hover:visible"
                @click.stop
              >
                <template #icon>
                  <icon-more />
                </template>
              </a-button>
              <template #content>
                <a-doption @click.stop="() => openUpdateNameModal(conversation)">
                  <template #icon>
                    <icon-edit />
                  </template>
                  {{ $t('common.actions.rename') }}
                </a-doption>
                <a-doption
                  class="text-red-700"
                  @click.stop="() => deleteRecentConversation(conversation)"
                >
                  <template #icon>
                    <icon-delete />
                  </template>
                  {{ $t('common.actions.deleteConversation') }}
                </a-doption>
              </template>
            </a-dropdown>
          </div>
        </div>
      </template>

      <!-- 收起态：最近对话按钮（仅图标） -->
      <div
        v-else
        class="flex flex-col gap-0.5 items-center px-2 shrink-0 mt-3"
      >
        <!-- 最近对话按钮 -->
        <div
          class="flex items-center justify-center w-7 h-7 rounded-[var(--aicss-radius)] cursor-pointer transition-all duration-200 text-brand-text hover:text-brand-text hover:bg-brand-soft group shrink-0"
          @mouseenter="handleRecentConversationsHover"
          @mouseleave="handleRecentConversationsLeave"
          :title="
            t('layout.sidebar.recentConversationsCount', { count: recentConversations.length })
          "
        >
          <div class="relative w-4 h-4 flex items-center justify-center shrink-0">
            <icon-history class="w-4 h-4 shrink-0" />
            <!-- 数量徽章 - 只在 hover 时显示 -->
            <div
              v-if="recentConversations.length > 0"
              class="absolute -top-2 -right-2 min-w-5 h-5 bg-brand-soft text-brand-text text-xs rounded-full flex items-center justify-center font-bold px-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200 shrink-0"
            >
              {{ recentConversations.length }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <update-conversation-name-modal
      v-model:visible="updateConversationNameVisible"
      :conversation_id="updateConversationNameId"
      :conversation_name="updateConversationName"
      @saved="updateConversationNameSuccess"
    />
    <user-recycle-bin-delete-modal
      :visible="conversationDeleteTarget !== null"
      :title="t('common.actions.deleteConversation')"
      :resource-name="conversationDeleteTarget?.name"
      :loading="conversationDeleteLoading"
      :hint="t('userRecycleBin.deleteHint')"
      @update:visible="(v) => !v && (conversationDeleteTarget = null)"
      @confirm="confirmDeleteConversation"
    />
  </div>
</template>

<style scoped>
/* 导航滚动区：隐藏滚动条 */
.sidebar-scroll {
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.sidebar-scroll::-webkit-scrollbar {
  width: 0;
  height: 0;
}
</style>
