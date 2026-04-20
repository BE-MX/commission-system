import request from './request'

export function getSupervisorList(params) {
  return request.get('/supervisor/list', { params })
}

export function setSupervisorRelation(data) {
  return request.post('/supervisor/relation', data)
}

export function getSupervisorHistory(params) {
  return request.get('/supervisor/history', { params })
}

export function importSupervisorRelations(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/supervisor/import', formData)
}
