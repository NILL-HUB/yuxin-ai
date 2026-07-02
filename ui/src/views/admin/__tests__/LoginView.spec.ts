import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminLoginView from '@/views/admin/LoginView.vue'

const mocks = vi.hoisted(() => ({
  adminLogin: vi.fn(),
  routerReplace: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/admin-auth', () => ({
  adminLogin: mocks.adminLogin,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    replace: mocks.routerReplace,
  }),
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    error: mocks.messageError,
  },
}))

HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as never

const renderView = () => {
  return mount(AdminLoginView, {
    attachTo: document.body,
    global: {
      stubs: {
        AdminLoginBackground: {
          name: 'AdminLoginBackground',
          template: '<div class="admin-login-background-stub" />',
        },
        IconOpenAgent: true,
        'icon-user': true,
        'icon-lock': true,
        'icon-eye': true,
        'icon-eye-invisible': true,
        'icon-close-circle-fill': true,
      },
    },
  })
}

const submitForm = async (wrapper: ReturnType<typeof renderView>) => {
  const form = wrapper.find('form')
  await form.trigger('submit')
  await flushPromises()
}

describe('AdminLoginView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('renders redesigned admin login layout', () => {
    const wrapper = renderView()

    expect(wrapper.text()).toContain('管理控制台')
    expect(wrapper.text()).toContain('独立凭证')
    expect(wrapper.text()).toContain('权限审计')
    expect(wrapper.find('input[placeholder="输入管理员账号或邮箱"]').exists()).toBe(true)
    expect(wrapper.find('input[placeholder="输入管理员密码"]').exists()).toBe(true)
    expect(wrapper.find('.admin-login-background-stub').exists()).toBe(true)
  })

  it('disables submit button when fields are empty', () => {
    const wrapper = renderView()

    expect(wrapper.find('button.submit-btn').attributes('disabled')).toBeDefined()
  })

  it('validates required fields before login', async () => {
    const wrapper = renderView()

    await submitForm(wrapper)

    expect(mocks.adminLogin).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请输入管理员账号或邮箱和密码')
  })

  it('logs in and redirects to admin dashboard', async () => {
    mocks.adminLogin.mockResolvedValue({ data: { access_token: 'admin-token' } })
    const wrapper = renderView()

    await wrapper.find('input[placeholder="输入管理员账号或邮箱"]').setValue('admin')
    await wrapper.find('input[placeholder="输入管理员密码"]').setValue('Root123456')
    await submitForm(wrapper)

    expect(mocks.adminLogin).toHaveBeenCalledWith('admin', 'Root123456')
    expect(mocks.routerReplace).toHaveBeenCalledWith('/admin')
  })

  it('shows friendly message when login fails', async () => {
    mocks.adminLogin.mockRejectedValue(new Error('账号不存在或者密码错误'))
    const wrapper = renderView()

    await wrapper.find('input[placeholder="输入管理员账号或邮箱"]').setValue('admin')
    await wrapper.find('input[placeholder="输入管理员密码"]').setValue('Wrong123456')
    await submitForm(wrapper)

    expect(mocks.messageError).toHaveBeenCalled()
  })

  it('remembers identifier when remember is checked', async () => {
    mocks.adminLogin.mockResolvedValue({ data: { access_token: 'admin-token' } })
    const wrapper = renderView()

    await wrapper.find('input[placeholder="输入管理员账号或邮箱"]').setValue('admin')
    await wrapper.find('input[placeholder="输入管理员密码"]').setValue('Root123456')
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await submitForm(wrapper)

    expect(localStorage.getItem('admin_remember_identifier')).toBe('admin')
  })
})
