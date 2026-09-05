<script setup lang="ts">
/**
 * 会话搜索 — 对齐画布原型 search.html 的独立翻新页。
 *
 * 数据源：真实接口。
 * - 关键词搜索：/conversations/search（searchConversations）
 * - 空关键词：最近会话 /conversations/recent（useGetRecentConversations）
 * - 重命名：/conversations/:id/name（UpdateConversationNameModal）
 * - 删除：/conversations/:id/delete（useDeleteConversation + 回收站留存规则）
 *
 * 视觉结构保留原型：粉调大圆角卡片、衬线标题、粉色关键词高亮、
 * hover 操作、定时/应用/Agent 徽标、空态。
 */
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import UpdateConversationNameModal from '@/views/layouts/components/UpdateConversationNameModal.vue'
import UserRecycleBinDeleteModal from '@/components/recycle-bin/UserRecycleBinDeleteModal.vue'
import { searchConversations, type SearchConversation } from '@/services/conversation-search'
import { useGetRecentConversations, useDeleteConversation } from '@/hooks/use-conversation'
import type { RecentConversation } from '@/models/conversation'

/** 模板视图对象：将接口 snake_case 项映射为模板需要的形状 */
type ViewConversation = {
  id: string
  name: string
  appName?: string
  agentName?: string
  isSchedule?: boolean
  matchedFields: string[]
  question?: string
  answer?: string
  updatedAt: string
  /** 真实跳转所需原信息 */
  sourceType?: string
  invokeFrom?: string
  appId?: string
  messageId?: string
  /** 真实接口搜索结果的原始标记 */
  matchFields: string[]
}

const router = useRouter()
const { t } = useI18n()

const searchQuery = ref('')
const loading = ref(false)
const searchResults = ref<ViewConversation[]>([])
const recentConversationsView = ref<ViewConversation[]>([])

const updateConversationNameVisible = ref(false)
const updateConversationNameId = ref('')
const updateConversationName = ref('')

// 删除弹窗
const deleteVisible = ref(false)
const deleteName = ref('')
const deleteLoading = ref(false)
const pendingDelete = ref<ViewConversation | null>(null)

const {
  loading: recentLoading,
  conversations: recentConversations,
  loadRecentConversations: loadRecent,
} = useGetRecentConversations()

const {
  deleteTarget: hookDeleteTarget,
  deleteLoading: hookDeleteLoading,
  handleDeleteConversation,
  confirmDeleteConversation,
} = useDeleteConversation()

watch(
  hookDeleteTarget,
  (v) => {
    deleteVisible.value = v !== null
    if (v) {
      deleteName.value = v.name
      pendingDelete.value = {
        id: v.id,
        name: v.name,
        matchedFields: [],
        matchFields: [],
        updatedAt: '',
        sourceType: 'assistant_agent',
      }
    } else {
      pendingDelete.value = null
    }
  },
  { immediate: true },
)

watch(hookDeleteLoading, (v) => {
  deleteLoading.value = v
})

/** 接口会话 → 视图对象 */
const mapToView = (item: SearchConversation | RecentConversation): ViewConversation => {
  const sourceType = item.source_type
  const isSchedule = sourceType === 'schedule' || item.invoke_from === 'schedule'
  const fields: string[] = []
  const src = item as SearchConversation
  if (Array.isArray(src.matched_fields)) {
    src.matched_fields.forEach((f) => {
      fields.push(f === 'human_message' ? 'message' : f === 'app_name' ? 'app' : f === 'agent_name' ? 'agent' : f)
    })
  }
  const v: ViewConversation = {
    id: item.id,
    name: item.name,
    appName: item.app_name || undefined,
    agentName: item.agent_name || undefined,
    isSchedule,
    matchedFields: fields,
    matchFields: fields,
    question: src.human_message || undefined,
    answer: src.ai_message || undefined,
    updatedAt: formatShortDate(item.latest_message_at ?? item.created_at),
    sourceType,
    invokeFrom: item.invoke_from,
    appId: item.app_id || undefined,
    messageId: (item as SearchConversation).message_id || undefined,
  }
  return v
}

