import { salesAutomationClient } from './clients'

export const getAcquisitionProfile = () => salesAutomationClient.get('/profile')
export const saveAcquisitionProfile = payload => salesAutomationClient.put('/profile', payload)

export const getSearchJobs = params => salesAutomationClient.get('/search-jobs', { params })
export const createSearchJob = payload => salesAutomationClient.post('/search-jobs', payload)
export const requeueSearchJob = id => salesAutomationClient.post(`/search-jobs/${id}/requeue`)

export const getLeads = params => salesAutomationClient.get('/leads', { params })
export const getLead = id => salesAutomationClient.get(`/leads/${id}`)
export const approveLead = id => salesAutomationClient.post(`/leads/${id}/approve`)
