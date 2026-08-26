import { dingtalkClient } from './clients'

export function getGmvDailyConfig() {
  return dingtalkClient.get('/gmv-daily/config', { showLoading: false })
}

export function saveGmvDailyConfig(data) {
  return dingtalkClient.put('/gmv-daily/config', data, { loadingText: '正在保存日报配置...' })
}

export function previewGmvDailyReport(reportDate = null) {
  return dingtalkClient.post('/gmv-daily/preview', { report_date: reportDate }, { loadingText: '正在计算 GMV...' })
}

export function sendGmvDailyReport(reportDate = null, scope = 'all') {
  return dingtalkClient.post('/gmv-daily/send', { report_date: reportDate, scope }, { loadingText: '正在发送钉钉日报...' })
}
