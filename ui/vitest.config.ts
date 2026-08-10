import { fileURLToPath } from 'node:url'
import { mergeConfig, defineConfig, configDefaults } from 'vitest/config'
import viteConfig from './vite.config'

export default mergeConfig(
  viteConfig as Parameters<typeof mergeConfig>[0],
  defineConfig({
    test: {
      environment: 'jsdom',
      exclude: [...configDefaults.exclude, 'e2e/**'],
      include: ['src/**/__tests__/**/*.spec.ts'],
      setupFiles: ['src/test/setup.ts'],
      root: fileURLToPath(new URL('./', import.meta.url)),
      clearMocks: true,
      restoreMocks: true,
    }
  })
)
