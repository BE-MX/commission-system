import { systemClient as sysApi } from './clients'

export function getDictTypes(config = {}) {
  return sysApi.get('/dict-types', { ...config, showLoading: false })
}

export function getDictItems(type, onlyActive = false, config = {}) {
  return sysApi.get('/dicts', { ...config, params: { type, only_active: onlyActive }, showLoading: false })
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
