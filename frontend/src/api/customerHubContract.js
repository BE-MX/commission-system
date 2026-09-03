export function createCustomerHubApi(client) {
  return {
    listCustomers: params => client.get('/customers', { params, showLoading: false }),
    getCustomer: customerId => client.get(`/customers/${customerId}`),
    listCustomerTimeline: (customerId, params) => client.get(`/customers/${customerId}/timeline`, { params, showLoading: false }),
    getAcquisitionProfile: () => client.get('/acquisition-profile'),
    saveAcquisitionProfile: payload => client.put('/acquisition-profile', payload),
    listSearchJobs: params => client.get('/search-jobs', { params, showLoading: false }),
    createSearchJob: payload => client.post('/search-jobs', payload),
    requeueSearchJob: jobId => client.post(`/search-jobs/${jobId}/requeue`),
    listSearchJobResults: (jobId, params) => client.get(`/search-jobs/${jobId}/results`, { params, showLoading: false }),
    createPublicPoolBatch: payload => client.post('/public-pool/batches', payload),
    listResearchTasks: params => client.get('/research-tasks', { params, showLoading: false }),
    getResearchTask: taskId => client.get(`/research-tasks/${taskId}`),
    reviewResearchTask: (taskId, reviewStatus) => client.post(`/research-tasks/${taskId}/result-review`, { review_status: reviewStatus }),
    listOpportunities: params => client.get('/opportunities', { params, showLoading: false }),
    updateOpportunity: (opportunityId, payload) => client.put(`/opportunities/${opportunityId}`, payload),
    listActions: params => client.get('/actions', { params, showLoading: false }),
    updateAction: (actionId, payload) => client.put(`/actions/${actionId}`, payload),
  }
}
