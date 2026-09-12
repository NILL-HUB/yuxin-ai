<template>
  <img :src="imageUrl" :alt="alt" :width="size" :height="size" :class="className" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import xiaoyuFull from '@/assets/images/xiaoyu.png'
import xiaoyuCharacter from '@/assets/images/xiaoyu_character.png'
import xiaoyuMini from '@/assets/images/xiaoyu_mini.png'

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
      return xiaoyuCharacter
    case 'mini':
      return xiaoyuMini
    case 'full':
    default:
      return xiaoyuFull
  }
})

const alt = computed(() => {
  switch (props.type) {
    case 'character':
      return '小钰 Character'
    case 'mini':
      return '小钰 Mini'
    case 'full':
    default:
      return '小钰'
  }
})
</script>
