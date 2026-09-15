// 库存色块图工作台集成：按页面权限换取子站点 SSO 链接
import { colorworkClient } from './clients'

/** view: library / inventory / master → { url, views, ... }（错误由页面内提示，不弹全局 toast） */
export function getColorworkSsoLink(view) {
  return colorworkClient.get('/sso', { params: { view }, showLoading: false, suppressToast: true })
}
