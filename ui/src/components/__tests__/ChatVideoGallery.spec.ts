import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import ChatVideoGallery from '../ChatVideoGallery.vue'

const mountGallery = (videos: Array<Record<string, unknown>> = []) =>
  mount(ChatVideoGallery, {
    props: { videos },
    global: {
      mocks: {
        $t: (key: string, params?: Record<string, unknown>) =>
          params ? `${key}:${JSON.stringify(params)}` : key,
      },
    },
  })

describe('ChatVideoGallery.vue', () => {
  it('renders nothing when there are no videos', () => {
    const wrapper = mountGallery([])
    expect(wrapper.find('.chat-video-gallery').exists()).toBe(false)
  })

  it('renders an inline player for a video artifact', () => {
    const wrapper = mountGallery([
      { name: '成片', url: 'https://cdn.example.com/a.mp4', mime_type: 'video/mp4' },
    ])

    const player = wrapper.get('.chat-video-card__player')
    expect(player.attributes('src')).toBe('https://cdn.example.com/a.mp4')
    // controls + playsinline：没有 controls 用户无法播放
    expect(player.attributes('controls')).toBeDefined()
    expect(wrapper.text()).toContain('成片')
  })

  it('renders one card per video', () => {
    const wrapper = mountGallery([
      { name: 'A', url: 'https://cdn.example.com/a.mp4' },
      { name: 'B', url: 'https://cdn.example.com/b.mp4' },
    ])

    expect(wrapper.findAll('.chat-video-card__player')).toHaveLength(2)
  })

  it('skips entries without a url', () => {
    const wrapper = mountGallery([
      { name: '坏数据', url: '' },
      { name: 'A', url: 'https://cdn.example.com/a.mp4' },
    ])

    expect(wrapper.findAll('.chat-video-card__player')).toHaveLength(1)
  })

  it('shows a fallback with a direct link when playback errors', async () => {
    const wrapper = mountGallery([{ name: '成片', url: 'https://cdn.example.com/a.mp4' }])

    await wrapper.get('.chat-video-card__player').trigger('error')

    expect(wrapper.find('.chat-video-card__player').exists()).toBe(false)
    const fallbackLink = wrapper.get('.chat-video-card__fallback-link')
    expect(fallbackLink.attributes('href')).toBe('https://cdn.example.com/a.mp4')
  })

  it('exposes a download button per video', () => {
    const wrapper = mountGallery([{ name: '成片', url: 'https://cdn.example.com/a.mp4' }])

    const button = wrapper.get('.chat-video-card__download')
    expect(button.attributes('data-download-filename')).toBe('成片.mp4')
  })
})
