<script setup lang="ts">
import { QueueEvent } from '@/config'
import { useAudioPlayer } from '@/hooks/use-audio'
import { copyTextToClipboard } from '@/utils/clipboard'
import { Message } from '@arco-design/web-vue'
import { computed, nextTick, onBeforeUnmount, ref, watch, type PropType } from 'vue'
import { useI18n } from 'vue-i18n'
import AiToolCallState from './ai-chat-ui/AiToolCallState.vue'
import type { AiToolRow } from './ai-chat-ui/types'

// 1.定义自定义组件所需数据
const props = defineProps({
  loading: { type: Boolean, default: false, required: true },
  message_id: { type: String, default: '', required: false },
  variant: { type: String as PropType<'sidebar' | 'inline'>, default: 'sidebar', required: false },
  default_visible: { type: Boolean, default: false, required: false },
  follow_latest_thought: { type: Boolean, default: false, required: false },
  agent_thoughts: {
    type: Array as PropType<Record<string, unknown>[]>,
    default: () => [],
    required: true,
  },
})
const { t } = useI18n()

const visible = ref(props.default_visible)
const containerRef = ref<HTMLElement | null>(null)
const activeThoughtKeys = ref<(string | number)[]>([])

// 流式期间（loading 或 follow_latest_thought 为 true）强制展开所有思考项，
// 保证推理过程逐 token 实时可见；用户手动折叠/展开后恢复正常交互。
// 不依赖 syncLatestThought 的 watch 时序，避免流式早期 follow 状态
// 尚未建立（item.id === message_id 未匹配）时卡片保持折叠。
const effectiveActiveKeys = computed(() => {
  if (props.loading || props.follow_latest_thought) {
    return thoughtItems.value.map((item) => getThoughtKey(item))
  }
  return activeThoughtKeys.value
})

// 手动展开/收起整个卡片：展开时把所有思考项一起展开，方便查看完整推理
const handleToggle = () => {
  visible.value = !visible.value
  if (visible.value) {
    activeThoughtKeys.value = thoughtItems.value.map((item) => getThoughtKey(item))
  }
}

// 流式期间（loading 或 follow_latest_thought）强制展开思考容器并展开所有思考项，
// 保证推理过程逐 token 实时可见；流式结束（两者均变 false）后默认收起：
// 一次到位、不闪烁，用户想看推理时可手动展开。
watch(
  [() => props.loading, () => props.follow_latest_thought],
  ([loading, follow], [prevLoading, prevFollow]) => {
    if (loading || follow) {
      visible.value = true
      activeThoughtKeys.value = thoughtItems.value.map((item) => getThoughtKey(item))
    } else if (prevLoading && !loading) {
      // 流式刚结束：稳定收起（不闪），避免 syncLatestThought 等时序把卡片留在展开态
      visible.value = false
      activeThoughtKeys.value = []
    }
  },
)

// 当 default_visible prop 变化时（如流式开始/结束），同步展开/折叠状态
watch(
  () => props.default_visible,
  (newVal) => {
    visible.value = newVal
  },
)
const {
  activeMessageId,
  activeThoughtId,
  activeStreamType,
  thoughtAudioLoading,
  startThoughtAudioStream,
  stopAudioStream,
} = useAudioPlayer()

const thoughtItems = computed(() =>
  props.agent_thoughts.filter((item: Record<string, unknown>) =>
    [
      QueueEvent.longTermMemoryRecall,
      QueueEvent.agentThought,
      QueueEvent.datasetRetrieval,
      QueueEvent.agentAction,
      // agent_message（"回复"卡片）与答案气泡内容重复，不再单独渲染卡片
    ].includes(String(item.event)) &&
    // 过滤无实际内容的思考条目，避免渲染只有标题+耗时的空卡片。
    // agent_action 即使观察为空也可能携带工具信息，予以保留
    (String(
      item.thought ?? item.content ?? item.reasoning ?? item.answer ?? item.observation ?? item.result ?? item.output ?? '',
    ).trim() !== '' || String(item.event) === QueueEvent.agentAction),
  ),
)

