<script setup lang="ts">
import { ref } from 'vue'
import MemoryView from '@/views/settings/MemoryView.vue'

const navItems = [
  { key: 'memory', label: '长期记忆' },
  { key: 'profile', label: '个人信息' },
  { key: 'notification', label: '通知设置' },
]

const activeKey = ref('memory')
</script>

<template>
  <div class="mx-auto flex max-w-6xl gap-6 px-6 py-6">
    <nav class="w-44 flex-shrink-0">
      <ul class="flex flex-col gap-1">
        <li
          v-for="item in navItems"
          :key="item.key"
          :class="`cursor-pointer rounded-lg px-3 py-2 text-sm transition-colors ${activeKey === item.key ? 'bg-gray-100 font-medium text-gray-900' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'}`"
          @click="activeKey = item.key"
        >
          {{ item.label }}
        </li>
      </ul>
    </nav>
    <main class="min-w-0 flex-1">
      <MemoryView v-if="activeKey === 'memory'" />
      <div
        v-else
        class="flex flex-col items-center justify-center rounded-lg border border-dashed bg-white py-20 text-gray-400"
      >
        {{ navItems.find((item) => item.key === activeKey)?.label }} · 即将上线
      </div>
    </main>
  </div>
</template>
