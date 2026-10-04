<script setup lang="ts">
/**
 * 文件中心卡片：AppCard 基座派生的业务卡片。
 *
 * 负责文件图标 / 图片缩略图（含失败回退）、来源标签与 hover 操作；
 * 打开/进入由调用方在组件上绑定原生 click（操作区已阻止冒泡）。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AppButton from '@/components/AppButton.vue'
import AppCard from '@/components/AppCard.vue'

const props = withDefaults(
  defineProps<{
    name: string
    isFolder?: boolean
    source?: string
    /** 文件的后端访问 URL（目录为 null） */
    url?: string | null
    /** 是否展示重命名/移动/删除操作（「全部文件」视图不展示） */
    showOps?: boolean
  }>(),
  { isFolder: false, source: 'upload', url: null, showOps: true },
)

const emit = defineEmits<{ (e: 'rename'): void; (e: 'move'): void; (e: 'delete'): void }>()

const { t, te } = useI18n()

const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg']
const VIDEO_EXTS = ['mp4', 'mov', 'webm', 'avi', 'mkv']
const AUDIO_EXTS = ['mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac']

const extOf = (name: string) => name.split('.').pop()?.toLowerCase() || ''
const isImageName = (name: string) => IMAGE_EXTS.includes(extOf(name))

/** 按扩展名映射文件图标（未注册的图标名会解析失败，新增时同步 plugins/arco.ts） */
const fileIconName = (name: string) => {
  const ext = extOf(name)
  if (IMAGE_EXTS.includes(ext)) return 'icon-file-image'
  if (ext === 'pdf') return 'icon-file-pdf'
  if (VIDEO_EXTS.includes(ext)) return 'icon-file-video'
  if (AUDIO_EXTS.includes(ext)) return 'icon-file-audio'
  return 'icon-file'
}

const sourceText = computed(() => {
  const key = `fileCenter.sources.${props.source}`
  return te(key) ? t(key) : props.source
})

/** 缩略图加载失败后回退为类型图标 */
const thumbFailed = ref(false)
const canUseThumb = computed(
  () => !props.isFolder && !!props.url && isImageName(props.name) && !thumbFailed.value,
)
const iconName = computed(() => (props.isFolder ? 'icon-folder' : fileIconName(props.name)))
</script>

<template>
  <AppCard class="file-card" variant="surface" interactive>
    <template #media>
      <div class="file-card__media">
        <img
          v-if="canUseThumb"
          :src="url as string"
          :alt="name"
          loading="lazy"
          @error="thumbFailed = true"
        />
        <component :is="iconName" v-else class="file-card__icon" :class="{ 'is-folder': isFolder }" />
      </div>
    </template>
    <template #title>
      <span class="file-card__name" :title="name">{{ name }}</span>
    </template>
    <template #meta>
      <span class="file-card__source">{{ sourceText }}</span>
    </template>
    <template v-if="showOps" #actions>
      <AppButton
        variant="ghost"
        size="mini"
        icon-only
        :title="t('fileCenter.rename')"
        @click="emit('rename')"
      >
        <template #icon><icon-edit /></template>
      </AppButton>
      <AppButton
        variant="ghost"
        size="mini"
        icon-only
        :title="t('fileCenter.move')"
        @click="emit('move')"
      >
        <template #icon><icon-relation /></template>
      </AppButton>
      <AppButton
        variant="ghost"
        size="mini"
        icon-only
        status="danger"
        :title="t('fileCenter.delete')"
        @click="emit('delete')"
      >
        <template #icon><icon-delete /></template>
      </AppButton>
    </template>
  </AppCard>
</template>

<style scoped>
.file-card__media {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  aspect-ratio: 4 / 3;
}

.file-card__media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.file-card__icon {
  font-size: 34px;
  color: var(--aicss-muted);
}

.file-card__icon.is-folder {
  color: var(--aicss-accent);
}

.file-card__name {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-card__source {
  align-self: flex-start;
  font-size: 11px;
  line-height: 1.5;
  padding: 0 8px;
  border-radius: 999px;
  color: var(--aicss-accent-text);
  background: var(--aicss-accent-soft);
}
</style>
