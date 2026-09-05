<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import AppStoreOverview from './components/AppStoreOverview.vue'
import PublicPreviewDebugChat from './components/PublicPreviewDebugChat.vue'

const route = useRoute()
const { t } = useI18n()
const props = defineProps({
  app: {
    type: Object,
    default: () => ({}),
    required: true,
  },
})

const draftAppConfigForm = computed(() => props.app?.draft_app_config || {})
</script>

<template>
  <div class="flex h-full min-h-0 w-full flex-col overflow-hidden bg-surface-2">
    <div class="flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
      <div class="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface lg:border-r lg:border-border-c">
        <div class="flex h-12 shrink-0 items-center gap-2 border-b border-border-c px-4">
          <icon-info-circle class="text-base text-muted" />
          <div class="text-sm font-medium text-text-2">
            {{ t('publicApps.preview.overview') }}
          </div>
        </div>
        <div class="min-h-0 flex-1 overflow-hidden">
          <app-store-overview :app="props.app" />
        </div>
      </div>

      <div class="flex min-h-0 flex-col overflow-hidden border-t border-border-c bg-surface lg:w-[420px] lg:shrink-0 lg:border-t-0">
        <div class="flex h-12 shrink-0 items-center gap-2 border-b border-border-c px-4">
          <icon-message class="text-base text-muted" />
          <div class="truncate text-sm font-medium text-text-2">
            {{ t('publicApps.preview.chatWithApp', { name: props.app?.name || '' }) }}
          </div>
        </div>
        <div class="min-h-0 flex-1 overflow-hidden">
          <public-preview-debug-chat
            class="h-full"
            :suggested_after_answer="draftAppConfigForm.suggested_after_answer"
            :opening_questions="draftAppConfigForm.opening_questions || []"
            :opening_statement="draftAppConfigForm.opening_statement || ''"
            :text_to_speech="draftAppConfigForm.text_to_speech"
            :app="props.app"
            :app_id="String(route.params?.app_id)"
          />
        </div>
      </div>
    </div>
  </div>
</template>
