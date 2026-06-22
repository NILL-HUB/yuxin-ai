import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, RouterLinkStub } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AdminLayout from '@/layouts/AdminLayout.vue'
import { useAdminStore } from '@/stores/admin'

const mocks = vi.hoisted(() => ({
  adminChangePassword: vi.fn(),
  adminLogout: vi.fn(),
  routerReplace: vi.fn(),
}))

vi.mock('@/services/admin-auth', () => ({
  adminChangePassword: mocks.adminChangePassword,
  adminLogout: mocks.adminLogout,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    replace: mocks.routerReplace,
  }),
  RouterLink: RouterLinkStub,
  RouterView: { template: '<section data-test="router-view">管理内容</section>' },
}))

const buttonStub = {
  emits: ['click'],
  template: '<button type="button" @click="$emit(\'click\')"><slot /></button>',
}

const inputPasswordStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template: '<input type="password" :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const mountAdminLayout = () => mount(AdminLayout, {
  global: {
    stubs: {
      'a-button': buttonStub,
      'a-modal': { template: '<section><slot /></section>' },
      'a-form': { template: '<form><slot /></form>' },
      'a-form-item': { template: '<label><slot /></label>' },
      'a-input-password': inputPasswordStub,
      'router-link': RouterLinkStub,
      'router-view': { template: '<section data-test="router-view">管理内容</section>' },
    },
  },
})

describe('AdminLayout', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    useAdminStore().update({
      id: 'admin-1',
      username: 'admin',
      email: '',
      name: 'Root',
      avatar: '',
      status: 'active',
      roles: ['super_admin'],
      permissions: ['admin:access'],
    })
  })

  it('renders admin shell with account and router view', () => {
    const wrapper = mountAdminLayout()

    expect(wrapper.text()).toContain('OpenAgent Admin')
    expect(wrapper.text()).toContain('Root')
    expect(wrapper.find('[data-test="router-view"]').exists()).toBe(true)
  })

  it('logs out and redirects to admin login', async () => {
    mocks.adminLogout.mockResolvedValue({ data: {}, message: '退出登录成功' })
    const wrapper = mountAdminLayout()

    const logoutButton = wrapper.findAll('button').find((button) => button.text() === '退出')
    expect(logoutButton).toBeTruthy()

    await logoutButton!.trigger('click')

    expect(mocks.adminLogout).toHaveBeenCalled()
    expect(mocks.routerReplace).toHaveBeenCalledWith('/admin/login')
  })

  it('renders menu entries according to admin permissions', () => {
    useAdminStore().update({
      id: 'admin-2',
      username: 'viewer',
      email: 'viewer@example.com',
      name: 'Viewer',
      avatar: '',
      status: 'active',
      roles: ['viewer'],
      permissions: ['app:read', 'dataset:read', 'tool:read', 'mcp:read', 'skill:read', 'user:read', 'plan:read', 'redeem_code:read', 'audit_log:read'],
    })

    const wrapper = mountAdminLayout()

    expect(wrapper.text()).toContain('应用编排')
    expect(wrapper.text()).toContain('知识库管理')
    expect(wrapper.text()).toContain('API工具')
    expect(wrapper.text()).toContain('MCP管理')
    expect(wrapper.text()).toContain('Skills管理')
    expect(wrapper.text()).toContain('客户用户')
    expect(wrapper.text()).toContain('套餐卡密')
    expect(wrapper.text()).toContain('审计日志')
    expect(wrapper.text()).not.toContain('工作流编排')
    expect(wrapper.text()).not.toContain('管理员')
    expect(wrapper.text()).not.toContain('角色权限')
  })

  it('hides billing menu when redeem code read permission is missing', () => {
    useAdminStore().update({
      id: 'admin-3',
      username: 'planviewer',
      email: 'plan-viewer@example.com',
      name: 'Plan Viewer',
      avatar: '',
      status: 'active',
      roles: ['viewer'],
      permissions: ['plan:read'],
    })

    const wrapper = mountAdminLayout()

    expect(wrapper.text()).not.toContain('套餐卡密')
  })
})
