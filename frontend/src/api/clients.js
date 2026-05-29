/**
 * 业务域 API client 集合。
 *
 * 所有 API 模块应从此处导入 client,不要自建 axios 实例,
 * 以保证 token 注入、loading、401 跳转、错误提示等行为一致。
 *
 * 注意: authClient 不在此处提供 — 登录/刷新有特殊语义
 * (401 不能跳转、需要 withCredentials),独立维护在 @/api/auth.js。
 */
import { createApiClient } from './request'

export const v1Client = createApiClient({ baseURL: '/api/v1' })
export const designClient = createApiClient({ baseURL: '/api/design' })
export const aiClient = createApiClient({ baseURL: '/api/ai', timeout: 120000 })
export const insightClient = createApiClient({ baseURL: '/api/insight', timeout: 90000 })
export const stockClient = createApiClient({ baseURL: '/api/stock', timeout: 90000 })
export const systemClient = createApiClient({ baseURL: '/api/system', timeout: 30000 })
export const assetClient = createApiClient({ baseURL: '/api/assets', timeout: 120000 })
export const colorClient = createApiClient({ baseURL: '/api/color', timeout: 120000 })
export const reportClient = createApiClient({ baseURL: '/api/report', timeout: 30000 })
