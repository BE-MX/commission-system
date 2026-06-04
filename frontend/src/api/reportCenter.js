/**
 * 报表中心 API（Stimulsoft）
 *
 * 使用 reportClient（baseURL /api/report）。
 * 替代原 jmreport.js 的 token 中转模式，改为直接请求模板 + 数据。
 */
import { reportClient } from './clients'

/** 模板列表 */
export const getReportTemplates = () => reportClient.get('/templates')

/** 模板详情（含 .mrt 内容） */
export const getReportTemplate = (code) => reportClient.get(`/templates/${code}`)

/** 创建模板 */
export const createReportTemplate = (data) => reportClient.post('/templates', data)

/** 更新模板 */
export const updateReportTemplate = (code, data) => reportClient.put(`/templates/${code}`, data)

/** 删除模板 */
export const deleteReportTemplate = (code) => reportClient.delete(`/templates/${code}`)

/** 获取报表数据 JSON */
export const getReportData = (code, params) => reportClient.get(`/data/${code}`, { params })

/** 模板版本历史列表 */
export const getTemplateVersions = (code) => reportClient.get(`/templates/${code}/versions`)

/** 获取指定版本内容 */
export const getTemplateVersion = (code, version) => reportClient.get(`/templates/${code}/versions/${version}`)

/** 回滚到指定版本 */
export const rollbackTemplate = (code, version) => reportClient.post(`/templates/${code}/rollback/${version}`)

/** 切换模板启用/禁用 */
export const toggleTemplateStatus = (code, status) => reportClient.patch(`/templates/${code}/status`, { status })
