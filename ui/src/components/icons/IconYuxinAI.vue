<template>
  <img :src="imageUrl" :alt="alt" :width="size" :height="size" :class="className" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import yuxinAIFull from '@/assets/images/yuxin_ai.png'
import yuxinAICharacter from '@/assets/images/yuxin_ai_character.png'
import yuxinAIMini from '@/assets/images/yuxin_ai_mini.png'

interface Props {
  type?: 'character' | 'mini' | 'full'
  size?: number
  className?: string
}

const props = withDefaults(defineProps<Props>(), {
  type: 'full',
  size: 24,
  className: '',
})

const imageUrl = computed(() => {
  switch (props.type) {
    case 'character':
      return yuxinAICharacter
    case 'mini':
      return yuxinAIMini
    case 'full':
    default:
      return yuxinAIFull
  }
})

const alt = computed(() => {
  switch (props.type) {
    case 'character':
      return '钰心AI Character'
    case 'mini':
      return '钰心AI Mini'
    case 'full':
    default:
      return '钰心AI'
  }
})
</script>