const toolCallCards = computed(() => {
  return thoughtItems.value.map((agentThought) => {
    const event = String(agentThought.event)
    const content = getThoughtContent(agentThought)
    const latency = Number(agentThought.latency || 0)
    const status: 'loading' | 'done' | 'error' = props.loading ? 'loading' : 'done'

    const isAgentAction = event === QueueEvent.agentAction
    const toolName = isAgentAction ? String(agentThought.tool || '') : ''

    const rows: AiToolRow[] = []
    const toolInput = agentThought.tool_input
    if (isAgentAction && toolInput && typeof toolInput === 'object') {
      const record = toolInput as Record<string, unknown>
      const timeline = (record.timeline || {}) as Record<string, unknown>
      const rawTodos = Array.isArray(timeline.todos) ? timeline.todos : Array.isArray(record.todos) ? record.todos : []
      rows.push(
        ...rawTodos
          .map((todo, index) => {
            if (todo && typeof todo === 'object') {
              const item = todo as Record<string, unknown>
              const label = String(
                item.content ?? item.text ?? item.description ?? item.title ?? item.name ?? '',
              ).trim()
              return {
                title: label,
                url: '',
                status: normalizeTodoStatus(String(item.status || '')),
              } as AiToolRow
            }
            return { title: String(todo || ''), url: '', status: 'pending' } as AiToolRow
          })
          .filter((row) => row.title),
      )
    }

    return {
      key: String(getThoughtKey(agentThought)),
      event,
      content,
      latency,
      status,
      isAgentAction,
      toolName,
      rows,
      agentThought,
    }
  })
})

const normalizeTodoStatus = (status: string) => {
  const normalized = status.trim().toLowerCase().replace(/[\s-]+/g, '_')
  if (['completed', 'complete', 'done', 'success', 'succeeded', 'finished'].includes(normalized)) {
    return 'done'
  }
  if (['error', 'failed', 'fail', 'failure'].includes(normalized)) return 'error'
  if (['in_progress', 'progress', 'running', 'working', 'doing', 'start'].includes(normalized)) {
    return 'loading'
  }
  return 'pending'
}

const resolveToolCardTitle = (event: string, toolName: string) => {
  if (event === QueueEvent.longTermMemoryRecall) return t('chat.thought.events.longTermMemoryRecall')
  if (event === QueueEvent.datasetRetrieval) return t('chat.thought.events.datasetRetrieval')
  if (event === QueueEvent.agentThought) return t('chat.thought.events.agentThought')
  if (event === QueueEvent.agentAction) return toolName || t('chat.thought.events.agentAction')
  return t('chat.thought.events.fallback')
}

const resolveToolCardKind = (event: string) => {
  if (event === QueueEvent.longTermMemoryRecall || event === QueueEvent.datasetRetrieval) {
    return 'web-search'
  }
  if (event === QueueEvent.agentAction) return 'tool'
  return 'tool'
}

const getThoughtKey = (agentThought: Record<string, unknown>) => {
  if (typeof agentThought?.id === 'number') return agentThought.id
  return String(agentThought?.id ?? '')
}

const latestThoughtKey = computed(() => {
  if (thoughtItems.value.length === 0) return ''
  return String(getThoughtKey(thoughtItems.value[thoughtItems.value.length - 1]))
})
const isInlineVariant = computed(() => props.variant === 'inline')

const isLatestThought = (agentThought: Record<string, unknown>) => {
  return String(getThoughtKey(agentThought)) === latestThoughtKey.value
}

const containerClass = computed(() => {
  return 'agent-thought aicss-agent-thought max-w-full min-w-0 flex flex-col gap-2 transition-all duration-300'
})

const toggleTitle = computed(() => {
  return visible.value ? t('chat.thought.hideTechnicalDetails') : t('chat.thought.showTechnicalDetails')
})

const toggleLabel = computed(() => {
  return visible.value ? t('chat.thought.hideTechnicalDetails') : t('chat.thought.showTechnicalDetails')
})

const headerClass = computed(() => {
  return 'agent-thought__header'
})

// 后端持久化时写入 thought 字段的占位文字（真实内容在 observation / answer）
const PLACEHOLDER_THOUGHT_TEXTS = new Set([
  'assistant_agent',
  'Orchestrator routing decision',
  'orchestrator',
  '指挥官决策',
  'agent',
])

const isPlaceholderThought = (thought: string) => PLACEHOLDER_THOUGHT_TEXTS.has(thought)

