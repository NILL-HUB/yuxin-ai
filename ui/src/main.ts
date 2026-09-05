import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from '@/App.vue'
import { i18n } from '@/i18n'
import router from '@/router'
import { installArco } from '@/plugins/arco'

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

app.mount('#app')
