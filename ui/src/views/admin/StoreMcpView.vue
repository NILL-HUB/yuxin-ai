<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import StoreMcpListView from '@/views/store/mcp/ListView.vue'

const { t } = useI18n()

/**
 * 在新标签页中以用户视角预览 MCP 商店（用户端路由 store/mcp）。
 */
const handlePreviewStore = () => {
  window.open('/store/mcp', '_blank')
}
</script>

<template>
  <div class="relative h-full">
    <a-tooltip :content="t('admin.storeOps.previewStoreTip')" position="bl" class="absolute right-4 top-4 z-10">
      <a-button :data-testid="'store-preview-mcp'" @click="handlePreviewStore">
        <template #icon>
          <icon-eye />
        </template>
        {{ t('admin.storeOps.previewStore') }}
      </a-button>
    </a-tooltip>
    <StoreMcpListView :hide-create="true" :admin-mode="true" />
  </div>
</template>