import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from '@/App.vue'
import { i18n } from '@/i18n'
import router from '@/router'
import { installArco } from '@/plugins/arco'
import { AUTH_REQUIRED_EVENT } from '@/utils/request'
import { redirectToLogin } from '@/utils/login-redirect'

import '@arco-design/web-vue/dist/arco.css'
import '@/assets/styles/main.css'
import '@/assets/styles/ai-chat-ui.css'
import '@/theme/theme.css'

// 初始化主题（挂载前设置 data-theme/arco-theme，避免首屏闪烁）
import { applyThemeToDom } from '@/theme'
applyThemeToDom()

const app = createApp(App)

app.use(createPinia())
app.use(i18n)
app.use(router)
installArco(app)

// 全局登录态失效处理：任一接口返回 401（token 过期/被清）时统一跳登录页，
// 不再由各布局弹登录弹窗。redirectToLogin 内部会过滤已在登录页/已登录场景。
if (typeof window !== 'undefined') {
  window.addEventListener(AUTH_REQUIRED_EVENT, () => {
    redirectToLogin()
  })
}

app.mount('#app')
