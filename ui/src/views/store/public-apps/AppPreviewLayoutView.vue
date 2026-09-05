<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { forkPublicApp, getPublicAppDetail, type PublicApp } from '@/services/public-app'
import { getErrorMessage } from '@/utils/error'
import { isCredentialLoggedIn } from '@/utils/auth'
import { AUTH_REQUIRED_EVENT } from '@/utils/request'
import { useCredentialStore } from '@/stores/credential'
import { formatTimestampShort } from '@/utils/time-formatter'

const route = useRoute()
const credentialStore = useCredentialStore()
const { t } = useI18n()
const loading = ref(false)
const forking = ref(false)
const isLoggedIn = computed(() => isCredentialLoggedIn(credentialStore.credential))
const openLoginModal = () => {
  if (typeof window === 'undefined') return
  window.dispatchEvent(
    new CustomEvent(AUTH_REQUIRED_EVENT, {
      detail: { redirect: route.fullPath },
    }),
  )
}
const normalizeIconUrl = (icon: string = '') => {
  if (!icon) return ''
  if (icon.startsWith('data:') || /^https?:\/\//.test(icon)) return icon
  const fallbackOrigin = globalThis.location?.origin ?? 'http://localhost'
  const apiUrl = new URL(import.meta.env.VITE_API_PREFIX || '/api', fallbackOrigin)
  const basePath = apiUrl.pathname.replace(/\/+$/, '')
  let path = icon.startsWith('/') ? icon : `/${icon}`

  if (path.startsWith('/api/') && !basePath.startsWith('/api')) {
    path = path.replace(/^\/api/, '')
  }

  if (basePath && basePath !== '/' && !path.startsWith(`${basePath}/`)) {
    if (path.startsWith('/api/')) {
      path = path.replace(/^\/api/, '')
    }
    return `${apiUrl.origin}${basePath}${path}`
  }

  return `${apiUrl.origin}${path}`
}
const appIconSrc = ref('')
const creatorAvatarSrc = ref('')
const appIconCandidates = ref<string[]>([])
const creatorAvatarCandidates = ref<string[]>([])
const appIconIndex = ref(0)
const creatorAvatarIndex = ref(0)
const getIconCandidates = (icon: string = '') => {
  const trimmed = String(icon || '').trim()
  if (!trimmed) return []

  const candidates = [trimmed]
  const normalized = normalizeIconUrl(trimmed)
  if (normalized && !candidates.includes(normalized)) {
    candidates.push(normalized)
  }

  if (trimmed.startsWith('/api/') && !candidates.includes(trimmed.slice(4))) {
    candidates.push(trimmed.slice(4))
  }

  return candidates
}
const onAppIconError = () => {
  appIconIndex.value += 1
  appIconSrc.value = appIconCandidates.value[appIconIndex.value] || ''
}
const onCreatorAvatarError = () => {
  creatorAvatarIndex.value += 1
  creatorAvatarSrc.value = creatorAvatarCandidates.value[creatorAvatarIndex.value] || ''
}
type PreviewApp = PublicApp & { draft_updated_at: number }
const app = ref<PreviewApp>({
  id: '',
  name: '',
  icon: '',
  description: '',
  tags: [],
  creator_name: '',
  creator_avatar: '',
  published_at: 0,
  created_at: 0,
  draft_updated_at: 0,
})

// 加载公共应用详情
const loadApp = async () => {
  try {
    loading.value = true
    const res = await getPublicAppDetail(String(route.params?.app_id))
    // 将 draft_app_config 数据合并到 app 对象中，这样 DetailView 可以直接使用
    app.value = {
      ...res.data,
      // 添加 draft_updated_at 字段，用于显示"已自动保存"时间
      draft_updated_at: res.data.updated_at || res.data.created_at,
    }
    appIconCandidates.value = getIconCandidates(res.data.icon)
    appIconIndex.value = 0
    appIconSrc.value = appIconCandidates.value[0] || ''

    creatorAvatarCandidates.value = getIconCandidates(res.data.creator_avatar)
    creatorAvatarIndex.value = 0
    creatorAvatarSrc.value = creatorAvatarCandidates.value[0] || ''
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('publicApps.preview.loadFailed')))
  } finally {
    loading.value = false
  }
}

