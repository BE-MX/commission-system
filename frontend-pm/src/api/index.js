// PM Hub 端点函数（与 backend/app/pm/router.py 一一对应）

import { api } from './client.js'

export const entry = (username) => api.post('/api/pm/entry', { username }, { silent: true })
export const fetchMe = () => api.get('/api/pm/me')
export const fetchMembers = () => api.get('/api/pm/members')
export const fetchDashboard = () => api.get('/api/pm/dashboard')

export const fetchMaterials = () => api.get('/api/pm/materials')
export const createMaterial = (data) => api.post('/api/pm/materials', data)
export const fetchMaterial = (id) => api.get(`/api/pm/materials/${id}`)
export const updateMaterial = (id, data) => api.put(`/api/pm/materials/${id}`, data)
export const deleteMaterial = (id) => api.del(`/api/pm/materials/${id}`)

export const uploadVersion = (id, file, changeNote) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('change_note', changeNote || '')
  return api.postForm(`/api/pm/materials/${id}/versions`, formData)
}
export const deleteVersion = (versionId) => api.del(`/api/pm/versions/${versionId}`)
export const fetchFileLink = (versionId, disposition = 'attachment') =>
  api.get(`/api/pm/versions/${versionId}/file-link?disposition=${disposition}`)
export const retryDiff = (versionId) => api.post(`/api/pm/versions/${versionId}/retry-diff`)

export const fetchTasks = (params = {}) => {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString()
  return api.get(`/api/pm/tasks${qs ? `?${qs}` : ''}`)
}
export const createTask = (data) => api.post('/api/pm/tasks', data)
export const updateTask = (id, data) => api.put(`/api/pm/tasks/${id}`, data)
export const deleteTask = (id) => api.del(`/api/pm/tasks/${id}`)

export const fetchActivity = (params = {}) => {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null)).toString()
  return api.get(`/api/pm/activity${qs ? `?${qs}` : ''}`)
}
