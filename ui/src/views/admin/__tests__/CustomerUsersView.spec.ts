import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, inject, onMounted, provide, ref } from 'vue'
import CustomerUsersView from '@/views/admin/CustomerUsersView.vue'

const mocks = vi.hoisted(() => ({
  listCustomerUsers: vi.fn(),
  disableCustomerUser: vi.fn(),
  enableCustomerUser: vi.fn(),
  revokeCustomerUserSessions: vi.fn(),
  listUserAppAssignments: vi.fn(),
  assignAppsToUser: vi.fn(),
  revokeUserAppAssignment: vi.fn(),
  listAdminApps: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('@/services/admin-customer-users', () => ({
  listCustomerUsers: mocks.listCustomerUsers,
  disableCustomerUser: mocks.disableCustomerUser,
  enableCustomerUser: mocks.enableCustomerUser,
  revokeCustomerUserSessions: mocks.revokeCustomerUserSessions,
}))

vi.mock('@/services/admin-app-assignments', () => ({
  listUserAppAssignments: mocks.listUserAppAssignments,
  assignAppsToUser: mocks.assignAppsToUser,
  revokeUserAppAssignment: mocks.revokeUserAppAssignment,
}))

vi.mock('@/services/admin-apps', () => ({
  listAdminApps: mocks.listAdminApps,
}))

vi.mock('@arco-design/web-vue', () => ({
  Message: {
    success: mocks.messageSuccess,
    error: mocks.messageError,
  },
}))

const inputStub = {
  props: ['modelValue', 'placeholder'],
  emits: ['update:modelValue'],
  template: '<input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const selectStub = {
  props: {
    modelValue: { default: null },
    options: { default: () => [] },
    multiple: { type: Boolean, default: false },
    allowSearch: { type: Boolean, default: false },
    placeholder: { type: String, default: '' },
  },
  emits: ['update:modelValue'],
  template: `
    <select v-if="!multiple" :value="modelValue" @change="$emit('update:modelValue', $event.target.value)">
      <option v-for="option in (options || [])" :key="option.value" :value="option.value">{{ option.label }}</option>
    </select>
    <input v-else type="text" :value="(modelValue || []).join(',')" :placeholder="placeholder" @input="$emit('update:modelValue', $event.target.value ? $event.target.value.split(',') : [])" />
  `,
}

const buttonStub = {
  props: ['loading', 'size', 'type', 'status', 'disabled'],
  emits: ['click'],
  template: '<button type="button" :disabled="loading || disabled" @click="$emit(\'click\')"><slot /></button>',
}

// Table stub that collects cell slots from a-table-column via provide/inject
const tableStub = defineComponent({
  props: ['data', 'columns', 'loading', 'pagination', 'bordered', 'rowKey', 'size'],
  setup(props, { slots }) {
    const cellSlots = ref<Array<(props: { record: Record<string, unknown> }) => unknown>>([])
    provide('cellSlots', cellSlots)
    return () => h('div', { class: 'a-table' }, [
      h('div', { style: 'display:none' }, slots.columns?.()),
      ...(props.data || []).map((row: Record<string, unknown>) =>
        h('div', { class: 'table-row', 'data-id': row.id },
          cellSlots.value.map(cellSlot =>
            h('div', { class: 'table-cell' }, cellSlot({ record: row }) as unknown as import('vue').VNode)
          )
        )
      )
    ])
  }
})

const tableColumnStub = defineComponent({
  props: ['title', 'width'],
  setup(props, { slots }) {
    const cellSlots = inject<import('vue').Ref<Array<(props: { record: Record<string, unknown> }) => unknown>>>('cellSlots', ref([]))
    onMounted(() => {
      if (slots.cell) {
        cellSlots.value.push(slots.cell as (props: { record: Record<string, unknown> }) => unknown)
      }
    })
    return () => null
  }
})

const user = {
  id: 'user-1',
  email: 'user@example.com',
  name: 'User One',
  avatar: '',
  status: 'active' as const,
  is_online: true,
  disabled_at: null,
  disabled_by: null,
  disabled_reason: '',
  last_login_at: 1893456000,
  last_login_ip: '127.0.0.1',
  created_at: 1861920000,
}

const disabledUser = {
  ...user,
  id: 'user-2',
  email: 'disabled@example.com',
  name: 'Disabled User',
  status: 'disabled' as const,
  is_online: false,
  disabled_reason: 'risk',
}

const renderView = async () => {
  mocks.listCustomerUsers.mockResolvedValue({
    list: [user, disabledUser],
    paginator: { total_record: 2, total_page: 1, current_page: 1, page_size: 20 },
  })
  mocks.listUserAppAssignments.mockResolvedValue({
    list: [{ id: 'assignment-1', app_id: 'app-1', account_id: 'user-1', assigned_by: 'admin-1', status: 'active', assigned_at: 1893456000, revoked_at: null, app: { id: 'app-1', name: '合同审查助手', icon: '', description: '', status: 'published', is_public: false } }],
  })
  mocks.listAdminApps.mockResolvedValue({ list: [{ id: 'app-2', name: 'App 2', icon: '', description: '', status: 'published', is_public: false }] })
  const wrapper = mount(CustomerUsersView, {
    global: {
      stubs: {
        'a-input': inputStub,
        'a-select': selectStub,
        'a-button': buttonStub,
        'a-table': tableStub,
        'a-table-column': tableColumnStub,
        'a-drawer': {
          props: ['visible', 'width', 'title'],
          emits: ['cancel'],
          template: '<div v-if="visible" class="a-drawer"><slot /></div>',
        },
        'a-pagination': {
          props: ['total', 'current', 'pageSize', 'showTotal', 'showPageSize', 'pageSizeOptions'],
          template: '<div class="a-pagination">共 {{ total }} 个用户</div>',
        },
        'a-avatar': { template: '<span class="a-avatar"><slot /></span>' },
        'a-tag': { template: '<span class="a-tag"><slot /></span>' },
        'a-space': { template: '<div class="a-space"><slot /></div>' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('CustomerUsersView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads and renders customer users', async () => {
    const wrapper = await renderView()

    expect(mocks.listCustomerUsers).toHaveBeenCalledWith({ keyword: '', status: '', current_page: 1, page_size: 20 })
    expect(wrapper.text()).toContain('用户管理')
    expect(wrapper.text()).toContain('user@example.com')
    expect(wrapper.text()).toContain('disabled@example.com')
    expect(wrapper.text()).toContain('共 2 个用户')
  })

  it('searches with keyword', async () => {
    const wrapper = await renderView()

    await wrapper.find('input[placeholder="搜索邮箱或名称"]').setValue('demo')
    await wrapper.findAll('button').find((button) => button.text() === '查询')?.trigger('click')
    await flushPromises()

    expect(mocks.listCustomerUsers).toHaveBeenLastCalledWith({ keyword: 'demo', status: '', current_page: 1, page_size: 20 })
  })

  it('disables active users and reloads list', async () => {
    mocks.disableCustomerUser.mockResolvedValue({ data: { ...user, status: 'disabled' } })
    const wrapper = await renderView()

    await wrapper.findAll('button').find((button) => button.text() === '禁用')?.trigger('click')
    await flushPromises()

    expect(mocks.disableCustomerUser).toHaveBeenCalledWith('user-1', '后台管理员禁用')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('用户已禁用')
    expect(mocks.listCustomerUsers).toHaveBeenCalledTimes(2)
  })

  it('enables disabled users', async () => {
    mocks.enableCustomerUser.mockResolvedValue({ data: { ...disabledUser, status: 'active' } })
    const wrapper = await renderView()

    await wrapper.findAll('button').find((button) => button.text() === '解禁')?.trigger('click')
    await flushPromises()

    expect(mocks.enableCustomerUser).toHaveBeenCalledWith('user-2')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('用户已解禁')
  })

  it('revokes customer user sessions', async () => {
    mocks.revokeCustomerUserSessions.mockResolvedValue({ revoked_sessions: 2 })
    const wrapper = await renderView()

    await wrapper.findAll('button').find((button) => button.text() === '踢下线')?.trigger('click')
    await flushPromises()

    expect(mocks.revokeCustomerUserSessions).toHaveBeenCalledWith('user-1')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('已踢下线 2 个会话')
  })

  it('loads assignments and assigns app to user', async () => {
    mocks.assignAppsToUser.mockResolvedValue({ assigned: 1, reactivated: 0, skipped: 0, list: [] })
    const wrapper = await renderView()

    await wrapper.findAll('button').find((button) => button.text() === '分配应用')?.trigger('click')
    await flushPromises()
    expect(mocks.listUserAppAssignments).toHaveBeenCalledWith('user-1')
    expect(wrapper.text()).toContain('合同审查助手')

    await wrapper.find('.a-drawer input').setValue('app-2')
    await wrapper.findAll('button').find((button) => button.text() === '确认分配')?.trigger('click')
    await flushPromises()

    expect(mocks.assignAppsToUser).toHaveBeenCalledWith('user-1', ['app-2'])
    expect(mocks.messageSuccess).toHaveBeenCalledWith('应用已分配')
  })

  it('revokes assigned app from user', async () => {
    mocks.revokeUserAppAssignment.mockResolvedValue({ id: 'assignment-1', status: 'revoked' })
    const wrapper = await renderView()

    await wrapper.findAll('button').find((button) => button.text() === '分配应用')?.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '撤销')?.trigger('click')
    await flushPromises()

    expect(mocks.revokeUserAppAssignment).toHaveBeenCalledWith('user-1', 'assignment-1')
    expect(mocks.messageSuccess).toHaveBeenCalledWith('应用分配已撤销')
  })
})
