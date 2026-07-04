import { computed } from 'vue'
import { useRoute } from 'vue-router'

/**
 * 统一 admin/space 上下文（realm）检测。
 *
 * 检测规则：
 * - route.path 以 /admin/ 开头，或
 * - route.meta.realm === 'admin'
 *
 * 使用场景：
 * 节点信息面板、应用能力组件等需要在 admin/space 双上下文下
 * 切换数据源（admin 端点跨账号加载，space 端点仅加载当前账号）。
 *
 * @returns
 *   - realm: 'admin' | 'space'  当前 realm 字符串
 *   - isAdmin: ComputedRef<boolean>  是否为 admin 上下文
 */
export const useRealm = () => {
  const route = useRoute()
  const isAdmin = computed(
    () => route.path.startsWith('/admin/') || route.meta.realm === 'admin',
  )
  const realm = computed<'admin' | 'space'>(() => (isAdmin.value ? 'admin' : 'space'))
  return { realm, isAdmin }
}
