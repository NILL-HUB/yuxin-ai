import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Button, Tabs } from '@arco-design/web-vue'
import ListView from '../ListView.vue'
import { listAllFileCenterFiles, listFileCenterEntries } from '@/services/file-center'

vi.mock('@/services/file-center', () => ({
  listFileCenterEntries: vi.fn(),
  createFileCenterFolder: vi.fn(),
  updateFileCenterEntry: vi.fn(),
  deleteFileCenterEntry: vi.fn(),
  listAllFileCenterFiles: vi.fn(),
  importFileCenterUpload: vi.fn(),
}))

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
  components: { 'a-button': Button, 'a-tabs': Tabs, 'a-tab-pane': Tabs.TabPane },
  stubs: {
    'a-spin': { template: '<div><slot /></div>' },
    'a-modal': { props: ['visible'], template: '<div v-if="visible"><slot /></div>' },
    'a-input': true,
    'a-select': true,
    'a-option': true,
    'a-pagination': true,
    'icon-home': true,
    'icon-folder-add': true,
    'icon-refresh': true,
    'icon-folder': true,
    'icon-edit': true,
    'icon-relation': true,
    'icon-delete': true,
    'icon-file': true,
    'icon-file-image': true,
    'icon-file-pdf': true,
  },
}

const entryFolder = {
  id: 'f1',
  parent_id: null,
  name: '资料夹',
  is_folder: true,
  upload_file_id: null,
  source: 'upload',
  origin: null,
  url: null,
}

const entryFile = {
  id: 'e1',
  parent_id: null,
  name: '报告.pdf',
  is_folder: false,
  upload_file_id: 'u1',
  source: 'artifact',
  origin: null,
  url: 'https://example.com/1',
}

const entryUnknownSource = {
  ...entryFile,
  id: 'e2',
  name: '未知来源.bin',
  source: 'custom_source',
}

describe('space/files/ListView.vue', () => {
  beforeEach(() => {
    vi.mocked(listFileCenterEntries).mockReset()
    vi.mocked(listAllFileCenterFiles).mockReset()
  })

  it('renders folder and file cards with source labels', async () => {
    vi.mocked(listFileCenterEntries).mockResolvedValue({
      items: [entryFolder, entryFile],
      parent_id: null,
    })

    const wrapper = mount(ListView, { global: globalOptions })
    await flushPromises()

    expect(wrapper.text()).toContain('资料夹')
    expect(wrapper.text()).toContain('报告.pdf')
    expect(wrapper.text()).toContain('fileCenter.sources.artifact')
  })

  it('falls back to raw source value for unknown source keys', async () => {
    vi.mocked(listFileCenterEntries).mockResolvedValue({
      items: [entryUnknownSource],
      parent_id: null,
    })

    const wrapper = mount(ListView, { global: globalOptions })
    await flushPromises()

    expect(wrapper.text()).toContain('custom_source')
    expect(wrapper.text()).not.toContain('fileCenter.sources.custom_source')
  })

  it('shows guided empty state with hint when folder is empty', async () => {
    vi.mocked(listFileCenterEntries).mockResolvedValue({ items: [], parent_id: null })

    const wrapper = mount(ListView, { global: globalOptions })
    await flushPromises()

    expect(wrapper.text()).toContain('fileCenter.emptyBrowseHint')
  })

  it('enters folder on card click with parent_id', async () => {
    vi.mocked(listFileCenterEntries).mockResolvedValue({
      items: [entryFolder],
      parent_id: null,
    })

    const wrapper = mount(ListView, { global: globalOptions })
    await flushPromises()

    await wrapper.find('.file-card').trigger('click')
    await flushPromises()

    expect(listFileCenterEntries).toHaveBeenCalledTimes(2)
    expect(vi.mocked(listFileCenterEntries).mock.calls[1][0]).toBe('f1')
  })

  it('loads all files when switching to the all tab', async () => {
    vi.mocked(listFileCenterEntries).mockResolvedValue({ items: [], parent_id: null })
    vi.mocked(listAllFileCenterFiles).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 24,
      total_pages: 0,
      total_record: 0,
    })

    const wrapper = mount(ListView, { global: globalOptions })
    await flushPromises()

    wrapper.findComponent(Tabs).vm.$emit('update:activeKey', 'all')
    await flushPromises()

    expect(listAllFileCenterFiles).toHaveBeenCalled()
  })
})
