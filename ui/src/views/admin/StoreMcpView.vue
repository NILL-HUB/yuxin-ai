<script setup lang="ts">
import StoreMcpListView from '@/views/store/mcp/ListView.vue'
import StoreUnsupportedView from './StoreUnsupportedView.vue'
</script>

<template>
  <StoreUnsupportedView>
    <StoreMcpListView :hide-create="true" />
  </StoreUnsupportedView>
</template>
