<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import moment from 'moment'
import type { MemoryDetail } from '@/models/memory-graph'

const props = defineProps<{
  detail: MemoryDetail | null
  loading?: boolean
  decaySaving?: boolean
}>()

const emit = defineEmits<{
  (e: 'edit'): void
  (e: 'soft-delete'): void
  (e: 'hard-delete'): void
  (e: 'decay', factor: number): void
  (e: 'select-related', nodeId: string): void
}>()

const { t } = useI18n()

const hasDetail = computed(() => props.detail && props.detail.memory_id)

// 降权滑杆（本地态；点击应用后把因子抛给父组件执行）
const decayFactor = ref(0.5)
const decayPreview = computed(() => {
  const base = props.detail?.weight !== undefined ? props.detail.weight : null
  if (base === null) return 0.5
  return Math.max(0, Math.min(1, base * (1 - decayFactor.value)))
})
const applyDecay = () => {
  emit('decay', Math.round(decayFactor.value * 100) / 100)
}

const typeLabel = (type?: string) => {
  if (!type) return '-'
  const key = `memory.memoryType.${type}`
  const translated = t(key)
  return translated === key ? type : translated
}

// 置信度展示：兼容 0-1 与 0-100 两种后端标度
const formatConfidence = (value?: number) => {
  if (value === undefined || value === null || Number.isNaN(value)) return ''
  const v = Math.abs(value) > 1 ? value : value * 100
  return `${Math.round(v)}%`
}

const formatTime = (value?: string) => {
  if (!value) return '-'
  const date = moment(value)
  return date.isValid() ? date.format('MM-DD HH:mm') : value
}

const timeAgo = (value?: string) => {
  if (!value) return '-'
  const diff = moment().diff(moment(value), 'hour')
  if (diff < 1) return '刚刚更新'
  if (diff < 24) return `${diff} 小时前`
  const days = moment().diff(moment(value), 'day')
  if (days < 30) return `${days} 天前`
  return formatTime(value)
}

// 关联节点文案（没有内容只有 id 时截断 id）
const relatedLabel = (id: string) => {
  if (id.length > 18) return `${id.slice(0, 10)}…${id.slice(-4)}`
  return id
}

const handleEdit = () => emit('edit')
const handleSoftDelete = () => emit('soft-delete')
const handleHardDelete = () => emit('hard-delete')
const handleSelectRelated = (nodeId: string) => emit('select-related', nodeId)
</script>

<template>
  <div class="detail-shell flex h-full flex-col p-5">
    <!-- 空态 -->
    <div
      v-if="!loading && !hasDetail"
      class="flex flex-1 flex-col items-center justify-center py-16 text-center text-muted"
    >
      <span class="detail-empty-ico"><icon-bookmark /></span>
      <p class="mt-3 text-sm font-medium text-text-2">记忆详情</p>
      <p class="mt-1 text-xs">{{ t('memory.graph.selectNodeHint') }}</p>
    </div>

    <a-spin v-else :loading="loading" class="block flex-1">
      <!-- 详情 -->
      <div v-if="hasDetail" class="flex h-full flex-col">
        <!-- 头部：标题 + 类型胶囊 -->
        <div class="flex items-start justify-between gap-3">
          <div>
            <h3 class="detail-title text-lg font-bold tracking-tight">记忆详情</h3>
            <p class="mt-1 text-xs text-muted">{{ typeLabel(detail!.memory_type) }}<template v-if="detail!.confidence !== undefined && detail!.confidence !== null"> · {{ formatConfidence(detail!.confidence) }} 置信</template></p>
          </div>
          <span class="detail-type-pill" :class="detail!.weight && detail!.weight > 0.7 ? 'pill-hot' : detail!.weight && detail!.weight > 0.35 ? 'pill-warm' : 'pill-cold'">
            <span class="pill-dot"></span>
            {{ detail!.weight && detail!.weight > 0.7 ? 'HOT' : detail!.weight && detail!.weight > 0.35 ? 'WARM' : 'COLD' }}
          </span>
        </div>

        <!-- 记忆内容 -->
        <div class="detail-content mt-4">
          <p class="text-sm leading-relaxed text-text-2">{{ detail!.content }}</p>
        </div>

        <!-- 元信息行 -->
        <div class="mt-4 space-y-2.5 text-xs text-muted">
          <p class="flex items-center gap-2">
            <icon-message class="detail-meta-ico shrink-0" />
            来源：{{ detail!.source_conversation_id ? `对话 ${detail!.source_conversation_id.slice(0, 8)}` : '对话沉淀' }}
          </p>
          <p class="flex items-center gap-2">
            <icon-clock-circle class="detail-meta-ico shrink-0" />
            更新于 {{ timeAgo(detail!.last_accessed_at || detail!.created_at) }}
          </p>
          <p v-if="detail!.created_at" class="flex items-center gap-2">
            <icon-schedule class="detail-meta-ico shrink-0" />
            创建于 {{ formatTime(detail!.created_at) }}
          </p>
          <p class="flex items-center gap-2">
            <icon-safe class="detail-meta-ico shrink-0" />
            权重：<span class="detail-weight">{{ (detail!.weight ?? 0).toFixed(2) }}</span>
          </p>
        </div>

        <!-- 降权内联滑杆 -->
        <div class="detail-decay mt-4 rounded-[var(--aicss-radius-sm)] bg-surface-2 p-3">
          <div class="flex items-center justify-between text-xs">
            <span class="flex items-center gap-1.5 text-muted">
              <icon-minus-circle class="detail-meta-ico" />
              手动降权
            </span>
            <span class="font-mono text-text">{{ decayPreview.toFixed(2) }}</span>
          </div>
          <input
            v-model.number="decayFactor"
            type="range"
            min="0"
            max="0.9"
            step="0.05"
            aria-label="记忆降权强度"
            class="detail-range mt-2"
          />
          <button
            type="button"
            class="detail-decay-btn mt-2"
            :class="{ 'is-loading': decaySaving }"
            :disabled="decaySaving || decayFactor === 0"
            @click="applyDecay"
          >
            <icon-down v-if="!decaySaving" class="detail-btn-ico" />
            {{ decaySaving ? '降权中…' : '应用降权' }}
          </button>
        </div>

        <!-- 关联记忆 -->
        <div v-if="detail!.related && detail!.related.length > 0" class="mt-4">
          <div class="mb-2 text-xs font-medium text-muted">{{ t('memory.graph.relatedLabel') }}</div>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="(rel, idx) in (detail!.related || []).slice(0, 6)"
              :key="idx"
              type="button"
              class="related-chip"
              @click="handleSelectRelated(rel.node_id)"
            >
              {{ relatedLabel(rel.node_id) }}
              <span class="related-w">w{{ rel.weight?.toFixed(2) ?? '-' }}</span>
            </button>
          </div>
        </div>

        <!-- 底部操作组 -->
        <div class="mt-auto space-y-2 border-t border-border pt-4" style="margin-top: auto">
          <button type="button" class="detail-action" @click="handleEdit">
            <icon-edit class="detail-btn-ico" />
            编辑记忆
          </button>
          <button type="button" class="detail-action" @click="handleSoftDelete">
            <icon-delete class="detail-btn-ico" />
            删除（进入回收站）
          </button>
          <button type="button" class="detail-action detail-action-danger" @click="handleHardDelete">
            <icon-delete class="detail-btn-ico" />
            彻底删除
          </button>
        </div>
      </div>
    </a-spin>
  </div>
