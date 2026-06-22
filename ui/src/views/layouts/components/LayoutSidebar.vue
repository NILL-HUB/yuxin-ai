<script setup lang="ts">
import type { RecentConversation } from '@/models/conversation'
import { useDeleteConversation, useGetRecentConversations } from '@/hooks/use-conversation'
import { useCredentialStore } from '@/stores/credential'
import { isCredentialLoggedIn } from '@/utils/auth'
import { getStoredAdminCredential, isAdminCredentialLoggedIn } from '@/utils/admin-auth'
import UpdateConversationNameModal from '@/views/layouts/components/UpdateConversationNameModal.vue'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import IconHomeFull from '@/components/icons/IconHomeFull.vue'
import IconHome from '@/components/icons/IconHome.vue'
import IconSpaceFull from '@/components/icons/IconSpaceFull.vue'
import IconSpace from '@/components/icons/IconSpace.vue'
import IconApps from '@/components/icons/IconApps.vue'

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
const isAdminLoggedIn = computed(() => isAdminCredentialLoggedIn(getStoredAdminCredential()))
const selectedConversationId = computed(() => String(route.query.conversation_id || '').trim())
const isHomeRootRoute = computed(() => route.path === '/home' && !selectedConversationId.value)
const currentAppId = computed(() => {
  if (!route.path.startsWith('/space/apps/')) return ''
  return String(route.params?.app_id || '').trim()
})
const {
  loading: getRecentConversationsLoading,
  conversations: recentConversations,
  loadRecentConversations: loadRecentConversationsHook,
} = useGetRecentConversations()
const { handleDeleteConversation } = useDeleteConversation()
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
    await router.push({
      path: `/space/apps/${conversation.app_id}`,
      query: {
        conversation_id: conversation.id,
        message_id: conversation.message_id,
      },
    })
  }
}

