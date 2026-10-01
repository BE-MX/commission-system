import { customerHubClient } from './clients'
import { createCustomerHubApi } from './customerHubContract'

export const {
  listWorkbench, listQualificationQueue, getQualificationContext, submitQualificationDecision, listCustomerEvidence,
  listCustomers, getCustomer, listCustomerTimeline, listCustomerServiceAssets, registerCustomerServiceAsset, revokeCustomerServiceAsset,
  getAcquisitionProfile, saveAcquisitionProfile, listSearchJobs, createSearchJob, requeueSearchJob, listSearchJobResults,
  createPublicPoolBatch, listResearchTasks, getResearchTask, reviewResearchTask,
  getPublicPoolRules, savePublicPoolRules, previewPublicPoolRules, createConfiguredPublicPoolBatch,
  listOpportunities, updateOpportunity, listActions, updateAction,
  listWorkbenchItems, getWorkItem, transitionWorkItem, admitDailyPlanItem, submitWorkItemFeedback,
  createWorkItemDelegation, transitionDelegation,
  getWorkbenchOverview, getEvaluationRun, createEvaluationRun, createCustomerAction,
  listProfileRevisions, createProfileRevision, listProfileSuggestions, decideProfileSuggestion,
  getCustomerEnrichment, requestCustomerEnrichment,
  listCustomerConversations, listConversationMessages, listPendingBindings, createConversationBinding,
  createAnalysisJob, getAnalysisJob,
  listCustomerOrders, getCustomerOrder, getOrderAnalytics, getReorderWindows,
  listMonitorSubscriptions, createMonitorSubscription, patchMonitorSubscription, runMonitorSubscription,
  listMonitorEvents, decideMonitorEvent,
  listMaintenancePlans, getMaintenancePlanSources, createMaintenancePlan, patchMaintenancePlan, rescheduleOccurrence, getMaintenanceCalendar,
  listSampleCases, createSampleCase, getSampleCase, patchSampleCase, createShipmentOrderLink,
  listCampaigns, createCampaign, publishCampaign, transitionCampaign, previewCampaign, createCampaignActions,
} = createCustomerHubApi(customerHubClient)
