import request from './request'

export function getEmployeeList(params) {
  return request.get('/employee/list', { params, showLoading: false })
}

export function setEmployeeAttribute(data) {
  return request.post('/employee/attribute', data, { loadingText: '正在保存...' })
}

export function getAttributeHistory(params) {
  return request.get('/employee/attribute/history', { params, showLoading: false })
}

export function importEmployeeAttributes(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/employee/attribute/import', formData, { loadingText: '正在导入...' })
}
