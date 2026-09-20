<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import {
  useGetKnowledgeDocument,
  useGetKnowledgeSegmentsWithPage,
} from '@/hooks/use-knowledge-base'
import { deleteKnowledgeDocument, triggerDocumentL2 } from '@/services/knowledge-base'
import { getErrorMessage } from '@/utils/error'
import TimelineEditorModal from './TimelineEditorModal.vue'

const props = defineProps<{
  knowledgeBaseId: string
  documentId: string | null
  visible: boolean
}>()
const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
  (e: 'deleted'): void
}>()
const { t } = useI18n()

const { loading: docLoading, document, loadDocument } = useGetKnowledgeDocument()
const { loading: segLoading, segments, loadSegments } = useGetKnowledgeSegmentsWithPage()
const l2Loading = ref(false)
const deleteLoading = ref(false)
const editorVisible = ref(false)
const canReassemble = computed(() => document.value.media_type === 'video')

watch(
  () => [props.visible, props.documentId] as const,
  ([visible, docId]) => {
    if (!visible || !docId || !props.knowledgeBaseId) return
    void loadDocument(props.knowledgeBaseId, docId)
    void loadSegments(props.knowledgeBaseId, docId, true)
  },
  { immediate: true },
)

const handleTriggerL2 = async () => {
  if (!props.documentId) return
  l2Loading.value = true
  try {
    await triggerDocumentL2(props.knowledgeBaseId, props.documentId)
    Message.success(t('space.datasets.detail.material.l2Triggered'))
  } catch (error) {
    Message.error(getErrorMessage(error, t('space.datasets.detail.material.l2Failed')))
  } finally {
    l2Loading.value = false
  }
}

const handleDelete = async () => {
  if (!props.documentId) return
  deleteLoading.value = true
  try {
    await deleteKnowledgeDocument(props.knowledgeBaseId, props.documentId)
    emit('deleted')
    emit('update:visible', false)
  } catch (error) {
    Message.error(getErrorMessage(error, t('space.datasets.detail.material.deleteFailed')))
  } finally {
    deleteLoading.value = false
  }
}

const formatTime = (sec: number) => {
  const total = Math.max(0, Math.floor(Number(sec) || 0))
  const m = Math.floor(total / 60)
    .toString()
    .padStart(2, '0')
  const s = (total % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}
</script>

<template>
  <a-drawer :visible="visible" :width="480" :footer="false" @cancel="emit('update:visible', false)">
    <template #title>
      <span class="text-base font-semibold text-text">{{ document.name || '' }}</span>
    </template>

    <div class="flex flex-col gap-4">
      <div
        v-if="document.media_type === 'video' && document.playback_url"
        class="overflow-hidden rounded-xl border border-border-c bg-black"
      >
        <video :src="document.playback_url" controls playsinline class="aspect-video w-full" />
      </div>

      <div v-loading="docLoading" class="space-y-2 rounded-xl border border-border-c bg-surface-2 p-4">
        <p class="text-sm text-text-2">
          {{ t('space.datasets.detail.material.status') }}:
          <a-tag>{{ document.status || 'waiting' }}</a-tag>
        </p>
        <p class="text-sm text-text-2">
          {{ t('space.datasets.detail.material.segmentCount') }}: {{ document.segment_count ?? 0 }}
        </p>
        <p class="text-sm text-text-2">
          {{ t('space.datasets.detail.material.characterCount') }}: {{ document.character_count ?? 0 }}
        </p>
      </div>

      <div class="flex gap-2">
        <a-button type="primary" size="small" :loading="l2Loading" @click="handleTriggerL2">
          {{ t('space.datasets.detail.material.triggerL2') }}
        </a-button>
        <a-button
          v-if="canReassemble"
          size="small"
          data-test="open-reassemble"
          @click="editorVisible = true"
        >
          {{ t('space.datasets.detail.material.reassemble') }}
        </a-button>
        <a-button size="small" status="danger" :loading="deleteLoading" @click="handleDelete">
          {{ t('space.datasets.detail.material.delete') }}
        </a-button>
      </div>

      <div class="space-y-2">
        <a-skeleton v-if="segLoading" :animation="true" />
        <template v-else>
          <div
            v-for="seg in segments"
            :key="seg.id"
            class="flex gap-3 rounded-lg border border-border-c bg-surface p-3"
          >
            <img
              v-if="seg.frame_url"
              :src="seg.frame_url"
              class="h-16 w-24 shrink-0 rounded object-cover"
              alt=""
            />
            <div class="min-w-0 flex-1">
              <p v-if="seg.start_sec && seg.start_sec > 0" class="text-xs text-muted">
                {{ formatTime(seg.start_sec) }} ~ {{ formatTime(seg.end_sec) }}
              </p>
              <p class="line-clamp-3 text-sm text-text-2">{{ seg.content }}</p>
              <p class="mt-1 text-xs text-muted">#{{ seg.position }}</p>
            </div>
          </div>
          <a-empty v-if="segments.length === 0">
            <template #description>{{ t('space.datasets.detail.material.noSegments') }}</template>
          </a-empty>
        </template>
      </div>
    </div>

    <timeline-editor-modal
      v-model:visible="editorVisible"
      :knowledge-base-id="knowledgeBaseId"
      :document-id="String(documentId || '')"
    />
  </a-drawer>
</template>