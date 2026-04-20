import request from './request'

export function getEmployeeList(params) {
  return request.get('/employee/list', { params })
}

export function setEmployeeAttribute(data) {
  return request.post('/employee/attribute', data)
}

export function getAttributeHistory(params) {
  return request.get('/employee/attribute/history', { params })
}

export function importEmployeeAttributes(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/employee/attribute/import', formData)
}
