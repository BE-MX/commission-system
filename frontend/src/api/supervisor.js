import request from './request'

export function getSupervisorList(params) {
  return request.get('/supervisor/list', { params, showLoading: false })
}

export function setSupervisorRelation(data) {
  return request.post('/supervisor/relation', data, { loadingText: '正在保存...' })
}

export function getSupervisorHistory(params) {
  return request.get('/supervisor/history', { params, showLoading: false })
}

export function importSupervisorRelations(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/supervisor/import', formData, { loadingText: '正在导入...' })
}
