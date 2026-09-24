import { customerHubClient } from './clients'
import { createCustomerHubApi } from './customerHubContract'

export const {
  listWorkbench, listQualificationQueue, getQualificationContext, submitQualificationDecision, listCustomerEvidence,
  listCustomers, getCustomer, listCustomerTimeline,
  getAcquisitionProfile, saveAcquisitionProfile, listSearchJobs, createSearchJob, requeueSearchJob, listSearchJobResults,
  createPublicPoolBatch, listResearchTasks, getResearchTask, reviewResearchTask,
  getPublicPoolRules, savePublicPoolRules, previewPublicPoolRules, createConfiguredPublicPoolBatch,
  listOpportunities, updateOpportunity, listActions, updateAction,
  getWorkbenchOverview, getEvaluationRun, createEvaluationRun, createCustomerAction,
  listProfileRevisions, createProfileRevision, listProfileSuggestions, decideProfileSuggestion,
  listCustomerConversations, listConversationMessages, listPendingBindings, createConversationBinding,
  createAnalysisJob, getAnalysisJob,
  listCustomerOrders, getCustomerOrder, getOrderAnalytics, getReorderWindows,
  listMonitorSubscriptions, createMonitorSubscription, patchMonitorSubscription, runMonitorSubscription,
  listMonitorEvents, decideMonitorEvent,
  listMaintenancePlans, createMaintenancePlan, patchMaintenancePlan, rescheduleOccurrence, getMaintenanceCalendar,
  listSampleCases, createSampleCase, getSampleCase, patchSampleCase, createShipmentOrderLink,
  listCampaigns, createCampaign, publishCampaign, transitionCampaign, previewCampaign, createCampaignActions,
} = createCustomerHubApi(customerHubClient)
