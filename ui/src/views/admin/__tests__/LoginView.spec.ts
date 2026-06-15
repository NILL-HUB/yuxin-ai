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

const inputStub = {
  props: ['modelValue', 'placeholder', 'type', 'size'],
  emits: ['update:modelValue'],
  template: '<input :type="type || \'text\'" :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const buttonStub = {
  props: ['loading', 'size', 'type', 'long'],
  emits: ['click'],
  template: '<button type="button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>',
}

const renderView = () => {
  return mount(AdminLoginView, {
    global: {
      stubs: {
        'a-input': inputStub,
        'a-input-password': inputStub,
        'a-button': buttonStub,
        'icon-lock': true,
        'icon-user': true,
      },
    },
  })
}

describe('AdminLoginView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders admin login form', () => {
    const wrapper = renderView()

    expect(wrapper.text()).toContain('管理控制台')
    expect(wrapper.find('input[placeholder="管理员账号或邮箱"]').exists()).toBe(true)
    expect(wrapper.find('input[placeholder="管理员密码"]').exists()).toBe(true)
  })

  it('validates required fields before login', async () => {
    const wrapper = renderView()

    await wrapper.find('button').trigger('click')

    expect(mocks.adminLogin).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请输入管理员账号或邮箱和密码')
  })

  it('logs in and redirects to admin dashboard', async () => {
    mocks.adminLogin.mockResolvedValue({ data: { access_token: 'admin-token' } })
    const wrapper = renderView()

    await wrapper.find('input[placeholder="管理员账号或邮箱"]').setValue('admin')
    await wrapper.find('input[placeholder="管理员密码"]').setValue('Root123456')
    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(mocks.adminLogin).toHaveBeenCalledWith('admin', 'Root123456')
    expect(mocks.routerReplace).toHaveBeenCalledWith('/admin')
  })

  it('shows friendly message when login fails', async () => {
    mocks.adminLogin.mockRejectedValue(new Error('账号不存在或者密码错误'))
    const wrapper = renderView()

    await wrapper.find('input[placeholder="管理员账号或邮箱"]').setValue('admin')
    await wrapper.find('input[placeholder="管理员密码"]').setValue('Wrong123456')
    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(mocks.messageError).toHaveBeenCalled()
  })
})
