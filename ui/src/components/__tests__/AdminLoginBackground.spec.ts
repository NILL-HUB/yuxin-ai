import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AdminLoginBackground from '@/components/admin/AdminLoginBackground.vue'

describe('AdminLoginBackground', () => {
  it('renders more evenly distributed breathing particles without movement offsets', () => {
    const wrapper = mount(AdminLoginBackground)
    const particles = wrapper.findAll('.background-particle')
    const firstParticleStyle = particles[0]?.attributes('style') ?? ''

    expect(particles).toHaveLength(14)
    expect(firstParticleStyle).not.toContain('--drift-x')
    expect(firstParticleStyle).not.toContain('--drift-y')
    expect(firstParticleStyle).toContain('--particle-scale')
    expect(firstParticleStyle).toContain('opacity: 0.14;')
    expect(firstParticleStyle).toContain('transform: scale(0.88);')
  })
})