const getThoughtContent = (agentThought: Record<string, unknown>) => {
  const event = agentThought?.event
  if (event === QueueEvent.agentThought || event === QueueEvent.agentMessage) {
    // 推理/回答内容：优先 thought / content / reasoning / answer
    // 但排除占位文字（如 "assistant_agent"、"Orchestrator routing decision"），
    // 这些是后端持久化时写入的固定标题，真实内容在 observation 字段
    const primary = String(
      agentThought?.thought || agentThought?.content || agentThought?.reasoning || agentThought?.answer || '',
    ).trim()
    if (primary && !isPlaceholderThought(primary)) return primary
    // 回退到 observation（路由决策详情 / 最终回答）
    const observation = String(agentThought?.observation || '').trim()
    if (observation) {
      // 路由决策详情是 JSON，格式化展示更易读
      if (observation.startsWith('{') || observation.startsWith('[')) {
        try {
          return JSON.stringify(JSON.parse(observation), null, 2)
        } catch {
          return observation
        }
      }
      return observation
    }
    return primary
  }
  // 工具调用 / 记忆召回 / 数据检索：兼容 observation / result / output
  return String(agentThought?.observation || agentThought?.result || agentThought?.output || '').trim()
}

const formatToolInput = (toolInput: unknown) => {
  if (!toolInput) return ''
  if (typeof toolInput === 'string') {
    try {
      const parsed = JSON.parse(toolInput)
      return JSON.stringify(parsed).slice(0, 120)
    } catch {
      return toolInput.slice(0, 120)
    }
  }
  try {
    return JSON.stringify(toolInput).slice(0, 120)
  } catch {
    return String(toolInput).slice(0, 120)
  }
}

const getThoughtLatency = (agentThought: Record<string, unknown>) => {
  const raw = Number(agentThought?.latency)
  if (!Number.isFinite(raw) || raw <= 0) return '0.00s'
  return `${raw.toFixed(2)}s`
}

const getThoughtTitle = (event: string) => {
  if (event === QueueEvent.longTermMemoryRecall) return t('chat.thought.events.longTermMemoryRecall')
  if (event === QueueEvent.agentThought) return t('chat.thought.events.agentThought')
  if (event === QueueEvent.datasetRetrieval) return t('chat.thought.events.datasetRetrieval')
  if (event === QueueEvent.agentAction) return t('chat.thought.events.agentAction')
  if (event === QueueEvent.agentMessage) return t('chat.thought.events.agentMessage')
  if (event === QueueEvent.deepThinking) return t('chat.thought.events.deepThinking')
  return t('chat.thought.events.fallback')
}

const getThoughtTitleTooltip = (event: string) => {
  if (event === QueueEvent.longTermMemoryRecall) return t('chat.thought.events.longTermMemoryRecall')
  if (event === QueueEvent.agentThought) return t('chat.thought.events.agentThought')
  if (event === QueueEvent.datasetRetrieval) return t('chat.thought.events.datasetRetrieval')
  if (event === QueueEvent.agentAction) return t('chat.thought.events.agentAction')
  if (event === QueueEvent.agentMessage) return t('chat.thought.events.agentMessage')
  if (event === QueueEvent.deepThinking) return t('chat.thought.events.deepThinkingTooltip')
  return t('chat.thought.events.fallback')
}

const scrollThoughtIntoView = (thoughtKey: string) => {
  if (!containerRef.value || !thoughtKey) return
  const node = containerRef.value.querySelector(`[data-thought-key="${thoughtKey}"]`) as HTMLElement | null
  node?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
}

const syncLatestThought = async () => {
  if (!props.follow_latest_thought) return
  const latestKey = latestThoughtKey.value
  if (!latestKey) {
    activeThoughtKeys.value = []
    return
  }
  activeThoughtKeys.value = [latestKey]
  visible.value = true
  await nextTick()
  scrollThoughtIntoView(latestKey)
}

const handleCopyThought = async (agentThought: Record<string, unknown>) => {
  const content = getThoughtContent(agentThought)
  if (!content) {
    Message.warning(t('chat.thought.noCopyableContent'))
    return
  }
  await copyTextToClipboard(content)
  Message.success(t('chat.thought.copied'))
}

