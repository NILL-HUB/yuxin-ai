<script setup lang="ts">
/**
 * 我的应用 — 视觉对齐画布原型 my-apps.html。
 *
 * 数据来源：真实接口 listMyApps（管理员分配 + 商店添加）。
 * - 列表视图：粉调大圆角应用卡片网格 + 搜索过滤，点击「打开」进入内嵌对话
 * - 对话视图：真实流式聊天（chatWithMyApp），外观对齐原型胶囊气泡
 * - 来源徽标：分叉（商店添加）/ 分配（管理员分配）
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { listMyApps, chatWithMyApp } from '@/services/my-apps'
import type { MyApp } from '@/models/app-assignment'
import { getErrorMessage } from '@/utils/error'
import {
  applyChatStreamEvent,
  type RenderableStreamMessage,
  type StreamState,
} from '@/views/shared/chat-stream'
import { withChatRenderId } from '@/views/shared/chat-stream'

const { t } = useI18n()

const apps = ref<MyApp[]>([])
const loading = ref(false)
const searchKeyword = ref('')
const activeApp = ref<MyApp | null>(null)
const messages = ref<RenderableStreamMessage[]>([])
const query = ref('')
const sending = ref(false)
const streamState = ref<StreamState>({
  position: 0,
  message_id: '',
  task_id: '',
  conversation_id: '',
  billingEvents: [],
})
const bottomAnchorRef = ref<HTMLElement | null>(null)

/** 无图标时的图标底色：统一使用主题色渐变 */
const accentOf = () => 'linear-gradient(135deg, var(--aicss-accent), var(--aicss-accent-text))'

/** 无图标时取应用名首字展示 */
const firstChar = (name: string) => (name || '?').trim().charAt(0).toUpperCase()

const loadApps = async () => {
  loading.value = true
  try {
    const res = await listMyApps()
    apps.value = res.data?.list || []
  } catch (error: unknown) {
    apps.value = []
    Message.error(getErrorMessage(error, t('myApps.loadFailed')))
  } finally {
    loading.value = false
  }
}

/** 按名称/描述本地过滤 */
const filteredApps = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return apps.value
  return apps.value.filter(
    (app) =>
      app.name.toLowerCase().includes(kw) ||
      (app.description || '').toLowerCase().includes(kw),
  )
})

const sourceLabel = (app: MyApp) => {
  return app.source === 'forked' ? t('myApps.sourceForked') : t('myApps.sourceAssigned')
}

/** 原型：分叉 = 商店添加；分配 = 管理员分配 */
const isForked = (app: MyApp) => app.source === 'forked'

const openApp = (app: MyApp) => {
  activeApp.value = app
  messages.value = []
  streamState.value = {
    position: 0,
    message_id: '',
    task_id: '',
    conversation_id: '',
    billingEvents: [],
  }
  query.value = ''
}

const backToList = () => {
  activeApp.value = null
  messages.value = []
}

const send = async () => {
  const text = query.value.trim()
  if (!text || !activeApp.value || sending.value) return

  const humanMessage = withChatRenderId(
    {
      id: '',
      conversation_id: streamState.value.conversation_id,
      answer: '',
      answer_parts: [],
      artifacts: [],
      latency: 0,
      total_token_count: 0,
      agent_thoughts: [],
      query: text,
      image_urls: [],
    },
    'my-app',
  )
  messages.value.push(humanMessage)
  query.value = ''
  sending.value = true

  try {
    await chatWithMyApp(activeApp.value.id, {
      query: text,
      image_urls: [],
      conversation_id: streamState.value.conversation_id || '',
    }, (event_response) => {
      const current = messages.value[messages.value.length - 1]
      if (!current) return
      const result = applyChatStreamEvent(current, event_response, streamState.value)
      streamState.value = result.state
      if (result.didUpdate) {
        void nextTick(() => scrollToBottom())
      }
    })
  } catch (error: unknown) {
    Message.error(getErrorMessage(error, t('myApps.sendFailed')))
  } finally {
    sending.value = false
  }
}

