<script setup lang="ts">
/**
 * 卡片基座：可复用卡片容器，供各板块派生出不同风格的业务卡片。
 *
 * 设计约定（见 AGENTS.md「前端组件抽象与主题规范」）：
 * - 统一的是抽象与封装：业务卡片（如 FileCard）基于本基座组合，不应在页面内裸写卡片样式；
 * - 允许样式多样：不同板块的业务卡片可有各自视觉（通过 variant / 插槽内容 / 局部样式扩展）；
 * - 颜色与圆角一律来自主题 token（--aicss-*）。
 */
withDefaults(
  defineProps<{
    /** surface 面板底 / outline 仅描边 / plain 无容器 */
    variant?: 'surface' | 'outline' | 'plain'
    /** 可交互（可点击）：hover 抬升 + 指针 */
    interactive?: boolean
    /** 选中态高亮 */
    selected?: boolean
    /** 操作区显隐：hover 出现（默认）或常显 */
    actionsVisible?: 'hover' | 'always'
    padding?: 'none' | 'small' | 'medium'
  }>(),
  {
    variant: 'surface',
    interactive: false,
    selected: false,
    actionsVisible: 'hover',
    padding: 'small',
  },
)
</script>

<template>
  <div
    class="app-card"
    :class="[
      `app-card--${variant}`,
      `app-card--padding-${padding}`,
      { 'app-card--interactive': interactive, 'app-card--selected': selected },
    ]"
  >
    <div v-if="$slots.media" class="app-card__media">
      <slot name="media" />
    </div>
    <div class="app-card__body">
      <div v-if="$slots.title" class="app-card__title">
        <slot name="title" />
      </div>
      <div v-if="$slots.meta" class="app-card__meta">
        <slot name="meta" />
      </div>
      <slot />
    </div>
    <div
      v-if="$slots.actions"
      class="app-card__actions"
      :class="`app-card__actions--${actionsVisible}`"
      @click.stop
    >
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.app-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-radius: var(--aicss-radius-sm, 8px);
  transition: border-color 0.16s, box-shadow 0.16s, transform 0.16s;
}

.app-card--surface {
  border: 1px solid var(--aicss-border);
  background: var(--aicss-surface);
}

.app-card--outline {
  border: 1px solid var(--aicss-border);
  background: transparent;
}

.app-card--plain {
  border: none;
  background: transparent;
}

.app-card--padding-none {
  padding: 0;
}

.app-card--padding-small {
  padding: 10px;
}

.app-card--padding-medium {
  padding: 16px;
}

.app-card--interactive {
  cursor: pointer;
}

.app-card--interactive:hover {
  border-color: var(--aicss-border-strong);
  box-shadow: var(--aicss-shadow-card);
  transform: translateY(-2px);
}

.app-card--selected {
  border-color: var(--aicss-accent);
  box-shadow: var(--aicss-shadow-card);
}

/* 媒体区：基础容器（尺寸与内容由业务卡片的插槽内容决定） */
.app-card__media {
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--aicss-radius-sm, 8px);
  background: var(--aicss-bg-subtle);
  overflow: hidden;
}

.app-card__body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.app-card__title {
  font-size: 13px;
  color: var(--aicss-text);
  min-width: 0;
}

.app-card__meta {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

/* 操作区：绝对定位右上，hover 显隐由 actionsVisible 控制 */
.app-card__actions {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--aicss-border);
  border-radius: 999px;
  background: var(--aicss-surface);
  box-shadow: var(--aicss-shadow-card);
  transition: opacity 0.16s;
}

.app-card__actions--hover {
  opacity: 0;
}

.app-card:hover .app-card__actions--hover {
  opacity: 1;
}
</style>
