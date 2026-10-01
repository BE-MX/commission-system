// 任务中心 API（拦截器已校验信封，调用方取数用 res.data）
import { taskClient } from './clients'

// 页面自带骨架/占位，不弹全局 loading 遮罩
const quiet = { showLoading: false }

export const listTasks = (config = {}) => taskClient.get('/items', { ...quiet, ...config })
export const getTask = (id, config = {}) => taskClient.get(`/items/${id}`, { ...quiet, ...config })
export const createTask = data => taskClient.post('/items', data)
export const updateTask = (id, data) => taskClient.patch(`/items/${id}`, data, quiet)
// 状态变更自己处理 409（子任务未结束需二次确认），不走拦截器的通用 toast
export const changeTaskStatus = (id, data) => taskClient.post(`/items/${id}/status`, data, { suppressToast: true })
export const moveTask = (id, parentId) => taskClient.post(`/items/${id}/move`, { parent_id: parentId })
export const deleteTask = id => taskClient.delete(`/items/${id}`)
export const restoreTask = id => taskClient.post(`/items/${id}/restore`)
export const listTrash = (config = {}) => taskClient.get('/trash', { ...quiet, ...config })
export const addTaskLink = (id, data) => taskClient.post(`/items/${id}/links`, data, quiet)
export const removeTaskLink = linkId => taskClient.delete(`/links/${linkId}`, quiet)
export const getTaskStats = (config = {}) => taskClient.get('/stats', { ...quiet, ...config })
export const listTaskModules = (config = {}) => taskClient.get('/modules', { ...quiet, ...config })
export const addCustomModule = title => taskClient.post('/modules/custom', { title })
export const removeCustomModule = key => taskClient.delete(`/modules/custom/${encodeURIComponent(key)}`)
export const draftTask = data => taskClient.post('/ai/draft', data, { ...quiet, timeout: 90000 })
export const getTodayBrief = (config = {}) => taskClient.get('/brief/today', { ...quiet, timeout: 90000, ...config })
