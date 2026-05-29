/**
 * 积木报表（jimureport）集成 — 前端 API 封装。
 * 统一从 clients.js 取 reportClient，token 注入由 createApiClient 自动处理。
 *
 * 注意：与 @/api/report.js 区别 —— report.js 是方舟现有「提成报表导出」（/api/v1/report），
 * 本文件是 jimureport iframe Token 中转（/api/report）。
 */
import { reportClient } from './clients'

/** 获取报表访问 Token + jmreport 服务地址 */
export function getReportToken() {
  return reportClient.get('/token')
}

/** 获取指定报表的嵌入 URL（含 reportCode） */
export function getReportEmbedToken({ reportCode = null, mode = 'view' } = {}) {
  return reportClient.post('/token/for-embed', {
    report_code: reportCode,
    mode,
  })
}

/** 检查报表服务是否在线 */
export function checkReportHealth() {
  return reportClient.get('/health')
}
