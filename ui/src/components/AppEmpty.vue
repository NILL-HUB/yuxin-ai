<script setup lang="ts">
/**
 * 空状态基座：页面/区块「暂无内容」的统一表达。
 *
 * 各板块通过 icon / title / hint / actions 插槽自定义内容，尺寸与配色统一走 token；
 * 调用方无需再逐处写空状态容器样式。
 */
withDefaults(
  defineProps<{
    title?: string
    hint?: string
    /** page 整页/整区块（大图标）；inline 卡片/列表内嵌（紧凑） */
    variant?: 'page' | 'inline'
  }>(),
  { title: '', hint: '', variant: 'page' },
)
</script>

<template>
  <div class="app-empty" :class="`app-empty--${variant}`">
    <div v-if="$slots.icon" class="app-empty__icon">
      <slot name="icon" />
    </div>
    <p v-if="title" class="app-empty__title">{{ title }}</p>
    <p v-if="hint" class="app-empty__hint">{{ hint }}</p>
    <slot />
    <div v-if="$slots.actions" class="app-empty__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.app-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  text-align: center;
}

.app-empty--page {
  padding: 56px 16px;
}

.app-empty--inline {
  padding: 24px 12px;
  gap: 6px;
}

.app-empty__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  margin-bottom: 4px;
  border-radius: 50%;
  background: var(--aicss-accent-soft);
  color: var(--aicss-accent);
  font-size: 30px;
}

.app-empty--inline .app-empty__icon {
  width: 44px;
  height: 44px;
  font-size: 22px;
}

.app-empty__title {
  margin: 0;
  font-size: 15px;
  font-weight: 500;
  color: var(--aicss-text);
}

.app-empty--inline .app-empty__title {
  font-size: 13px;
}

.app-empty__hint {
  margin: 0;
  max-width: 420px;
  font-size: 13px;
  color: var(--aicss-muted);
}

.app-empty--inline .app-empty__hint {
  font-size: 12px;
}

.app-empty__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
</style>