const scrollToBottom = () => {
  bottomAnchorRef.value?.scrollIntoView({ behavior: 'smooth' })
}

onMounted(loadApps)
</script>

<template>
  <div class="my-apps-page relative h-full w-full overflow-y-auto">
    <!-- ===== 列表视图 ===== -->
    <div v-if="!activeApp" class="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
      <!-- 页头 -->
      <header class="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div class="min-w-0">
          <p class="my-apps-kicker text-xs font-medium uppercase tracking-widest text-brand">Workspace</p>
          <h1 class="my-apps-title mt-2 text-3xl font-semibold sm:text-4xl">{{ t('myApps.title') }}</h1>
          <p class="mt-3 max-w-xl text-[15px] leading-relaxed text-muted">{{ t('myApps.description') }}</p>
        </div>
        <!-- 搜索 -->
        <div class="relative w-full shrink-0 sm:w-72">
          <icon-search
            class="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
          />
          <input
            v-model="searchKeyword"
            type="search"
            :placeholder="t('common.actions.search')"
            :aria-label="t('common.actions.search')"
            class="my-apps-search w-full rounded-[var(--aicss-radius)] border border-border-strong bg-card py-3 pl-11 pr-4 text-sm text-text shadow-[var(--aicss-shadow-card)] outline-hidden transition placeholder:text-muted hover:border-brand-soft focus:border-brand focus:ring-2 focus:ring-brand-soft"
          />
        </div>
      </header>

      <!-- 卡片网格 -->
      <section aria-labelledby="my-apps-heading" class="mt-10">
        <div class="flex items-baseline justify-between gap-4">
          <h2 id="my-apps-heading" class="my-apps-subtitle text-xl font-semibold">{{ t('myApps.sectionTitle') }}</h2>
          <span class="text-sm text-muted">{{ t('myApps.countSuffix', { count: filteredApps.length }) }}</span>
        </div>

        <div v-if="loading" class="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          <div
            v-for="i in 6"
            :key="`skeleton-${i}`"
            class="animate-pulse rounded-[var(--aicss-radius)] border border-border-c bg-card p-6"
          >
            <div class="h-12 w-12 rounded-[var(--aicss-radius)] bg-surface-2"></div>
            <div class="mt-4 h-4 w-1/2 rounded bg-surface-2"></div>
            <div class="mt-3 h-3 w-3/4 rounded bg-surface-2"></div>
            <div class="mt-6 h-8 w-20 rounded-[var(--aicss-radius)] bg-surface-2"></div>
          </div>
        </div>

        <!-- 空态 -->
        <div
          v-else-if="filteredApps.length === 0"
          class="mt-6 flex flex-col items-center rounded-[var(--aicss-radius)] border-2 border-dashed border-brand-soft bg-surface-2/40 px-6 py-14 text-center"
        >
          <div class="flex h-12 w-12 items-center justify-center rounded-full bg-brand-soft text-brand-text">
            <icon-apps class="h-5 w-5" />
          </div>
          <p class="my-apps-subtitle mt-4 text-lg font-bold">
            {{ searchKeyword ? t('common.status.noRecord') : t('myApps.empty') }}
          </p>
        </div>

        <!-- 应用卡片 -->
        <div
          v-else
          id="my-apps-grid"
          class="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3"
        >
          <article
            v-for="app in filteredApps"
            :key="app.id"
            class="my-app-card group relative flex cursor-pointer flex-col rounded-[var(--aicss-radius)] border border-border-c bg-card p-6 shadow-[var(--aicss-shadow-card)] transition-all duration-300 hover:-translate-y-1 hover:border-brand-soft hover:shadow-[var(--aicss-shadow-elevated)] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-brand-soft"
            tabindex="0"
            role="link"
            @click="openApp(app)"
            @keydown.enter="openApp(app)"
          >
            <!-- 顶部：图标 + 来源徽标 -->
            <div class="flex items-start justify-between gap-4">
              <div
                class="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-[var(--aicss-radius)] text-white shadow-[var(--aicss-shadow-card)]"
                :style="{ background: accentOf() }"
              >
                <img
                  v-if="app.icon"
                  :src="app.icon"
                  :alt="app.name"
                  class="h-full w-full object-cover"
                />
                <span v-else class="my-app-letter text-lg font-semibold">{{ firstChar(app.name) }}</span>
              </div>
              <span
                class="inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium"
                :class="isForked(app) ? 'my-badge-fork' : 'my-badge-assign'"
              >
                <icon-branch v-if="isForked(app)" class="h-3 w-3" />
                <icon-user v-else class="h-3 w-3" />
                {{ sourceLabel(app) }}
              </span>
            </div>

            <h3 class="mt-4 truncate text-base font-semibold text-text">{{ app.name }}</h3>
            <p class="mt-1.5 line-clamp-2 text-sm leading-relaxed text-muted">
              {{ app.description || t('myApps.noDescription') }}
            </p>

            <!-- 状态徽标 -->
            <div class="mt-4">
              <span
                class="my-badge-published inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium"
              >
                <span class="h-1.5 w-1.5 rounded-full bg-current"></span>
                {{ t('myApps.published') }}
              </span>
            </div>

            <!-- 底部操作 -->
            <div
              class="mt-auto flex items-center justify-between gap-3 border-t border-border-c pt-5"
              style="margin-top: auto"
            >
              <span class="text-xs text-muted">{{ t('myApps.enterChatHint') }}</span>
              <span
                class="my-app-open inline-flex items-center gap-1.5 rounded-[var(--aicss-radius)] px-3.5 py-2 text-sm font-medium transition-colors"
              >
                {{ t('myApps.open') }}<icon-right class="h-3.5 w-3.5" />
              </span>
            </div>
          </article>
        </div>
      </section>

      <!-- 页脚 -->
      <footer class="mt-12 border-t border-border-c pt-6">
        <p class="text-xs text-muted">{{ t('myApps.footer') }}</p>
      </footer>
    </div>

    <!-- ===== 对话视图 ===== -->
    <div v-else class="flex h-full min-h-0 flex-col">
      <!-- 顶栏：返回 + 应用名 + 来源徽标 -->
      <div class="flex shrink-0 items-center gap-3 border-b border-border-c bg-surface px-4 py-2.5">
        <button
          type="button"
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--aicss-radius)] text-muted transition hover:bg-surface-2 hover:text-text"
          :aria-label="t('myApps.backToList')"
          :title="t('myApps.backToList')"
          @click="backToList"
        >
          <icon-left class="h-4 w-4" />
        </button>
        <div
          class="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-[var(--aicss-radius)] text-white"
          :style="{ background: accentOf() }"
        >
          <img v-if="activeApp.icon" :src="activeApp.icon" :alt="activeApp.name" class="h-full w-full object-cover" />
          <span v-else class="my-app-letter text-sm font-semibold">{{ firstChar(activeApp.name) }}</span>
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <span class="truncate text-sm font-semibold text-text">{{ activeApp.name }}</span>
            <span
              class="inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
              :class="isForked(activeApp) ? 'my-badge-fork' : 'my-badge-assign'"
            >
              {{ sourceLabel(activeApp) }}
            </span>
          </div>
        </div>
      </div>

      <!-- 消息流 -->
      <div class="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
        <div v-if="messages.length === 0" class="flex h-full items-center justify-center">
          <div class="text-center">
            <icon-message class="mx-auto h-10 w-10 text-brand-soft" />
            <p class="mt-3 text-sm text-muted">{{ t('myApps.chatEmpty') }}</p>
          </div>
        </div>
        <div v-else class="mx-auto w-full max-w-2xl space-y-5">
          <div v-for="item in messages" :key="item.render_id">
            <!-- 用户消息 -->
            <div v-if="item.query" class="flex justify-end">
              <p
                class="max-w-[78%] whitespace-pre-wrap rounded-[var(--aicss-radius)] bg-brand px-4 py-2.5 text-sm leading-relaxed text-white shadow-[var(--aicss-shadow-card)]"
              >
                {{ item.query }}
              </p>
            </div>
            <!-- AI 回复 -->
            <div v-if="item.answer" class="mt-2.5 flex justify-start gap-2.5">
              <span
                class="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-[var(--aicss-radius)] text-white"
                :style="{ background: accentOf() }"
              >
                <img v-if="activeApp.icon" :src="activeApp.icon" :alt="activeApp.name" class="h-full w-full object-cover" />
                <span v-else class="my-app-letter text-sm font-semibold">{{ firstChar(activeApp.name) }}</span>
              </span>
              <div class="min-w-0 max-w-[85%] rounded-[var(--aicss-radius)] border border-border-c bg-card px-4 py-2.5 text-sm leading-relaxed text-text shadow-[var(--aicss-shadow-card)]">
                <p class="whitespace-pre-wrap">{{ item.answer }}</p>
                <p class="mt-2 text-xs text-muted">{{ activeApp.name }} · {{ sourceLabel(activeApp) }}</p>
              </div>
            </div>
          </div>
        </div>
        <div ref="bottomAnchorRef" class="h-px w-full" />
      </div>

      <!-- 底部输入 -->
      <div class="flex shrink-0 items-center gap-2 border-t border-border-c bg-card px-4 py-3">
        <a-textarea
          v-model="query"
          :auto-size="{ minRows: 1, maxRows: 4 }"
          :placeholder="t('myApps.inputPlaceholder')"
          class="my-apps-input"
          @keydown.enter.exact.prevent="send"
        />
        <button
          type="button"
          class="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--aicss-radius)] bg-brand text-white shadow-[var(--aicss-shadow-card)] transition hover:-translate-y-0.5 hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="sending || !query.trim()"
          :aria-label="t('myApps.send')"
          @click="send"
        >
          <icon-send class="h-4 w-4" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.my-apps-page {
  height: 100%;
  background: var(--aicss-bg);
}

