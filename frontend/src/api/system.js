import { systemClient as sysApi } from './clients'

export function getDictTypes() {
  return sysApi.get('/dict-types', { showLoading: false })
}

export function getDictItems(type, onlyActive = false) {
  return sysApi.get('/dicts', { params: { type, only_active: onlyActive }, showLoading: false })
}

export function createDictItem(data) {
  return sysApi.post('/dicts', data, { loadingText: '正在保存...' })
}

export function updateDictItem(id, data) {
  return sysApi.put(`/dicts/${id}`, data, { loadingText: '正在保存...' })
}

export function deleteDictItem(id) {
  return sysApi.delete(`/dicts/${id}`)
}

export default sysApi
