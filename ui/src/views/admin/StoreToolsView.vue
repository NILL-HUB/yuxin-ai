<script setup lang="ts">
import StoreToolsListView from '@/views/store/tools/ListView.vue'
import StoreUnsupportedView from './StoreUnsupportedView.vue'
</script>

<template>
  <StoreUnsupportedView>
    <StoreToolsListView :hide-create="true" />
  </StoreUnsupportedView>
</template>
