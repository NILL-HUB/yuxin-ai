import { beforeEach, describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import StoreSkillsView from '@/views/admin/StoreSkillsView.vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => {
      const map: Record<string, string> = {
        'admin.storeOps.previewStore': '预览商店效果',
        'admin.storeOps.previewStoreTip': '在新标签页中以用户视角预览商店',
      }
      return map[key] ?? key
    },
  }),
}))

const globalStubs = {
  'store-skills-list-view': { template: '<div class="skills-list" />' },
  'store-unsupported-view': { template: '<div><slot /></div>' },
  'a-tooltip': { template: '<span><slot /></span>' },
  'a-button': {
    emits: ['click'],
    template: '<button type="button" @click="$emit(\'click\')"><slot /></button>',
  },
  'icon-eye': { template: '<span />' },
}

describe('StoreSkillsView 商店预览（UX-8）', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    window.open = vi.fn()
  })

  it('renders 预览商店效果 button and opens the user-facing skills store', async () => {
    const wrapper = shallowMount(StoreSkillsView, {
      global: { stubs: globalStubs },
    })

    const previewButton = wrapper.find('[data-testid="store-preview-skills"]')
    expect(previewButton.exists()).toBe(true)

    await previewButton.trigger('click')
    expect(window.open).toHaveBeenCalledWith('/store/skills', '_blank')
  })
})