const isThoughtPlaying = (agentThoughtId: string) => {
  return (
    activeStreamType.value === 'thought' &&
    activeMessageId.value === props.message_id &&
    activeThoughtId.value === agentThoughtId
  )
}

const isThoughtLoading = (agentThoughtId: string) => {
  return (
    thoughtAudioLoading.value &&
    activeStreamType.value === 'thought' &&
    activeMessageId.value === props.message_id &&
    activeThoughtId.value === agentThoughtId
  )
}

const canShowThoughtAudioAction = computed(() => {
  return !props.loading && Boolean(props.message_id)
})

const handlePlayThought = async (agentThought: Record<string, unknown>) => {
  if (!props.message_id) {
    Message.warning(t('chat.thought.unsupportedAudioForMessage'))
    return
  }

  const content = getThoughtContent(agentThought)
  if (!content) {
    Message.warning(t('chat.thought.noPlayableContent'))
    return
  }

  const currentId = String(getThoughtKey(agentThought))
  if (!currentId) {
    Message.warning(t('chat.thought.unsupportedAudioForThought'))
    return
  }

  if (isThoughtPlaying(currentId)) {
    stopAudioStream()
    return
  }

  await startThoughtAudioStream(props.message_id, currentId, content)
}

watch(
  () =>
    thoughtItems.value.map((item) => ({
      key: String(getThoughtKey(item)),
      content: String(getThoughtContent(item) ?? ''),
    })),
  (currentItems, previousItems = []) => {
    if (!props.follow_latest_thought) return

    const currentIds = currentItems.map((item) => item.key)
    const previousIds = previousItems.map((item) => item.key)

    const latestChanged =
      currentIds.length !== previousIds.length ||
      currentIds[currentIds.length - 1] !== previousIds[previousIds.length - 1]

    // 最新推理内容变化时（流式推理逐 token 更新同一条 thought）也触发展开
    const latestContentChanged =
      currentItems[currentItems.length - 1]?.content !== previousItems[previousItems.length - 1]?.content

    const currentLatest = currentIds[currentIds.length - 1]
    const hasPinnedLatest =
      currentLatest !== undefined && activeThoughtKeys.value.map((key) => String(key)).includes(currentLatest)

    if (latestChanged || latestContentChanged || !hasPinnedLatest) {
      void syncLatestThought()
    }
  },
  { immediate: true },
)

watch(
  () => props.follow_latest_thought,
  (enabled) => {
    if (enabled) {
      void syncLatestThought()
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (activeStreamType.value !== 'thought' || !activeThoughtId.value) return
  if (thoughtItems.value.some((item) => String(item?.id || '') === activeThoughtId.value)) {
    stopAudioStream()
  }
})
</script>

<template>
  <!-- 智能体推理步骤 -->
  <div v-if="thoughtItems.length > 0" ref="containerRef" :class="containerClass">
    <button
      type="button"
      :class="headerClass"
      :title="toggleTitle"
      :aria-expanded="visible"
      @click="handleToggle"
    >
      <span
        class="agent-thought__dot"
        :class="{ 'agent-thought__dot--streaming': props.loading || props.follow_latest_thought }"
        aria-hidden="true"
      />
      <span
        v-if="props.loading || props.follow_latest_thought"
        class="agent-thought__label aicss-shimmer"
      >
        {{ t('chat.thought.thinking') }}
      </span>
      <span v-else class="agent-thought__label">
        {{ toggleLabel }}
        <span class="agent-thought__count">{{ thoughtItems.length }}</span>
      </span>
      <svg
        class="agent-thought__chevron"
        :class="{ 'agent-thought__chevron--open': visible }"
        viewBox="0 0 24 24"
        width="12"
        height="12"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="m4.5 15.75 7.5-7.5 7.5 7.5" />
      </svg>
    </button>
    <!-- 底部内容 -->
    <div
      v-if="visible"
      class="agent-thought__cards"
    >
      <div
        v-for="card in toolCallCards"
        :key="card.key"
        :class="['agent-thought-card', { 'agent-thought-item--latest': card.key === latestThoughtKey }]"
        :data-thought-key="card.key"
      >
        <div class="agent-thought-card__main">
          <ai-tool-call-state
            :kind="resolveToolCardKind(card.event)"
            :title="resolveToolCardTitle(card.event, card.toolName)"
            :status="card.status"
            :latency="card.latency"
            :rows="card.rows"
            :details="card.isAgentAction ? '' : card.content || undefined"
          />
        </div>
        <div class="agent-thought-card__footer">
          <div class="agent-thought-card__actions">
            <button
              type="button"
              class="agent-thought-card__action"
              :title="t('chat.thought.copy')"
              @click.stop="() => handleCopyThought(card.agentThought)"
            >
              <icon-copy />
            </button>
            <template v-if="canShowThoughtAudioAction">
              <span
                v-if="isThoughtLoading(card.key)"
                class="agent-thought-card__action agent-thought-card__action--loading"
              >
                <icon-loading />
              </span>
              <button
                v-else-if="isThoughtPlaying(card.key)"
                type="button"
                class="agent-thought-card__action"
                :title="t('chat.thought.stopPlay')"
                @click.stop="stopAudioStream"
              >
                <icon-pause />
              </button>
              <button
                v-else
                type="button"
                class="agent-thought-card__action"
                :title="t('chat.thought.play')"
                @click.stop="() => handlePlayThought(card.agentThought)"
              >
                <icon-play-circle />
              </button>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-thought__header {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  align-self: flex-start;
  max-width: 100%;
  min-height: 22px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--aicss-muted);
  cursor: pointer;
  user-select: none;
  font-family: var(--aicss-font);
  transition: color 0.16s ease;
}

