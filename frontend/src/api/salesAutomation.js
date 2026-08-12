import { salesAutomationClient } from './clients'

export const getAcquisitionProfile = () => salesAutomationClient.get('/profile')
export const saveAcquisitionProfile = payload => salesAutomationClient.put('/profile', payload)

export const getSearchJobs = params => salesAutomationClient.get('/search-jobs', { params })
export const createSearchJob = payload => salesAutomationClient.post('/search-jobs', payload)
export const requeueSearchJob = id => salesAutomationClient.post(`/search-jobs/${id}/requeue`)

export const getLeads = params => salesAutomationClient.get('/leads', { params })
export const getLead = id => salesAutomationClient.get(`/leads/${id}`)
export const approveLead = id => salesAutomationClient.post(`/leads/${id}/approve`)

export const getPublicPoolAudit = () => salesAutomationClient.get('/public-pool/audit')
export const refreshPublicPoolAudit = () => salesAutomationClient.post('/public-pool/audit/refresh')
export const createPublicPoolBatch = payload => salesAutomationClient.post('/public-pool/batches', payload)
export const getPublicPoolTasks = params => salesAutomationClient.get('/public-pool/tasks', { params })
export const getPublicPoolTask = id => salesAutomationClient.get(`/public-pool/tasks/${id}`)
export const approvePublicPoolTask = id => salesAutomationClient.post(`/public-pool/tasks/${id}/approve`)
export const rejectPublicPoolTask = (id, reason) => salesAutomationClient.post(`/public-pool/tasks/${id}/reject`, { reason })
