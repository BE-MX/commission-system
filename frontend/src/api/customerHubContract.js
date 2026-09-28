/** 业务写请求统一携带 Idempotency-Key（用户+路由+资源范围由调用方生成）。 */
export function withIdempotency(config = {}, key) {
  return { ...config, headers: { ...(config.headers || {}), 'Idempotency-Key': key } }
}

export function createCustomerHubApi(client) {
  return {
    listWorkbench: params => client.get('/workbench', { params, showLoading: false }),
    listQualificationQueue: params => client.get('/qualification-queue', { params, showLoading: false }),
    getQualificationContext: taskId => client.get(`/qualification-queue/${taskId}`, { showLoading: false }),
    submitQualificationDecision: (taskId, payload) => client.post(`/qualification-queue/${taskId}/decision`, payload),
    listCustomerEvidence: (customerId, params) => client.get(`/customers/${customerId}/evidence`, { params, showLoading: false }),
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
    getPublicPoolRules: () => client.get('/public-pool/rules'),
    savePublicPoolRules: payload => client.put('/public-pool/rules', payload),
    previewPublicPoolRules: payload => client.post('/public-pool/rules/preview', payload),
    createConfiguredPublicPoolBatch: payload => client.post('/public-pool/rules/batches', payload),
    listResearchTasks: params => client.get('/research-tasks', { params, showLoading: false }),
    getResearchTask: taskId => client.get(`/research-tasks/${taskId}`),
    reviewResearchTask: (taskId, reviewStatus) => client.post(`/research-tasks/${taskId}/result-review`, { review_status: reviewStatus }),
    listOpportunities: params => client.get('/opportunities', { params, showLoading: false }),
    updateOpportunity: (opportunityId, payload) => client.put(`/opportunities/${opportunityId}`, payload),
    listActions: params => client.get('/actions', { params, showLoading: false }),
    updateAction: (actionId, payload) => client.put(`/actions/${actionId}`, payload),

    // ── 私海客户工作台（PCW-01..06，契约见 docs/requirements/private-customer-workbench-prototype/api-contracts.md）──
    // PCW-01 概览与评估
    getWorkbenchOverview: params => client.get('/workbench/overview', { params, showLoading: false }),
    getEvaluationRun: id => client.get(`/evaluation-runs/${id}`, { showLoading: false }),
    createEvaluationRun: (payload, idempotencyKey) => client.post('/evaluation-runs', payload, withIdempotency({}, idempotencyKey)),
    createCustomerAction: (customerId, payload, key) => client.post(`/customers/${customerId}/actions`, payload, withIdempotency({}, key)),
    // PCW-02 档案修订与建议
    listProfileRevisions: (customerId, params) => client.get(`/customers/${customerId}/profile-revisions`, { params, showLoading: false }),
    createProfileRevision: (customerId, payload, key) => client.post(`/customers/${customerId}/profile-revisions`, payload, withIdempotency({}, key)),
    listProfileSuggestions: (customerId, params) => client.get(`/customers/${customerId}/profile-suggestions`, { params, showLoading: false }),
    decideProfileSuggestion: (id, payload, key) => client.post(`/profile-suggestions/${id}/decisions`, payload, withIdempotency({}, key)),
    // PCW-03 会话、绑定与摘要
    listCustomerConversations: (customerId, params) => client.get(`/customers/${customerId}/conversations`, { params, showLoading: false }),
    listConversationMessages: (id, params) => client.get(`/conversations/${id}/messages`, { params, showLoading: false }),
    listPendingBindings: params => client.get('/conversation-bindings/pending', { params, showLoading: false }),
    createConversationBinding: (payload, key) => client.post('/conversation-bindings', payload, withIdempotency({}, key)),
    createAnalysisJob: (conversationId, key) => client.post(`/conversations/${conversationId}/analysis-jobs`, {}, withIdempotency({}, key)),
    getAnalysisJob: id => client.get(`/analysis-jobs/${id}`, { showLoading: false }),
    // PCW-04 订单与复购
    listCustomerOrders: (customerId, params) => client.get(`/customers/${customerId}/orders`, { params, showLoading: false }),
    getCustomerOrder: (customerId, orderId) => client.get(`/customers/${customerId}/orders/${orderId}`),
    getOrderAnalytics: (customerId, params) => client.get(`/customers/${customerId}/order-analytics`, { params, showLoading: false }),
    getReorderWindows: (customerId, params) => client.get(`/customers/${customerId}/reorder-windows`, { params, showLoading: false }),
    // PCW-05 监控订阅与事件
    listMonitorSubscriptions: customerId => client.get(`/customers/${customerId}/monitor-subscriptions`, { showLoading: false }),
    createMonitorSubscription: (customerId, payload, key) => client.post(`/customers/${customerId}/monitor-subscriptions`, payload, withIdempotency({}, key)),
    patchMonitorSubscription: (id, payload, key) => client.patch(`/monitor-subscriptions/${id}`, payload, withIdempotency({}, key)),
    runMonitorSubscription: (id, key) => client.post(`/monitor-subscriptions/${id}/runs`, {}, withIdempotency({}, key)),
    listMonitorEvents: (customerId, params) => client.get(`/customers/${customerId}/monitor-events`, { params, showLoading: false }),
    decideMonitorEvent: (id, payload, key) => client.post(`/monitor-events/${id}/decisions`, payload, withIdempotency({}, key)),
    // PCW-06 维护计划、样品与活动
    listMaintenancePlans: (customerId, params) => client.get(`/customers/${customerId}/maintenance-plans`, { params, showLoading: false }),
    createMaintenancePlan: (customerId, payload, key) => client.post(`/customers/${customerId}/maintenance-plans`, payload, withIdempotency({}, key)),
    patchMaintenancePlan: (id, payload, key) => client.patch(`/maintenance-plans/${id}`, payload, withIdempotency({}, key)),
    // 契约没有独立的 /maintenance-occurrences/{id}/reschedule；改约走 PATCH /maintenance-plans/{id}，
    // payload 携带 occurrence_id / occurrence_date / reason / expected_plan_version / expected_occurrence_version。
    rescheduleOccurrence: (planId, payload, key) => client.patch(`/maintenance-plans/${planId}`, payload, withIdempotency({}, key)),
    getMaintenanceCalendar: params => client.get('/maintenance-calendar', { params, showLoading: false }),
    listSampleCases: (customerId, params) => client.get(`/customers/${customerId}/sample-cases`, { params, showLoading: false }),
    createSampleCase: (customerId, payload, key) => client.post(`/customers/${customerId}/sample-cases`, payload, withIdempotency({}, key)),
    getSampleCase: id => client.get(`/sample-cases/${id}`),
    patchSampleCase: (id, payload, key) => client.patch(`/sample-cases/${id}`, payload, withIdempotency({}, key)),
    createShipmentOrderLink: (payload, key) => client.post('/shipment-order-links', payload, withIdempotency({}, key)),
    listCampaigns: params => client.get('/campaigns', { params, showLoading: false }),
    createCampaign: (payload, key) => client.post('/campaigns', payload, withIdempotency({}, key)),
    publishCampaign: (id, payload, key) => client.post(`/campaigns/${id}/publications`, payload, withIdempotency({}, key)),
    transitionCampaign: (id, payload, key) => client.post(`/campaigns/${id}/state-transitions`, payload, withIdempotency({}, key)),
    previewCampaign: id => client.post(`/campaigns/${id}/preview`),
    createCampaignActions: (id, payload, key) => client.post(`/campaigns/${id}/actions`, payload, withIdempotency({}, key)),
  }
}
