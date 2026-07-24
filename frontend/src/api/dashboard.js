// 工作台布局配置 API（响应拦截器已解包信封，调用方取数用 res.data）
// 三个请求都 showLoading:false——布局配置是工作台的静默旁路，不该弹全局 loading
import { dashboardClient } from './clients'

export function getDashboardPreference() {
  return dashboardClient.get('/preference', { showLoading: false })
}

export function saveDashboardPreference(prefs) {
  return dashboardClient.put('/preference', prefs, { showLoading: false })
}

export function resetDashboardPreference() {
  return dashboardClient.delete('/preference', { showLoading: false })
}
