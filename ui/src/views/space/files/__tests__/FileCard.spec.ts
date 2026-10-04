import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { Button, Tag } from '@arco-design/web-vue'
import FileCard from '../components/FileCard.vue'

const knownSources = ['upload', 'artifact', 'render_output', 'platform']
vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
    te: (key: string) => {
      const match = /^fileCenter\.sources\.(.+)$/.exec(key)
      return match ? knownSources.includes(match[1]) : true
    },
  }),
}))

const globalOptions = {
  components: { 'a-button': Button, 'a-tag': Tag },
  stubs: {
    'icon-edit': true,
    'icon-relation': true,
    'icon-delete': true,
    'icon-folder': true,
    'icon-file': true,
    'icon-file-image': true,
    'icon-file-pdf': true,
  },
}

describe('space/files/FileCard.vue', () => {
  it('renders folder card with accent folder icon, name and source label', () => {
    const wrapper = mount(FileCard, {
      props: { name: '产物', isFolder: true, source: 'artifact' },
      global: globalOptions,
    })

    expect(wrapper.text()).toContain('产物')
    expect(wrapper.text()).toContain('fileCenter.sources.artifact')
    expect(wrapper.find('.file-card__icon.is-folder').exists()).toBe(true)
  })

  it('falls back to icon (not folder style) for files without preview', () => {
    const wrapper = mount(FileCard, {
      props: { name: '报告.pdf', url: 'https://example.com/1' },
      global: globalOptions,
    })

    expect(wrapper.find('.file-card__icon').exists()).toBe(true)
    expect(wrapper.find('.file-card__icon.is-folder').exists()).toBe(false)
    expect(wrapper.find('.file-card__media img').exists()).toBe(false)
  })

  it('renders image thumbnail for image files with url', () => {
    const wrapper = mount(FileCard, {
      props: { name: '照片.png', url: 'https://example.com/a.png' },
      global: globalOptions,
    })

    const img = wrapper.find('.file-card__media img')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toBe('https://example.com/a.png')
  })

  it('falls back to type icon when thumbnail fails to load', async () => {
    const wrapper = mount(FileCard, {
      props: { name: '照片.png', url: 'https://example.com/a.png' },
      global: globalOptions,
    })

    await wrapper.find('.file-card__media img').trigger('error')

    expect(wrapper.find('.file-card__media img').exists()).toBe(false)
    expect(wrapper.find('.file-card__icon').exists()).toBe(true)
  })

  it('falls back to raw source value for unknown source keys', () => {
    const wrapper = mount(FileCard, {
      props: { name: 'x.bin', source: 'custom_source' },
      global: globalOptions,
    })

    expect(wrapper.text()).toContain('custom_source')
    expect(wrapper.text()).not.toContain('fileCenter.sources.custom_source')
  })

  it('emits rename/move/delete from hover actions', async () => {
    const wrapper = mount(FileCard, { props: { name: 'a.txt' }, global: globalOptions })

    const buttons = wrapper.findAll('.app-card__actions button')
    expect(buttons.length).toBe(3)

    await buttons[0].trigger('click')
    await buttons[1].trigger('click')
    await buttons[2].trigger('click')

    expect(wrapper.emitted('rename')).toHaveLength(1)
    expect(wrapper.emitted('move')).toHaveLength(1)
    expect(wrapper.emitted('delete')).toHaveLength(1)
  })

  it('hides actions when showOps is false', () => {
    const wrapper = mount(FileCard, {
      props: { name: 'a.txt', showOps: false },
      global: globalOptions,
    })

    expect(wrapper.find('.app-card__actions').exists()).toBe(false)
  })
})