const handleHomeNavigation = async () => {
  if (!isLoggedIn.value) {
    await router.push('/home')
    return
  }

  await router.push('/home')
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
  handleDeleteConversation(conversation.id, async () => {
    recentConversations.value = recentConversations.value.filter(
      (item) => item.id !== conversation.id,
    )

    if (selectedConversationId.value === conversation.id) {
      if (conversation.source_type === 'assistant_agent') {
        await router.replace({ path: '/home' })
      } else if (conversation.source_type === 'public_app' && conversation.app_id) {
        await router.replace({ path: `/store/public-apps/${conversation.app_id}/preview` })
      } else if (conversation.source_type === 'app_debugger' && conversation.app_id) {
        await router.replace({ path: `/space/apps/${conversation.app_id}` })
      }
    }
    await loadRecentConversations()
  })
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
  <div class="flex flex-col h-full min-h-0 overflow-hidden">
    <!-- 导航菜单 -->
    <div
      :class="`flex flex-col gap-0.5 mt-2 flex-shrink-0 ${props.collapsed ? 'items-center' : ''}`"
    >
      <button
        type="button"
        data-testid="sidebar-home-new-conversation"
        :class="`flex items-center h-9 rounded-lg transition-all text-gray-700 hover:text-gray-900 hover:bg-gray-200 flex-shrink-0 ${props.collapsed ? 'justify-center w-9' : 'gap-2 px-2'} ${isHomeRootRoute ? 'bg-gray-100' : ''}`"
        :title="isHomeRootRoute ? t('layout.sidebar.home') : ''"
        @click="handleHomeNavigation"
      >
        <icon-home-full v-if="isHomeRootRoute" class="flex-shrink-0 w-4 h-4" />
        <icon-home v-else class="flex-shrink-0 w-4 h-4" />
        <span v-if="!props.collapsed" class="truncate text-sm">{{
          $t('layout.sidebar.home')
        }}</span>
      </button>
      <router-link
        v-if="isAdminLoggedIn"
        to="/admin/apps"
        :class="`flex items-center h-9 rounded-lg transition-all text-gray-700 hover:text-gray-900 hover:bg-gray-200 flex-shrink-0 ${props.collapsed ? 'justify-center w-9' : 'gap-2 px-2'} ${route.path.startsWith('/admin/apps') ? 'bg-gray-100' : ''}`"
        :title="route.path.startsWith('/admin/apps') ? t('layout.sidebar.resourceOrchestration') : ''"
      >
        <icon-space-full v-if="route.path.startsWith('/admin/apps')" class="flex-shrink-0 w-4 h-4" />
        <icon-space v-else class="flex-shrink-0 w-4 h-4" />
        <span v-if="!props.collapsed" class="truncate text-sm">
          {{ $t('layout.sidebar.resourceOrchestration') }}
        </span>
      </router-link>
      <router-link
        v-if="isAdminLoggedIn"
        to="/admin"
        :class="`flex items-center h-9 rounded-lg transition-all text-gray-700 hover:text-gray-900 hover:bg-gray-200 flex-shrink-0 ${props.collapsed ? 'justify-center w-9' : 'gap-2 px-2'} ${route.path.startsWith('/admin') ? 'bg-gray-100' : ''}`"
        :title="route.path.startsWith('/admin') ? t('layout.sidebar.adminConsole') : ''"
      >
        <icon-settings class="flex-shrink-0 w-4 h-4" />
        <span v-if="!props.collapsed" class="truncate text-sm">
          {{ $t('layout.sidebar.adminConsole') }}
        </span>
      </router-link>
      <router-link
        to="/search"
        :class="`flex items-center h-9 rounded-lg transition-all text-gray-700 hover:text-gray-900 hover:bg-gray-200 flex-shrink-0 ${props.collapsed ? 'justify-center w-9' : 'gap-2 px-2'} ${route.path === '/search' ? 'bg-gray-100' : ''}`"
        :title="route.path === '/search' ? t('layout.sidebar.search') : ''"
      >
        <icon-search class="flex-shrink-0 w-4 h-4" />
        <span v-if="!props.collapsed" class="truncate text-sm">
          {{ $t('layout.sidebar.search') }}
        </span>
      </router-link>
      <router-link
        to="/memory"
        :class="`flex items-center h-9 rounded-lg transition-all text-gray-700 hover:text-gray-900 hover:bg-gray-200 flex-shrink-0 ${props.collapsed ? 'justify-center w-9' : 'gap-2 px-2'} ${route.path.startsWith('/memory') ? 'bg-gray-100' : ''}`"
        :title="route.path.startsWith('/memory') ? t('layout.sidebar.memory') : ''"
      >
        <icon-bookmark class="flex-shrink-0 w-4 h-4" />
        <span v-if="!props.collapsed" class="truncate text-sm">
          {{ $t('layout.sidebar.memory') }}
        </span>
      </router-link>
      <router-link
        to="/my-knowledge"
        :class="`flex items-center h-9 rounded-lg transition-all text-gray-700 hover:text-gray-900 hover:bg-gray-200 flex-shrink-0 ${props.collapsed ? 'justify-center w-9' : 'gap-2 px-2'} ${route.path.startsWith('/my-knowledge') ? 'bg-gray-100' : ''}`"
        :title="route.path.startsWith('/my-knowledge') ? t('layout.sidebar.myKnowledge') : ''"
      >
        <icon-book class="flex-shrink-0 w-4 h-4" />
        <span v-if="!props.collapsed" class="truncate text-sm">
          {{ $t('layout.sidebar.myKnowledge') }}
        </span>
      </router-link>
      <router-link
        to="/external-data-sources"
        :class="`flex items-center h-9 rounded-lg transition-all text-gray-700 hover:text-gray-900 hover:bg-gray-200 flex-shrink-0 ${props.collapsed ? 'justify-center w-9' : 'gap-2 px-2'} ${route.path.startsWith('/external-data-sources') ? 'bg-gray-100' : ''}`"
        :title="route.path.startsWith('/external-data-sources') ? t('externalDataSource.title') : ''"
      >
        <icon-cloud class="flex-shrink-0 w-4 h-4" />
        <span v-if="!props.collapsed" class="truncate text-sm">
          {{ $t('externalDataSource.title') }}
        </span>
      </router-link>
      <router-link
        to="/showcase"
        :class="`flex items-center h-9 rounded-lg transition-all text-gray-700 hover:text-gray-900 hover:bg-gray-200 flex-shrink-0 ${props.collapsed ? 'justify-center w-9' : 'gap-2 px-2'} ${route.path.startsWith('/showcase') ? 'bg-gray-100' : ''}`"
        :title="route.path.startsWith('/showcase') ? t('layout.sidebar.showcase') : ''"
      >
        <icon-image class="flex-shrink-0 w-4 h-4" />
        <span v-if="!props.collapsed" class="truncate text-sm">
          {{ $t('layout.sidebar.showcase') }}
        </span>
      </router-link>
    </div>

    <!-- 最近对话区域 - 可滚动 -->
    <div v-if="isLoggedIn" class="flex flex-col flex-1 min-h-0 overflow-hidden">
      <!-- 侧边栏展开时显示完整列表 -->
      <div
        v-if="!props.collapsed"
        class="mt-2 pt-2 flex items-center gap-2 px-2 mb-1 flex-shrink-0"
      >
        <div class="text-sm font-bold text-gray-700">
          {{ $t('layout.sidebar.recentConversations') }}
        </div>
        <div class="flex-1 h-px bg-gray-200"></div>
      </div>

      <!-- 最近对话列表 - 只在展开时显示，固定高度可滚动 -->
      <div
        v-if="!props.collapsed"
        class="flex-1 min-h-0 overflow-y-auto pr-1 recent-conversation-list"
        @scroll.passive="handleRecentConversationsScroll"
      >
        <div v-if="recentConversations.length === 0" class="text-xs text-gray-400 px-2 py-1">
          {{ $t('layout.sidebar.noRecentConversations') }}
        </div>
        <div v-else class="flex flex-col gap-0.5">
          <div
            v-for="conversation in recentConversations"
            :key="conversation.id"
            :class="`group flex items-center gap-1 h-8 leading-8 pl-2 pr-1 text-gray-700 rounded-lg cursor-pointer ${isConversationActive(conversation) ? 'bg-blue-50 !text-blue-700' : ''} hover:bg-blue-50 hover:text-blue-700`"
            @click="() => changeConversation(conversation)"
          >
            <div class="flex-1 min-w-0 flex items-center gap-1.5">
              <icon-message
                v-if="conversation.source_type === 'assistant_agent'"
                class="text-gray-400 group-hover:text-current flex-shrink-0"
              />
              <icon-apps v-else class="text-gray-400 group-hover:text-current flex-shrink-0" />
              <div class="flex-1 line-clamp-1 break-all">{{ conversation.name }}</div>
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
      </div>

      <!-- 侧边栏收缩时显示按钮组 - 最近对话按钮与搜索按钮和折叠按钮保持相同间距 -->
      <div
        v-if="props.collapsed"
        class="flex flex-col gap-0.5 items-center px-2 flex-shrink-0 mt-2"
      >
        <!-- 最近对话按钮 -->
        <div
          class="flex items-center justify-center w-7 h-7 rounded-lg cursor-pointer transition-all duration-200 text-blue-600 hover:text-blue-700 hover:bg-blue-50 group flex-shrink-0"
          @mouseenter="handleRecentConversationsHover"
          @mouseleave="handleRecentConversationsLeave"
          :title="
            t('layout.sidebar.recentConversationsCount', { count: recentConversations.length })
          "
        >
          <div class="relative w-4 h-4 flex items-center justify-center flex-shrink-0">
            <svg
              class="w-4 h-4 flex-shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <!-- 数量徽章 - 只在 hover 时显示 -->
            <div
              v-if="recentConversations.length > 0"
              class="absolute -top-2 -right-2 min-w-5 h-5 bg-blue-200 text-blue-700 text-xs rounded-full flex items-center justify-center font-bold px-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex-shrink-0"
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
  </div>
</template>

<style scoped>
.recent-conversation-list {
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.recent-conversation-list::-webkit-scrollbar {
  width: 0;
  height: 0;
}
</style>
