<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import {
  useGetKnowledgeDocumentsWithPage,
  useGetKnowledgeSegmentsWithPage,
} from '@/hooks/use-knowledge-base'
import { reassembleKnowledgeDocument } from '@/services/knowledge-base'
import { getErrorMessage } from '@/utils/error'

type TimelineClip = {
  document_id: string
  segment_index: number
  frame_url?: string
  start_sec?: number
  end_sec?: number
  speech_text?: string
  content?: string
}

const props = defineProps<{
  knowledgeBaseId: string
  documentId: string
  visible: boolean
}>()
const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
}>()
const { t } = useI18n()

// 主文档分段与替换素材分段必须用两个 hook 实例：单实例单缓存，
// 共用一个会把主文档时间线冲掉（替换素材分段加载会覆盖缓存）。
const { loading: segLoading, segments: mainSegments, loadSegments: loadMainSegments } = useGetKnowledgeSegmentsWithPage()
const { loading: sourceSegLoading, segments: sourceSegments, loadSegments: loadSourceSegments } = useGetKnowledgeSegmentsWithPage()
const { loading: docLoading, documents, loadDocuments } = useGetKnowledgeDocumentsWithPage()

const clips = ref<TimelineClip[]>([])
const name = ref('')
const submitting = ref(false)
const replaceIndex = ref<number | null>(null)
const replaceDocId = ref('')
const replaceSegments = ref<TimelineClip[]>([])
const dragIndex = ref<number | null>(null)

const mainTimeline = computed(() =>
  mainSegments.value.filter(
    seg => seg.source === 'vision_timeline' && Number(seg.start_sec) >= 0,
  ),
)

const replaceableVideos = computed(() =>
  documents.value.filter(doc => doc.media_type === 'video'),
)

const canSubmit = computed(() => clips.value.length > 0 && !submitting.value)

watch(
  () => [props.visible, props.documentId] as const,
  async ([visible, docId]) => {
    if (!visible || !docId || !props.knowledgeBaseId) return
    clips.value = []
    name.value = ''
    replaceIndex.value = null
    replaceDocId.value = ''
    replaceSegments.value = []
    dragIndex.value = null
    await loadMainSegments(props.knowledgeBaseId, docId, true)
    // 初始编排 = 主文档全部时间线段落（按 position 顺序）
    clips.value = mainTimeline.value.map((seg, index) => ({
      document_id: docId,
      segment_index: index + 1,
      frame_url: seg.frame_url,
      start_sec: seg.start_sec,
      end_sec: seg.end_sec,
      speech_text: seg.speech_text,
      content: seg.content,
    }))
  },
  { immediate: true },
)

const handleDragStart = (index: number) => {
  dragIndex.value = index
}

const handleDragOver = (event: DragEvent) => {
  event.preventDefault()
}

const handleDrop = (index: number) => {
  if (dragIndex.value === null || dragIndex.value === index) return
  const list = [...clips.value]
  const [moved] = list.splice(dragIndex.value, 1)
  list.splice(index, 0, moved)
  clips.value = list
  dragIndex.value = null
}

const handleRemove = (index: number) => {
  clips.value = clips.value.filter((_, i) => i !== index)
}

const openReplacer = async (index: number) => {
  replaceIndex.value = index
  replaceDocId.value = ''
  replaceSegments.value = []
  await loadDocuments(props.knowledgeBaseId, {
    current_page: 1,
    page_size: 50,
    search_word: '',
  })
}

const pickReplaceDoc = async (docId: string) => {
  replaceDocId.value = docId
  replaceSegments.value = []
  await loadSourceSegments(props.knowledgeBaseId, docId, true)
  replaceSegments.value = sourceSegments.value
    .filter(seg => seg.source === 'vision_timeline' && Number(seg.start_sec) >= 0)
    .map((seg, index) => ({
      document_id: docId,
      segment_index: index + 1,
      frame_url: seg.frame_url,
      start_sec: seg.start_sec,
      end_sec: seg.end_sec,
      speech_text: seg.speech_text,
      content: seg.content,
    }))
}

const applyReplace = (seg: TimelineClip) => {
  if (replaceIndex.value === null) return
  const next = [...clips.value]
  next[replaceIndex.value] = seg
  clips.value = next
  replaceIndex.value = null
  replaceDocId.value = ''
  replaceSegments.value = []
}

const handleSubmit = async () => {
  if (clips.value.length === 0) return
  submitting.value = true
  try {
    await reassembleKnowledgeDocument(props.knowledgeBaseId, props.documentId, {
      clips: clips.value.map(clip => ({
        document_id: clip.document_id,
        segment_index: clip.segment_index,
      })),
      name: name.value,
    })
    Message.success(t('space.datasets.detail.material.reassembleSubmitted'))
    emit('update:visible', false)
  } catch (error) {
    Message.error(getErrorMessage(error, t('space.datasets.detail.material.reassembleFailed')))
  } finally {
    submitting.value = false
  }
}

