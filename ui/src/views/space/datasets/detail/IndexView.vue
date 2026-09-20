<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useGetKnowledgeBase } from '@/hooks/use-knowledge-base'
import UsagePanel from './components/UsagePanel.vue'
import PartitionTreeNav from './components/PartitionTreeNav.vue'
import MaterialGrid from './components/MaterialGrid.vue'
import MaterialDetailDrawer from './components/MaterialDetailDrawer.vue'

const route = useRoute()
const knowledgeBaseId = computed(() => String(route.params.dataset_id ?? ''))

const { knowledgeBase: dataset, loadKnowledgeBase } = useGetKnowledgeBase()
if (knowledgeBaseId.value) void loadKnowledgeBase(knowledgeBaseId.value)

const currentPartition = ref('')
const drawerDocId = ref<string | null>(null)
const drawerVisible = ref(false)

const openDocument = (documentId: string) => {
  drawerDocId.value = documentId
  drawerVisible.value = true
}

const onDeleted = () => {
  drawerVisible.value = false
}
</script>

<template>
  <div class="scrollbar-w-none m-auto flex h-full w-full max-w-7xl min-h-0 flex-col gap-4 overflow-y-auto px-6 py-6 pb-10">
    <div class="flex items-center justify-between">
      <router-link :to="{ name: 'my-knowledge' }">
        <a-button size="mini" type="text" class="!text-text-2">
          <template #icon><icon-left /></template>
          <span class="max-w-[320px] truncate">{{ dataset.name || '' }}</span>
        </a-button>
      </router-link>
    </div>

    <UsagePanel />

    <div class="grid min-h-0 flex-1 grid-cols-[220px_minmax(0,1fr)] gap-4 overflow-hidden rounded-2xl border border-border-c bg-surface shadow-sm">
      <aside class="min-h-0 overflow-y-auto border-r border-border-c pt-2">
        <PartitionTreeNav :knowledge-base-id="knowledgeBaseId" @select="currentPartition = $event" />
      </aside>
      <section class="min-h-0 p-4">
        <MaterialGrid
          :knowledge-base-id="knowledgeBaseId"
          :partition-id="currentPartition"
          @open="openDocument"
        />
      </section>
    </div>

    <MaterialDetailDrawer
      v-model:visible="drawerVisible"
      :knowledge-base-id="knowledgeBaseId"
      :document-id="drawerDocId"
      @deleted="onDeleted"
    />
  </div>
</template>