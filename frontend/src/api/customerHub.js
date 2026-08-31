import { customerHubClient } from './clients'

export const listCustomers = params => customerHubClient.get('/customers', { params, showLoading: false })
export const getCustomer = customerId => customerHubClient.get(`/customers/${customerId}`)
export const listCustomerTimeline = (customerId, params) => customerHubClient.get(`/customers/${customerId}/timeline`, { params, showLoading: false })

export const listSearchJobs = params => customerHubClient.get('/search-jobs', { params, showLoading: false })
export const getAcquisitionProfile = () => customerHubClient.get('/acquisition-profile')
export const saveAcquisitionProfile = payload => customerHubClient.put('/acquisition-profile', payload)
export const createSearchJob = payload => customerHubClient.post('/search-jobs', payload)
export const requeueSearchJob = jobId => customerHubClient.post(`/search-jobs/${jobId}/requeue`)
export const listResearchTasks = params => customerHubClient.get('/research-tasks', { params, showLoading: false })
export const getResearchTask = taskId => customerHubClient.get(`/research-tasks/${taskId}`)
export const createPublicPoolBatch = payload => customerHubClient.post('/public-pool/batches', payload)
export const reviewResearchTask = (taskId, reviewStatus) => customerHubClient.post(`/research-tasks/${taskId}/result-review`, { review_status: reviewStatus })

export const listOpportunities = params => customerHubClient.get('/opportunities', { params, showLoading: false })
export const updateOpportunity = (opportunityId, payload) => customerHubClient.put(`/opportunities/${opportunityId}`, payload)
export const listActions = params => customerHubClient.get('/actions', { params, showLoading: false })
export const updateAction = (actionId, payload) => customerHubClient.put(`/actions/${actionId}`, payload)
