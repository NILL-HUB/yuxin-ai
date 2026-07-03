<script setup lang="ts">
import { useI18n } from 'vue-i18n'

/**
 * 资源运营-不支持商店上下架的资源类型包装组件，在公共商店组件上方展示提示。
 */
const { t } = useI18n()
</script>

<template>
  <div class="flex h-full flex-col">
    <a-alert type="info" :show-icon="true" class="mx-6 mt-6">
      {{ t('admin.storeOps.unsupportedNotice') }}
    </a-alert>
    <div class="min-h-0 flex-1">
      <slot />
    </div>
  </div>
</template>