const formatTime = (sec?: number) => {
  const total = Math.max(0, Math.floor(Number(sec) || 0))
  const m = Math.floor(total / 60).toString().padStart(2, '0')
  const s = (total % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}
</script>

<template>
  <a-modal
    :visible="visible"
    :width="720"
    :footer="false"
    @cancel="emit('update:visible', false)"
  >
    <template #title>
      <span class="text-base font-semibold text-text">
        {{ t('space.datasets.detail.material.reassembleTitle') }}
      </span>
    </template>

    <div class="space-y-3">
      <p class="text-xs text-muted">
        {{ t('space.datasets.detail.material.reassembleHint') }}
      </p>

      <a-input
        v-model="name"
        :placeholder="t('space.datasets.detail.material.reassembleNamePlaceholder')"
      />

      <a-skeleton v-if="segLoading" :animation="true" />
      <a-empty v-else-if="mainTimeline.length === 0">
        <template #description>{{ t('space.datasets.detail.material.reassembleEmpty') }}</template>
      </a-empty>

      <div v-else class="space-y-2">
        <div
          v-for="(clip, index) in clips"
          :key="`${clip.document_id}-${clip.segment_index}-${index}`"
          class="flex items-center gap-3 rounded-lg border border-border-c bg-surface p-3"
          draggable="true"
          @dragstart="handleDragStart(index)"
          @dragend="dragIndex = null"
          @dragover="handleDragOver"
          @drop="handleDrop(index)"
        >
          <img
            v-if="clip.frame_url"
            :src="clip.frame_url"
            class="h-14 w-20 shrink-0 rounded object-cover"
            alt=""
          />
          <div class="min-w-0 flex-1">
            <p class="line-clamp-1 text-sm font-medium text-text">
              {{ clip.content || clip.speech_text || `#${index + 1}` }}
            </p>
            <p class="mt-0.5 text-xs text-muted">
              {{ formatTime(clip.start_sec) }} ~ {{ formatTime(clip.end_sec) }}
            </p>
          </div>
          <button
            type="button"
            class="shrink-0 text-xs text-brand-text"
            :data-test="`replace-clip-${index}`"
            @click="openReplacer(index)"
          >
            {{ t('space.datasets.detail.material.reassembleReplace') }}
          </button>
          <button
            type="button"
            class="shrink-0 text-xs text-red-500"
            data-test="remove-clip"
            @click="handleRemove(index)"
          >
            {{ t('space.datasets.detail.material.reassembleDelete') }}
          </button>
        </div>
      </div>

      <!-- 替换素材选择区 -->
      <div
        v-if="replaceIndex !== null"
        class="rounded-lg border border-border-c bg-surface-2 p-3"
      >
        <p class="mb-2 text-xs font-medium text-text-2">
          {{ t('space.datasets.detail.material.reassembleReplaceTitle') }}
        </p>
        <div v-if="replaceDocId === ''" class="space-y-1">
          <a-skeleton v-if="docLoading" :animation="true" />
          <button
            v-for="doc in replaceableVideos"
            :key="doc.id"
            type="button"
            class="block w-full rounded px-2 py-1.5 text-left text-sm text-text hover:bg-surface"
            :data-test="`pick-doc-${doc.id}`"
            @click="pickReplaceDoc(String(doc.id))"
          >
            {{ doc.name }}
          </button>
        </div>
        <div v-else class="space-y-1">
          <button
            type="button"
            class="mb-1 text-xs text-muted"
            :data-test="'back-to-docs'"
            @click="replaceDocId = ''; replaceSegments = []"
          >
            {{ t('space.datasets.detail.material.reassembleBack') }}
          </button>
          <a-skeleton v-if="sourceSegLoading" :animation="true" />
          <button
            v-for="(seg, segIndex) in replaceSegments"
            :key="segIndex"
            type="button"
            class="block w-full rounded px-2 py-1.5 text-left text-sm text-text hover:bg-surface"
            :data-test="`pick-segment-${segIndex}`"
            @click="applyReplace(seg)"
          >
            {{ seg.content || seg.speech_text || `#${segIndex + 1}` }}
            <span class="ml-1 text-xs text-muted">
              {{ formatTime(seg.start_sec) }} ~ {{ formatTime(seg.end_sec) }}
            </span>
          </button>
        </div>
      </div>

      <div class="flex justify-end gap-2 pt-1">
        <a-button @click="emit('update:visible', false)">
          {{ t('space.datasets.detail.material.reassembleCancel') }}
        </a-button>
        <a-button
          type="primary"
          data-test="submit"
          :disabled="!canSubmit"
          :loading="submitting"
          @click="handleSubmit"
        >
          {{ t('space.datasets.detail.material.reassembleSubmit') }}
        </a-button>
      </div>
    </div>
  </a-modal>
</template>