/* 滚动条微调 */
.my-apps-page::-webkit-scrollbar {
  width: 6px;
}
.my-apps-page::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: var(--aicss-border-strong);
}
.my-apps-page::-webkit-scrollbar-track {
  background: transparent;
}

/* 衬线标题族（对应原型 font-serif） */
.my-apps-kicker {
  font-family: var(--aicss-font-sans, inherit);
  letter-spacing: 0.14em;
}
.my-apps-title,
.my-apps-subtitle {
  font-family: 'Songti SC', 'SimSun', 'NSimSun', Georgia, serif;
  letter-spacing: -0.02em;
  color: var(--aicss-text);
}

/* 搜索框 */
.my-apps-search {
  color: var(--aicss-text);
  background: var(--aicss-card);
}
.my-apps-search:focus {
  border-color: var(--aicss-accent);
  box-shadow: 0 0 0 3px var(--aicss-accent-soft);
}

/* 应用卡片 */
.my-app-card {
  background: var(--aicss-card);
}

/* 图标块首字 */
.my-app-letter {
  font-family: Georgia, 'Songti SC', 'SimSun', serif;
  line-height: 1;
}

/* 来源徽标 */
.my-badge-fork {
  background: var(--aicss-accent-soft);
  color: var(--aicss-brand-text, var(--aicss-accent-text));
}
.my-badge-assign {
  background: var(--aicss-surface-2);
  color: var(--aicss-text-2);
}

/* 状态徽标 */
.my-badge-published {
  background: var(--aicss-accent-soft);
  color: var(--aicss-brand-text, var(--aicss-accent-text));
}

/* 打开按钮：hover 时反白为主粉 */
.my-app-open {
  background: var(--aicss-surface-2);
  color: var(--aicss-text-2);
  transition:
    background-color 0.18s var(--aicss-ease),
    color 0.18s var(--aicss-ease);
}
.my-app-card:hover .my-app-open {
  background: var(--aicss-accent);
  color: #fff;
}
</style>
