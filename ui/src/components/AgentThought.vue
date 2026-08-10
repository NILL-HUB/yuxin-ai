<script setup lang="ts">
import { QueueEvent } from '@/config'
import { useAudioPlayer } from '@/hooks/use-audio'
import { copyTextToClipboard } from '@/utils/clipboard'
import { Message } from '@arco-design/web-vue'
import { computed, nextTick, onBeforeUnmount, ref, watch, type PropType } from 'vue'
import { useI18n } from 'vue-i18n'

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

const handleCollapseChange = (keys: (string | number)[]) => {
  activeThoughtKeys.value = keys
}

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
  const baseClass = 'flex flex-col rounded-2xl border border-gray-200 bg-white overflow-hidden transition-all duration-300'
  if (isInlineVariant.value) {
    return `${baseClass} max-w-full flex-shrink-0 ${visible.value ? 'w-[min(560px,100%)]' : 'w-[180px]'}`
  }
  return `${baseClass} max-w-full ${visible.value ? 'w-[min(560px,100%)]' : 'w-[180px]'}`
})

const toggleTitle = computed(() => {
  return visible.value ? t('chat.thought.hideTechnicalDetails') : t('chat.thought.showTechnicalDetails')
})

const toggleLabel = computed(() => {
  return visible.value ? t('chat.thought.hideTechnicalDetails') : t('chat.thought.showTechnicalDetails')
})

const headerClass = computed(() => {
  return `relative flex items-center h-10 px-4 cursor-pointer text-gray-700 whitespace-nowrap select-none bg-gray-100 transition-colors hover:bg-gray-200 ${
    visible.value ? 'rounded-t-2xl border-b border-gray-200' : 'rounded-2xl'
  }`
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
    <div :class="headerClass" :title="toggleTitle" @click="handleToggle">
      <!-- 左侧图标与标题 -->
      <div class="flex items-center gap-2 font-medium text-gray-700 whitespace-nowrap">
        <icon-list />
        {{ toggleLabel }}
      </div>
      <!-- 右侧图标 -->
      <div class="absolute right-4 top-1/2 -translate-y-1/2 flex items-center">
        <template v-if="props.loading">
          <icon-loading />
        </template>
        <template v-else>
          <icon-up v-if="visible" />
          <icon-down v-else />
        </template>
      </div>
    </div>
    <!-- 底部内容 -->
    <a-collapse
      v-if="visible"
      class="agent-thought bg-transparent"
      destroy-on-hide
      :bordered="false"
      :active-key="effectiveActiveKeys"
      @change="handleCollapseChange"
    >
      <a-collapse-item
        v-for="agent_thought in thoughtItems"
        :key="getThoughtKey(agent_thought)"
        :class="['rounded-xl', { 'agent-thought-item--latest': isLatestThought(agent_thought) }]"
        :data-thought-key="String(getThoughtKey(agent_thought))"
      >
        <template #expand-icon>
          <icon-file v-if="agent_thought.event === QueueEvent.longTermMemoryRecall" />
          <icon-language v-else-if="agent_thought.event === QueueEvent.agentThought" />
          <icon-storage v-else-if="agent_thought.event === QueueEvent.datasetRetrieval" />
          <icon-tool v-else-if="agent_thought.event === QueueEvent.agentAction" />
          <icon-message v-else-if="agent_thought.event === QueueEvent.agentMessage" />
          <!-- 深度思考：脑图标（用 SVG 内联） -->
          <svg
            v-else-if="agent_thought.event === QueueEvent.deepThinking"
            class="h-[14px] w-[14px] text-violet-500"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-1.66Z" />
            <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-1.66Z" />
          </svg>
        </template>
        <template #header>
          <div
            :class="[
              'inline-block min-w-[6em] whitespace-nowrap font-semibold',
              isLatestThought(agent_thought) ? 'text-gray-800' : 'text-gray-700',
            ]"
            :title="getThoughtTitleTooltip(String(agent_thought.event))"
          >
            {{ getThoughtTitle(String(agent_thought.event)) }}
          </div>
        </template>
        <template #extra>
          <div class="text-xs text-gray-400">{{ getThoughtLatency(agent_thought) }}</div>
        </template>
        <div class="flex items-start gap-2">
          <div class="flex-1 text-xs text-gray-500 whitespace-pre-wrap break-words max-h-[240px] overflow-y-auto">
            <template v-if="agent_thought.event === QueueEvent.agentAction && agent_thought.tool">
              <div class="mb-1">
                <span class="font-mono text-blue-600 font-semibold">{{ agent_thought.tool }}</span>
                <span v-if="agent_thought.tool_input" class="text-gray-400 ml-1">
                  ({{ formatToolInput(agent_thought.tool_input) }})
                </span>
              </div>
            </template>
            {{ getThoughtContent(agent_thought) || '-' }}
          </div>
          <div class="flex items-center gap-1 flex-shrink-0">
            <icon-copy
              class="text-gray-400 cursor-pointer hover:text-gray-700"
              @click.stop="() => handleCopyThought(agent_thought)"
            />
            <template v-if="canShowThoughtAudioAction">
              <icon-loading
                v-if="isThoughtLoading(String(getThoughtKey(agent_thought)))"
                class="text-gray-400"
              />
              <icon-pause
                v-else-if="isThoughtPlaying(String(getThoughtKey(agent_thought)))"
                class="text-gray-400 cursor-pointer hover:text-gray-700"
                @click.stop="stopAudioStream"
              />
              <icon-play-circle
                v-else
                class="text-gray-400 cursor-pointer hover:text-gray-700"
                @click.stop="() => handlePlayThought(agent_thought)"
              />
            </template>
          </div>
        </div>
      </a-collapse-item>
    </a-collapse>
  </div>
</template>

<style scoped>
.agent-thought :deep(.arco-collapse-item) {
  border-bottom: 1px solid #f3f4f6;
}

.agent-thought :deep(.arco-collapse-item:last-child) {
  border-bottom: none;
}

.agent-thought :deep(.arco-collapse-item-header) {
  margin: 0;
  padding-top: 10px;
  padding-bottom: 10px;
  color: #374151;
  transition: background-color 0.18s ease;
}

.agent-thought :deep(.arco-collapse-item-header-left) {
  padding-right: 13px;
  padding-left: 34px;
}

.agent-thought :deep(.arco-collapse-item-header-right) {
  padding-right: 34px;
  padding-left: 13px;
}

.agent-thought :deep(.arco-collapse-item-header:hover) {
  background: #f9fafb;
}

.agent-thought :deep(.arco-collapse-item-active > .arco-collapse-item-header) {
  background: #f9fafb;
}

.agent-thought :deep(.arco-collapse-item-content) {
  padding-right: 13px;
  padding-bottom: 12px;
  padding-left: 34px;
}

.agent-thought-item--latest :deep(.arco-collapse-item-header) {
  background: #f9fafb;
}
</style>
