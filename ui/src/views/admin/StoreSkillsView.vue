<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import StoreSkillsListView from '@/views/store/skills/ListView.vue'
import StoreUnsupportedView from './StoreUnsupportedView.vue'

const { t } = useI18n()

/**
 * 在新标签页中以用户视角预览技能商店（用户端路由 store/skills）。
 */
const handlePreviewStore = () => {
  window.open('/store/skills', '_blank')
}
</script>

<template>
  <div class="relative h-full">
    <a-tooltip :content="t('admin.storeOps.previewStoreTip')" position="bl" class="absolute right-4 top-4 z-10">
      <a-button :data-testid="'store-preview-skills'" @click="handlePreviewStore">
        <template #icon>
          <icon-eye />
        </template>
        {{ t('admin.storeOps.previewStore') }}
      </a-button>
    </a-tooltip>
    <StoreUnsupportedView>
      <StoreSkillsListView :admin-mode="true" />
    </StoreUnsupportedView>
  </div>
</template>