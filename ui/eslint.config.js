import pluginVue from 'eslint-plugin-vue'
import vueTsEslintConfig from '@vue/eslint-config-typescript'
import skipFormatting from '@vue/eslint-config-prettier/skip-formatting'

export default [
  {
    name: 'app/files-to-lint',
    files: ['**/*.{ts,mts,tsx,vue}'],
  },
  {
    name: 'app/files-to-ignore',
    // .d.ts 是类型声明文件，使用 any 做 shim 是标准做法；tmp_* 是临时构建产物
    ignores: ['**/dist/**', '**/coverage/**', '**/node_modules/**', '**/*.d.ts', '**/tmp_*'],
  },
  ...pluginVue.configs['flat/essential'],
  ...vueTsEslintConfig(),
  skipFormatting,
  {
    name: 'app/no-unused-vars-settings',
    rules: {
      // _ 前缀参数/变量是刻意保留的占位符（如 rest 解构排除项、未用回调参数）
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', ignoreRestSiblings: true },
      ],
    },
  },
  {
    name: 'app/scripts-node-env',
    files: ['scripts/*.mjs'],
    languageOptions: {
      globals: {
        process: 'readonly',
        console: 'readonly',
        __dirname: 'readonly',
      },
    },
  },
]
