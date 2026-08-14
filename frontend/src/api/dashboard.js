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

// AI 每日问候：模型调用可能较慢，单请求放宽超时；suppressToast——开屏第一句问候
// 不该弹错误条，失败由调用方静默降级本地文案
export function fetchGreeting(payload) {
  return dashboardClient.post('/greeting', payload, {
    showLoading: false,
    timeout: 45000,
    suppressToast: true,
  })
}
