<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useTheme } from '@/theme'

const { t } = useI18n()
const { isDark, toggleTheme } = useTheme()
</script>

<template>
  <button
    type="button"
    class="relative inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--aicss-radius)] border border-[var(--aicss-border)] bg-[var(--aicss-surface)] text-[var(--aicss-muted)] transition hover:border-[var(--aicss-border-strong)] hover:text-[var(--aicss-accent)] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-[var(--aicss-accent)]"
    :title="isDark ? t('theme.switchToLight') : t('theme.switchToDark')"
    :aria-label="isDark ? t('theme.switchToLight') : t('theme.switchToDark')"
    @click="toggleTheme"
  >
    <!-- 亮色主题显示月亮（提示可切换暗色）；暗色主题显示太阳 -->
    <icon-moon-fill v-if="!isDark" class="text-base" />
    <icon-sun-fill v-else class="text-base" />
  </button>
</template>