const handleFork = async () => {
  if (!isLoggedIn.value) {
    openLoginModal()
    return
  }
  if (app.value.is_forked || forking.value) return
  forking.value = true
  try {
    await forkPublicApp(app.value.id)
    app.value.is_forked = true
    Message.success(t('publicApps.preview.addToSpaceSuccess', { name: app.value.name }))
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('publicApps.preview.actionFailed')))
  } finally {
    forking.value = false
  }
}

watch(
  () => app.value.icon,
  (icon) => {
    appIconCandidates.value = getIconCandidates(icon)
    appIconIndex.value = 0
    appIconSrc.value = appIconCandidates.value[0] || ''
  },
  { immediate: true },
)

watch(
  () => app.value.creator_avatar,
  (avatar) => {
    creatorAvatarCandidates.value = getIconCandidates(avatar)
    creatorAvatarIndex.value = 0
    creatorAvatarSrc.value = creatorAvatarCandidates.value[0] || ''
  },
  { immediate: true },
)

onMounted(async () => await loadApp())

watch(
  () => route.params?.app_id,
  async (newValue, oldValue) => {
    const newAppId = String(newValue ?? '').trim()
    const oldAppId = String(oldValue ?? '').trim()
    if (!newAppId || newAppId === oldAppId) return
    await loadApp()
  },
)
</script>

<template>
  <!-- 外层容器 -->
  <div class="flex flex-1 min-h-0 w-full flex-col overflow-hidden">
    <!-- 顶部导航 -->
    <div
      class="h-[77px] shrink-0 bg-surface-2 p-4 flex items-center justify-between relative border-b border-border-c"
    >
      <!-- 左侧应用信息 -->
      <div class="flex items-center gap-2">
        <!-- 回退按钮 -->
        <router-link :to="{ name: 'store-public-apps-list' }">
          <a-button size="mini">
            <template #icon>
              <icon-left />
            </template>
          </a-button>
        </router-link>
        <!-- 应用容器 -->
        <div class="flex items-center gap-3">
          <!-- 应用图标 -->
          <div class="h-10 w-10 overflow-hidden rounded-lg bg-surface-2 flex items-center justify-center">
              <img
                v-if="appIconSrc"
                :src="appIconSrc"
                class="h-full w-full object-cover"
                alt="app icon"
                @error="onAppIconError"
              />
            <icon-apps v-else />
          </div>
          <!-- 应用信息 -->
          <div class="flex flex-col justify-between h-[40px]">
            <a-skeleton-line v-if="loading" :widths="[100]" />
            <div v-else class="flex items-center gap-2">
              <div class="text-text-2 font-bold">{{ app.name }}</div>
              <a-tag color="arcoblue" size="small">{{ t('publicApps.preview.usageOnly') }}</a-tag>
            </div>
            <div v-if="loading" class="flex items-center gap-2">
              <a-skeleton-line :widths="[60]" :line-height="18" />
              <a-skeleton-line :widths="[60]" :line-height="18" />
              <a-skeleton-line :widths="[60]" :line-height="18" />
            </div>
            <div v-else class="flex items-center gap-2">
              <div class="h-5 w-5 overflow-hidden rounded-full bg-surface-2 flex items-center justify-center">
                <img
                  v-if="creatorAvatarSrc"
                  :src="creatorAvatarSrc"
                  class="h-full w-full object-cover"
                  alt="creator avatar"
                  @error="onCreatorAvatarError"
                />
                <icon-user v-else />
              </div>
              <div class="flex items-center h-[18px] text-xs text-muted">
                {{ app.creator_name }}
              </div>
              <a-tag size="small" class="rounded h-[18px] leading-[18px] bg-surface-2 text-muted">
                {{ t('publicApps.preview.publishedAt', { time: formatTimestampShort(app.published_at) }) }}
              </a-tag>
            </div>
          </div>
        </div>
      </div>

      <!-- 添加到我的应用 -->
      <a-button
        v-if="isLoggedIn"
        type="primary"
        size="small"
        :loading="forking"
        :disabled="Boolean(app.is_forked)"
        @click="handleFork"
      >
        {{ app.is_forked ? t('publicApps.preview.addedToSpace') : t('publicApps.preview.addToMySpace') }}
      </a-button>
    </div>
    <!-- 底部内容区 -->
    <div class="flex min-h-0 flex-1 overflow-hidden">
      <router-view :key="String(route.params?.app_id ?? '')" :app="app" />
    </div>
  </div>
</template>

<style scoped></style>