.agent-thought__header:hover {
  color: var(--aicss-text-2);
}

.agent-thought__dot {
  width: 7px;
  height: 7px;
  flex: none;
  border-radius: 50%;
  background: var(--aicss-subtle);
  box-shadow: 0 0 0 0 color-mix(in srgb, var(--aicss-accent) 36%, transparent);
  transition:
    background-color 0.2s ease,
    box-shadow 0.2s ease;
}

.agent-thought__dot--streaming {
  background: var(--aicss-accent);
  animation: agent-thought-pulse 1.5s var(--aicss-ease) infinite;
}

@keyframes agent-thought-pulse {
  0% {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--aicss-accent) 36%, transparent);
    transform: scale(0.9);
  }
  55% {
    box-shadow: 0 0 0 6px transparent;
    transform: scale(1);
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
    transform: scale(0.9);
  }
}

.agent-thought__label {
  font-size: 13px;
  font-weight: 500;
  line-height: 18px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-thought__count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  margin-left: 4px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--aicss-surface-2);
  color: var(--aicss-muted);
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.agent-thought__chevron {
  flex: none;
  color: var(--aicss-subtle);
  transform: rotate(-90deg);
  transition: transform 0.24s var(--aicss-ease);
}

.agent-thought__chevron--open {
  transform: rotate(0deg);
}

.agent-thought__cards {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  padding-left: 14px;
  position: relative;
}

.agent-thought__cards::before {
  content: "";
  position: absolute;
  top: 8px;
  bottom: 8px;
  left: 3px;
  width: 1px;
  background: var(--aicss-border);
}

.agent-thought-card {
  position: relative;
  min-width: 0;
}

.agent-thought-card__main {
  min-width: 0;
}

.agent-thought-card__footer {
  display: flex;
  justify-content: flex-end;
  min-height: 0;
  margin-top: -2px;
  padding: 0 6px;
}

.agent-thought-card__actions {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.16s ease;
}

.agent-thought-card:hover .agent-thought-card__actions,
.agent-thought-card:focus-within .agent-thought-card__actions {
  opacity: 1;
  pointer-events: auto;
}

.agent-thought-card__action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: 0;
  background: transparent;
  color: var(--aicss-muted);
  border-radius: 6px;
  cursor: pointer;
  transition:
    color 0.16s ease,
    background-color 0.16s ease;
}

.agent-thought-card__action--loading {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  color: var(--aicss-muted);
}

.agent-thought-card__action:hover {
  color: var(--aicss-text-2);
  background: var(--aicss-surface-2);
}

.agent-thought-card--latest {
  border-radius: 10px;
}

@media (hover: none) {
  .agent-thought-card__actions {
    opacity: 1;
    pointer-events: auto;
  }
}

@media (prefers-reduced-motion: reduce) {
  .agent-thought__dot--streaming {
    animation: none;
  }
}
</style>
