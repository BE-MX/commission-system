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

// --- 月度批次 ---

// 状态与步骤条顺序。后端 period_service.STATUS_ORDER 是真相源，这里只是渲染顺序，
// 文案一律用接口回的 status_label——两边各写一份中文，改一处就会对不上。
export const PERIOD_STATUS_ORDER = [
  'draft', 'attendance_synced', 'imported', 'calculated', 'reviewing', 'confirmed',
]

export function listPeriods(params) {
  return salaryClient.get('/periods', { params })
}

export function getPeriod(id) {
  return salaryClient.get(`/periods/${id}`)
}

export function listPeriodEvents(id) {
  return salaryClient.get(`/periods/${id}/events`)
}

export function createPeriod(data) {
  return salaryClient.post('/periods', data)
}

export function updatePeriodWorkday(id, data) {
  return salaryClient.put(`/periods/${id}/workday`, data)
}

// 锁定走 /confirm 而非 /transition（权限也从 write 变 admin）——这条特例由接口的
// next_steps[].endpoint 告知，调用方按它派发，不要在前端硬编码状态判断。
export function transitionPeriod(id, data) {
  return salaryClient.post(`/periods/${id}/transition`, data)
}

export function confirmPeriod(id, data) {
  return salaryClient.post(`/periods/${id}/confirm`, data)
}

export function unlockPeriod(id, data) {
  return salaryClient.post(`/periods/${id}/unlock`, data)
}

// --- 计算 / 工资明细（M3-f）---

// 触发整批计算。并发护栏是批次的 status_version：409 = 批次被他人改过（刷新重试）；
// 400 = 状态不对或还有 blocking 异常，detail 文案由拦截器原样弹给用户。
export function calculatePeriod(id, data) {
  return salaryClient.post(`/periods/${id}/calculate`, data)
}

// 金额可能是 null（批次还没算过）；社保/公积金/缺勤/减项小计是**负数**，
// 与 HR 手头的工资表同构，展示层直接照显，不要取绝对值。
export function listRecords(id, params) {
  return salaryClient.get(`/periods/${id}/records`, { params })
}

// 人工改 5 个值列。body 只放真正要改的列：不传 = 不动，传 null = 清除人工覆盖
// （final 回落引擎值）——和考勤录入同一条规矩，整行 spread 会把别的列抹掉。
// 并发护栏是**行级**的 row_version（expected_row_version 必填），不是批次的
// status_version：409 只说明这一行被他人改过，别去刷新整个批次。
export function editRecordManual(id, employeeId, data) {
  return salaryClient.put(`/periods/${id}/records/${employeeId}`, data)
}

// --- 社保 / 公积金导入 ---

export function importPeriodFile(id, kind, file) {
  const fd = new FormData()
  fd.append('file', file)
  return salaryClient.post(`/periods/${id}/imports/${kind}`, fd)
}

export function listImportRows(id, kind, params) {
  return salaryClient.get(`/periods/${id}/imports/${kind}`, { params })
}

// --- 考勤 ---

// 66 人 × 2 片 = 132 次钉钉调用，实测跑一分钟出头。走 client 默认的 60s 会在
// 服务端仍在写库时把请求掐掉，界面显示「超时」而数据其实同步成功了——
// HR 于是重试，又是一分钟 + 一次限流额度。
export function syncAttendance(id, data) {
  return salaryClient.post(`/periods/${id}/attendance/sync`, data, { timeout: 300000 })
}

export function listAttendance(id, params) {
  return salaryClient.get(`/periods/${id}/attendance`, { params })
}

// data 只放**真正要改的字段**：漏传 = 不动，传 null = 清空。
// 把整行表单 spread 进来会让未编辑的 null 字段变成显式清空，
// 刚录的病假会被抹掉（少扣缺勤 + 白发全勤奖）。
export function upsertAttendance(id, employeeId, data) {
  return salaryClient.put(`/periods/${id}/attendance/${employeeId}`, data)
}

// --- 异常面板 ---

export function listAnomalies(id) {
  return salaryClient.get(`/periods/${id}/anomalies`)
}