/** 仅保留时间部分（yyyy-mm-dd），给卡片标题右侧/正文展示 */
const formatShortDate = (ts: number | undefined) => {
  if (!ts) return ''
  const ms = ts < 10000000000 ? ts * 1000 : ts
  const d = new Date(ms)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${mm}-${dd}`
}

const listForView = (list: RecentConversation[]) => list.map(mapToView)

// 最近会话 hook 数据变化 → 视图列表
watch(
  () => recentConversations.value.length,
  () => {
    recentConversationsView.value = listForView(recentConversations.value)
  },
  { immediate: true },
)

const normalizedQuery = computed(() => searchQuery.value.trim().toLowerCase())

/** 展示列表：有关键词时展示搜索结果；否则展示最近会话 */
const filteredConversations = computed<ViewConversation[]>(() => {
  const q = normalizedQuery.value
  if (q) {
    return searchResults.value
  }
  return recentConversationsView.value
})

const hasResult = computed(() => filteredConversations.value.length > 0)

/** 输入防抖搜索真实接口 */
let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(searchQuery, (q) => {
  if (searchTimer) clearTimeout(searchTimer)
  const keyword = q.trim()
  if (!keyword) {
    searchResults.value = []
    return
  }
  loading.value = true
  searchTimer = setTimeout(async () => {
    try {
      const resp = await searchConversations(keyword, 100)
      const data = resp.data || []
      searchResults.value = data.map(mapToView)
    } catch {
      searchResults.value = []
    } finally {
      loading.value = false
    }
  }, 300)
})

// ---------- 高亮 ----------
const escapeHtml = (text: string) =>
  String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')

const escapeRegExp = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const highlightText = (text: string) => {
  const safeText = escapeHtml(text)
  const keyword = searchQuery.value.trim()
  if (!keyword) return safeText
  const regex = new RegExp(`(${escapeRegExp(keyword)})`, 'gi')
  return safeText.replace(regex, '<mark class="search-hit">$1</mark>')
}

const highlightTitle = (name: string) => {
  const keyword = normalizedQuery.value
  if (!keyword) return escapeHtml(name)
  const index = name.toLowerCase().indexOf(keyword)
  if (index === -1) return escapeHtml(name)
  const start = Math.max(0, index - 8)
  const prefix = start > 0 ? '…' : ''
  const clipped = name.slice(start, index + name.length)
  return `${prefix}${highlightText(clipped)}`
}

const snippetAround = (text: string, maxLen = 60) => {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim()
  if (!normalized) return ''
  const keyword = normalizedQuery.value
  if (!keyword) {
    return normalized.length > maxLen ? `${normalized.slice(0, maxLen)}…` : normalized
  }
  const index = normalized.toLowerCase().indexOf(keyword)
  if (index === -1) {
    return normalized.length > maxLen ? `${normalized.slice(0, maxLen)}…` : normalized
  }
  let start = Math.max(0, index - Math.floor((maxLen - keyword.length) / 2))
  const end = Math.min(normalized.length, start + maxLen)
  if (end - start < maxLen) start = Math.max(0, end - maxLen)
  const prefix = start > 0 ? '…' : ''
  const suffix = end < normalized.length ? '…' : ''
  return `${prefix}${highlightText(normalized.slice(start, end))}${suffix}`
}

const hasMessageMatch = (fields: string[]) =>
  fields.includes('message') || fields.includes('human_message') || fields.includes('ai_message')

const matchedMessage = (conv: ViewConversation) => {
  if (hasMessageMatch(conv.matchFields)) return true
  const q = normalizedQuery.value
  return !!(q && (conv.question?.toLowerCase().includes(q) || conv.answer?.toLowerCase().includes(q)))
}

const matchLabels = (conv: ViewConversation): string[] => {
  const labels: string[] = []
  const fields = conv.matchFields
  if (fields.includes('name') || fields.includes('title')) {
    labels.push(t('conversationSearch.matchedLabels.title'))
  }
  if (fields.includes('app')) labels.push(t('conversationSearch.matchedLabels.app'))
  if (fields.includes('agent')) {
    labels.push(t('conversationSearch.matchedLabels.agent', { name: conv.agentName || '' }))
  }
  return labels
}

const hasOtherMatches = (conv: ViewConversation) =>
  !matchedMessage(conv) && matchLabels(conv).length > 0

// ---------- 跳转 ----------
const openConversation = (conv: ViewConversation) => {
  if (!conv.id) return
  if (conv.invokeFrom === 'schedule' || conv.isSchedule || conv.sourceType === 'schedule') {
    // 定时任务会话不可从普通会话页打开
    return
  }
  if (conv.sourceType === 'assistant_agent') {
    void router.push({ path: '/home', query: { conversation_id: conv.id } })
    return
  }
  if (conv.sourceType === 'public_app' && conv.appId) {
    void router.push({
      path: `/store/public-apps/${conv.appId}/preview`,
      query: { conversation_id: conv.id, message_id: conv.messageId || undefined },
    })
    return
  }
  if (conv.sourceType === 'app_debugger') {
    // 调试会话在用户空间不可打开
    return
  }
  void router.push({ path: '/home', query: { conversation_id: conv.id } })
}

// ---------- 重命名 ----------
const openRename = (conv: ViewConversation) => {
  updateConversationNameId.value = conv.id
  updateConversationName.value = conv.name
  updateConversationNameVisible.value = true
}

const onRenameSaved = (id: string, name: string) => {
  const list = normalizedQuery.value ? searchResults.value : recentConversationsView.value
  const conv = list.find(c => c.id === id)
  if (conv) conv.name = name
}

// ---------- 删除（走回收站 hook） ----------
const requestDelete = (conv: ViewConversation) => {
  handleDeleteConversation(conv.id, async () => {
    searchResults.value = searchResults.value.filter(c => c.id !== conv.id)
    recentConversationsView.value = recentConversationsView.value.filter(c => c.id !== conv.id)
  }, conv.name)
}

// ---------- 初始化 ----------
onMounted(() => {
  void loadRecent(20)
})
</script>

<template>
  <div class="search-page relative w-full overflow-y-auto">
    <div class="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
      <!-- 页头 -->
      <header>
        <h1 class="search-title text-2xl font-bold leading-tight sm:text-3xl">
          {{ t('conversationSearch.title') }}
        </h1>
        <p class="mt-2 text-sm text-muted">在对话记录中搜索，快速找回历史问答</p>
      </header>

      <!-- 搜索框 -->
      <section class="mt-6" aria-label="搜索">
        <div class="relative">
          <icon-search
            class="pointer-events-none absolute left-5 top-1/2 h-5 w-5 -translate-y-1/2 text-muted"
          />
          <input
            v-model="searchQuery"
            data-testid="conversation-search-input"
            type="search"
            :placeholder="t('conversationSearch.placeholder')"
            class="search-input search-serif w-full rounded-full border border-border-strong bg-card py-3.5 pl-14 pr-16 text-base text-text shadow-[var(--aicss-shadow-card)] outline-hidden transition placeholder:text-muted focus:border-brand focus:ring-2 focus:ring-brand-soft"
          />
          <kbd
            class="pointer-events-none absolute right-5 top-1/2 -translate-y-1/2 rounded-full bg-surface-2 px-2.5 py-1 font-mono text-xs text-muted"
          >
            ⌘K
          </kbd>
        </div>
      </section>

      <!-- 结果区 -->
      <section class="mt-9" aria-label="搜索结果">
        <!-- 加载状态 -->
        <div v-if="loading" class="space-y-3">
          <div
            v-for="i in 3"
            :key="`skeleton-${i}`"
            class="flex animate-pulse items-start gap-4 rounded-[var(--aicss-radius)] border border-border-c bg-card p-4"
          >
            <div class="h-11 w-11 rounded-[var(--aicss-radius)] bg-surface-2"></div>
            <div class="flex-1 space-y-2">
              <div class="h-4 w-1/3 rounded bg-surface-2"></div>
              <div class="h-3 w-2/3 rounded bg-surface-2"></div>
            </div>
          </div>
        </div>

        <!-- 无关键词：最近会话 -->
        <div v-else-if="normalizedQuery === ''">
          <div class="mb-4 flex items-center gap-2">
            <icon-history class="h-4 w-4 text-brand" />
            <h2 class="search-subtitle text-lg font-bold">最近对话</h2>
          </div>

          <div v-if="recentLoading && recentConversationsView.length === 0" class="space-y-3">
            <div
              v-for="i in 4"
              :key="`recent-skeleton-${i}`"
              class="flex animate-pulse items-start gap-4 rounded-[var(--aicss-radius)] border border-border-c bg-card p-4"
            >
              <div class="h-11 w-11 rounded-[var(--aicss-radius)] bg-surface-2"></div>
              <div class="flex-1 space-y-2">
                <div class="h-4 w-1/3 rounded bg-surface-2"></div>
                <div class="h-3 w-1/2 rounded bg-surface-2"></div>
              </div>
            </div>
          </div>

          <div v-else-if="filteredConversations.length === 0" class="mt-2 text-center">
            <p class="text-sm text-muted">暂无最近对话，开始一段新对话吧</p>
          </div>

          <div v-else class="space-y-3">
            <a
              v-for="conv in filteredConversations"
              :key="conv.id"
              data-testid="conversation-card"
              class="group flex cursor-pointer items-start gap-4 rounded-[var(--aicss-radius)] border border-border-c bg-card p-4 shadow-[var(--aicss-shadow-card)] transition hover:-translate-y-0.5 hover:border-brand-soft hover:shadow-[var(--aicss-shadow-elevated)] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-brand-soft"
              @click.prevent="openConversation(conv)"
            >
              <div
                class="search-avatar flex h-12 w-12 shrink-0 items-center justify-center rounded-[var(--aicss-radius)] bg-linear-to-br from-brand to-brand-soft text-white shadow-[var(--aicss-shadow-card)]"
              >
                <icon-message class="h-5 w-5" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center justify-between gap-3">
                  <h3
                    class="truncate text-base font-bold text-text transition group-hover:text-brand-text"
                    v-html="highlightTitle(conv.name)"
                  />
                  <time class="shrink-0 font-mono text-xs text-muted">{{ conv.updatedAt }}</time>
                </div>
                <p
                  v-if="conv.question"
                  class="mt-1.5 truncate text-sm text-muted"
                  v-html="`<span class='search-q'>问：</span>${snippetAround(conv.question, 40)}`"
                />
                <p
                  v-else-if="conv.answer"
                  class="mt-1.5 truncate text-sm text-muted"
                  v-html="`<span class='search-q'>答：</span>${snippetAround(conv.answer, 40)}`"
                />
              </div>
            </a>
          </div>
        </div>

        <!-- 有关键词：搜索结果 -->
        <div v-else-if="hasResult" class="space-y-3">
          <div class="mb-4 text-xs text-muted">
            找到 {{ filteredConversations.length }} 个相关对话
          </div>
          <article
            v-for="conv in filteredConversations"
            :key="conv.id"
            data-testid="conversation-card"
            class="search-hit-card group relative cursor-pointer rounded-[var(--aicss-radius)] border border-border-c bg-card p-4 shadow-[var(--aicss-shadow-card)] transition hover:-translate-y-0.5 hover:border-brand-soft hover:shadow-[var(--aicss-shadow-elevated)] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-brand-soft"
            tabindex="0"
            role="link"
            @click="openConversation(conv)"
            @keydown.enter="openConversation(conv)"
          >
            <div class="flex items-start justify-between gap-3">
              <h3
                class="search-result-title search-serif min-w-0 truncate text-base font-bold text-text"
                v-html="highlightTitle(conv.name)"
              />
              <div class="flex shrink-0 items-center gap-2">
                <div class="search-row-actions flex items-center gap-1">
                  <button
                    type="button"
                    class="search-icon-btn flex h-8 w-8 items-center justify-center rounded-full text-muted transition hover:bg-surface-2 hover:text-text"
                    :aria-label="t('common.actions.rename')"
                    :title="t('common.actions.rename')"
                    @click.stop="openRename(conv)"
                  >
                    <icon-edit class="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    class="search-icon-btn flex h-8 w-8 items-center justify-center rounded-full text-muted transition hover:bg-surface-2 hover:text-text"
                    :aria-label="t('common.actions.deleteConversation')"
                    :title="t('common.actions.deleteConversation')"
                    @click.stop="requestDelete(conv)"
                  >
                    <icon-delete class="h-4 w-4" />
                  </button>
                </div>
                <icon-right class="search-open-icon h-4 w-4 text-muted" />
              </div>
            </div>

            <time class="mt-1 block font-mono text-xs text-muted">{{ conv.updatedAt }}</time>

            <div v-if="matchedMessage(conv)" class="search-snippet mt-2.5 space-y-1 text-sm leading-relaxed">
              <p
                v-if="conv.question"
                class="line-clamp-2 text-muted"
                v-html="`<span class='search-q'>问：</span>${snippetAround(conv.question)}`"
              />
              <p
                v-if="conv.answer"
                class="line-clamp-2 text-muted"
                v-html="`<span class='search-q'>答：</span>${snippetAround(conv.answer)}`"
              />
            </div>

            <div v-if="hasOtherMatches(conv)" class="search-source mt-2 text-xs text-muted">
              匹配来源：{{ matchLabels(conv).join(' / ') }}
            </div>

            <div class="mt-3 flex flex-wrap items-center gap-2">
              <span
                v-if="conv.appName"
                class="inline-flex items-center rounded-full bg-brand-soft px-2.5 py-0.5 text-xs font-medium text-brand-text"
                v-html="highlightText(conv.appName)"
              />
              <span
                v-if="conv.agentName"
                class="inline-flex items-center rounded-full bg-surface-2 px-2.5 py-0.5 text-xs font-medium text-text-2"
                v-html="highlightText(conv.agentName)"
              />
              <span
                v-if="conv.isSchedule"
                class="inline-flex items-center gap-1 rounded-full bg-brand px-2.5 py-0.5 text-xs font-medium text-white"
              >
                <icon-schedule class="h-3 w-3" />
                定时
              </span>
            </div>
          </article>
        </div>

        <!-- 空状态 -->
        <div
          v-else
          class="mt-4 flex flex-col items-center rounded-[var(--aicss-radius)] border-2 border-dashed border-brand-soft bg-surface-2/40 px-6 py-12 text-center"
        >
          <div
            class="flex h-12 w-12 items-center justify-center rounded-full bg-brand-soft text-brand-text"
          >
            <icon-search class="h-5 w-5" />
          </div>
          <p class="search-serif mt-4 text-lg font-bold text-text">
            {{ t('conversationSearch.noResultsTitle') }}
          </p>
          <p class="mt-1 text-sm text-muted">换个关键词试试</p>
        </div>
      </section>

      <!-- 页脚 -->
      <footer
        class="mt-12 flex flex-col items-center justify-between gap-3 border-t border-border-c pb-2 pt-6 text-xs text-muted sm:flex-row"
      >
        <p>钰心AI · 用心对话，智慧陪伴</p>
      </footer>
    </div>

    <!-- 重命名弹窗 -->
    <update-conversation-name-modal
      v-model:visible="updateConversationNameVisible"
      :conversation_id="updateConversationNameId"
      :conversation_name="updateConversationName"
      @saved="onRenameSaved"
    />

    <!-- 删除确认弹窗（回收站联动文案） -->
    <user-recycle-bin-delete-modal
      :visible="deleteVisible"
      :title="t('common.actions.deleteConversation')"
      :resource-name="deleteName"
      :loading="deleteLoading"
      :hint="t('userRecycleBin.deleteHint')"
      @update:visible="v => (deleteVisible = v)"
      @confirm="confirmDeleteConversation"
    />
  </div>
</template>

<style scoped>
.search-page {
  height: 100%;
  background: var(--aicss-bg);
}

/* 滚动条微调（保持轻量、不抢视觉） */
.search-page::-webkit-scrollbar {
  width: 6px;
}
.search-page::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: var(--aicss-border-strong);
}
.search-page::-webkit-scrollbar-track {
  background: transparent;
}

/* 页面大标题：衬线体 + 收紧字距（对应原型 font-serif） */
.search-title {
  font-family: var(--aicss-font-serif, Georgia, 'Songti SC', serif);
  letter-spacing: -0.02em;
  color: var(--aicss-text);
}

.search-subtitle {
  font-family: var(--aicss-font-serif, Georgia, 'Songti SC', serif);
  letter-spacing: -0.02em;
  color: var(--aicss-text);
}

/* 组件内所有希望呈现衬线的元素统一走该工具类 */
.search-serif {
  font-family: Georgia, 'Songti SC', 'SimSun', serif;
  letter-spacing: -0.01em;
}

/* 搜索框：粉调胶囊 */
.search-input {
  color: var(--aicss-text);
  background: var(--aicss-card);
}
.search-input::placeholder {
  color: var(--aicss-muted);
}
.search-input:focus {
  border-color: var(--aicss-accent);
  box-shadow: 0 0 0 3px var(--aicss-accent-soft);
}

/* 结果标题（衬线大标题行内保留高亮 mark） */
.search-result-title {
  color: var(--aicss-text);
}

/* 关键词高亮：粉底胶囊式 */
:deep(.search-hit) {
  background: var(--aicss-accent-soft);
  color: var(--aicss-brand-text, var(--aicss-accent-text));
  border-radius: 6px;
  padding: 0 2px;
  font-weight: 600;
}

/* 问/答前缀 */
:deep(.search-q) {
  font-weight: 600;
  color: var(--aicss-text-2);
}

/* 搜索源 meta */
.search-source {
  color: var(--aicss-muted);
}

/* 图标块（粉调渐变底） */
.search-avatar {
  background: linear-gradient(135deg, var(--aicss-accent) 0%, var(--aicss-accent-text) 100%);
  color: #fff;
}

/* 结果卡 hover 动作行 */
.search-row-actions {
  opacity: 0;
  transition: opacity 0.18s var(--aicss-ease);
}
.search-hit-card:hover .search-row-actions,
.search-hit-card:focus-within .search-row-actions {
  opacity: 1;
}

.search-icon-btn {
  background: transparent;
  border: none;
  cursor: pointer;
}
.search-icon-btn:hover {
  background: var(--aicss-surface-2);
}
.search-icon-btn[aria-label*='删除']:hover,
.search-icon-btn[title*='删除']:hover {
  color: var(--aicss-destructive, var(--aicss-accent-text));
}

/* 进入会话箭头：hover 显示 */
.search-open-icon {
  opacity: 0;
  transition: opacity 0.18s var(--aicss-ease);
}
.search-hit-card:hover .search-open-icon {
  opacity: 1;
}

/* 消息摘录 2 行裁剪 */
.search-snippet :deep(p) {
  margin: 0;
}
.search-snippet :deep(.line-clamp-2) {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}
</style>
