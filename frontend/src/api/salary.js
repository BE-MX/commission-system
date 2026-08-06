// 薪资计算 API（响应拦截器已解包信封，调用方取数用 res.data）
import { salaryClient } from './clients'

// 职级赛道**不在前端写死**：GET /grades 的 schemes 字段是唯一真相源。
// 曾经这里硬编码过一份，后端加赛道时前端不会出现、也不报错（静默失效，
// 与 CLAUDE.md 红线 7 要防的是同一个模式，只是载体从 prompt 换成了前端常量）。
// 这里只留一个兜底 label：接口没返回时至少不显示成空白。
export function schemeLabel(schemes, code) {
  if (!code) return ''
  return schemes?.find(s => s.code === code)?.label || code
}

// 管理岗职级表填的是 std_salary（规则图上没有「底薪」栏），列表要按赛道切换展示列。
// 这条口径与后端 service._STD_SALARY_SCHEMES 双写，改动时两处都要动。
export const STD_SALARY_SCHEMES = ['manage']

// 金额展示统一两位小数。后端的 Decimal 过 JSON 会变成 float，3500.00 → 3500，
// 而工资表对分位是 3 月复算的验收标准，展示层不能丢。
export function money(v) {
  if (v === null || v === undefined || v === '') return '-'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(2) : String(v)
}

export const PROFILE_STATUS_OPTIONS = [
  { value: 'active', label: '在职' },
  { value: 'left', label: '离职' },
]

// --- 员工档案 ---

export function listProfiles(params) {
  return salaryClient.get('/profiles', { params })
}

export function getProfile(id) {
  return salaryClient.get(`/profiles/${id}`)
}

export function createProfile(data) {
  return salaryClient.post('/profiles', data)
}

export function updateProfile(id, data) {
  return salaryClient.put(`/profiles/${id}`, data)
}

// --- 规则配置 ---

export function listGrades(params) {
  return salaryClient.get('/grades', { params })
}

export function upsertGrade(data) {
  return salaryClient.post('/grades', data)
}

export function listParams(params) {
  return salaryClient.get('/params', { params })
}

export function updateParam(id, data) {
  return salaryClient.put(`/params/${id}`, data)
}

export function listDeptMappings() {
  return salaryClient.get('/dept-mappings')
}

export function upsertDeptMapping(data) {
  return salaryClient.post('/dept-mappings', data)
}
