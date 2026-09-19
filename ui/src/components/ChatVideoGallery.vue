<script setup lang="ts">
import { computed, ref, type PropType } from 'vue'
import { useI18n } from 'vue-i18n'

type ChatVideo = {
  name?: string
  url: string
  mime_type?: string
  extension?: string
}

const props = defineProps({
  videos: {
    type: Array as PropType<ChatVideo[]>,
    default: () => [],
  },
})

const { t } = useI18n()

const failedUrls = ref<string[]>([])

const normalizedVideos = computed(() => {
  return props.videos.filter((video): video is ChatVideo => {
    return Boolean(video && String(video.url || '').trim())
  })
})

const markFailed = (url: string) => {
  const normalized = String(url || '').trim()
  if (!normalized || failedUrls.value.includes(normalized))
    return
  failedUrls.value = [...failedUrls.value, normalized]
}

const isFailed = (url: string) => failedUrls.value.includes(String(url || '').trim())

const videoTitle = (video: ChatVideo, index: number) => {
  const name = String(video.name || '').trim()
  return name || t('chat.video.untitled', { index: index + 1 })
}

const sanitizeFilename = (value: string) => {
  return String(value || '')
    .trim()
    .replace(/[\\/:*?"<>|]/g, '_')
    .replace(/\s+/g, ' ')
    .replace(/\.+$/u, '')
}

const getUrlFilename = (url: string) => {
  try {
    return new URL(url).pathname.split('/').pop() || ''
  } catch {
    return ''
  }
}

const downloadFilename = (video: ChatVideo) => {
  const name = String(video.name || '').trim() || getUrlFilename(video.url) || 'video.mp4'
  const sanitized = sanitizeFilename(name)
  if (!sanitized)
    return 'video.mp4'
  return /\.[a-z0-9]{2,5}$/iu.test(sanitized) ? sanitized : `${sanitized}.mp4`
}

const triggerDownloadLink = (href: string, filename: string) => {
  const link = document.createElement('a')
  link.href = href
  link.download = filename
  link.rel = 'noreferrer'
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  link.remove()
}

const handleDownload = async (video: ChatVideo) => {
  const filename = downloadFilename(video)
  const fetcher = globalThis.fetch
  if (typeof fetcher === 'function') {
    try {
      const response = await fetcher(video.url, { mode: 'cors' })
      if (!response.ok)
        throw new Error(`HTTP ${response.status}`)

      const blob = await response.blob()
      if (typeof URL.createObjectURL === 'function') {
        const objectUrl = URL.createObjectURL(blob)
        triggerDownloadLink(objectUrl, filename)
        window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
        return
      }
    } catch {
      // 回退到直链下载
    }
  }

  triggerDownloadLink(video.url, filename)
}
</script>

<template>
  <div
    v-if="normalizedVideos.length > 0"
    class="chat-video-gallery"
  >
    <div
      v-for="(video, index) in normalizedVideos"
      :key="video.url"
      class="chat-video-card"
    >
      <div class="chat-video-card__title">
        {{ videoTitle(video, index) }}
      </div>
      <div class="chat-video-card__frame">
        <div
          v-if="isFailed(video.url)"
          class="chat-video-card__fallback"
        >
          <span>{{ t('chat.video.playbackFailed') }}</span>
          <a
            class="chat-video-card__fallback-link"
            :href="video.url"
            target="_blank"
            rel="noreferrer"
          >
            {{ t('chat.video.openInNewTab') }}
          </a>
        </div>
        <video
          v-else
          class="chat-video-card__player"
          :src="video.url"
          controls
          playsinline
          preload="metadata"
          @error="markFailed(video.url)"
        />
      </div>
      <div class="chat-video-card__actions">
        <button
          type="button"
          class="chat-video-card__download"
          :data-download-filename="downloadFilename(video)"
          :aria-label="t('chat.video.downloadAria', { filename: downloadFilename(video) })"
          @click="handleDownload(video)"
        >
          {{ t('chat.video.download') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-video-gallery {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 8px;
  max-width: 420px;
  width: 100%;
}

.chat-video-card {
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 12px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chat-video-card__title {
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
  word-break: break-all;
}

.chat-video-card__frame {
  border-radius: 8px;
  overflow: hidden;
  background: #0f172a;
  aspect-ratio: 16 / 9;
  display: flex;
  align-items: center;
  justify-content: center;
}

.chat-video-card__player {
  width: 100%;
  height: 100%;
  display: block;
  background: #000;
}

.chat-video-card__fallback {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #e5e7eb;
  font-size: 13px;
  padding: 16px;
  text-align: center;
}

.chat-video-card__fallback-link {
  color: #93c5fd;
  text-decoration: underline;
}

.chat-video-card__actions {
  display: flex;
  justify-content: flex-end;
}

.chat-video-card__download {
  font-size: 12px;
  color: #2563eb;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 2px 4px;
}

.chat-video-card__download:hover {
  text-decoration: underline;
}
</style>