</template>

<style scoped>
/* ============================================================
   记忆详情面板 · 粉色自绘（对齐原型 memory.html 右侧面板）
   ============================================================ */
.detail-title {
  color: var(--aicss-text);
  font-family: var(--aicss-font-serif, Georgia, 'Songti SC', serif);
  letter-spacing: -0.01em;
}
.detail-empty-ico {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent);
  font-size: 28px;
}
.detail-empty-ico :deep(svg) {
  width: 28px;
  height: 28px;
}

/* 类型胶囊 */
.detail-type-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.pill-hot {
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
}
.pill-warm {
  background: var(--aicss-surface-2);
  color: var(--aicss-text-2);
}
.pill-cold {
  background: var(--aicss-bg-subtle);
  color: var(--aicss-muted);
}
.pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

/* 内容 */
.detail-content {
  padding: 12px 14px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-bg-subtle);
}
.detail-content p {
  color: var(--aicss-text-2);
  line-height: 1.75;
}

.detail-meta-ico {
  color: var(--aicss-accent);
  font-size: 13px;
}
.detail-meta-ico :deep(svg) {
  width: 13px;
  height: 13px;
}
.detail-weight {
  color: var(--aicss-accent-text);
  font-family: var(--aicss-font-mono, ui-monospace, monospace);
  font-weight: 700;
}

/* 降权 */
.detail-decay {
  border: 1px solid var(--aicss-border);
}
.detail-range {
  display: block;
  width: 100%;
  height: 6px;
  appearance: none;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--aicss-accent), var(--aicss-accent-soft));
  outline: none;
  cursor: pointer;
}
.detail-range::-webkit-slider-thumb {
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  border: 3px solid var(--aicss-accent);
  box-shadow: 0 1px 4px rgba(233, 30, 99, 0.4);
  cursor: pointer;
}
.detail-range::-moz-range-thumb {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #fff;
  border: 3px solid var(--aicss-accent);
  cursor: pointer;
}
.detail-decay-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 13px;
  border: none;
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent-text);
  font-size: 12px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition:
    background 0.2s ease,
    opacity 0.2s ease;
}
.detail-decay-btn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--aicss-accent) 20%, transparent);
}
.detail-decay-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 关联记忆 chips */
.related-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 170px;
  padding: 5px 11px;
  border: 1px solid var(--aicss-border);
  border-radius: 999px;
  background: var(--aicss-surface);
  color: var(--aicss-text-2);
  font-size: 11px;
  font-family: var(--aicss-font-mono, ui-monospace, monospace);
  cursor: pointer;
  transition:
    border-color 0.2s ease,
    background 0.2s ease;
}
.related-chip:hover {
  border-color: var(--aicss-accent);
  background: var(--aicss-accent-soft);
}
.related-w {
  color: var(--aicss-muted);
}

/* 操作按钮 */
.detail-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  width: 100%;
  height: 36px;
  border: 1px solid var(--aicss-border);
  border-radius: var(--aicss-radius-sm);
  background: var(--aicss-surface);
  color: var(--aicss-text);
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition:
    border-color 0.2s ease,
    background 0.2s ease,
    color 0.2s ease;
}
.detail-action:hover {
  border-color: var(--aicss-border-strong);
  background: var(--aicss-bg-subtle);
}
.detail-action-danger {
  border-color: transparent;
  background: linear-gradient(135deg, #e8456f, #c2185b);
  color: #fff;
}
.detail-action-danger:hover {
  background: linear-gradient(135deg, #d63a63, #ad1457);
  border-color: transparent;
}
.detail-btn-ico {
  font-size: 14px;
}
.detail-btn-ico :deep(svg) {
  width: 14px;
  height: 14px;
}
</style>
