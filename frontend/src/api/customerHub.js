import { customerHubClient } from './clients'
import { createCustomerHubApi } from './customerHubContract'

export const {
  listCustomers, getCustomer, listCustomerTimeline,
  getAcquisitionProfile, saveAcquisitionProfile, listSearchJobs, createSearchJob, requeueSearchJob, listSearchJobResults,
  createPublicPoolBatch, listResearchTasks, getResearchTask, reviewResearchTask,
  listOpportunities, updateOpportunity, listActions, updateAction,
} = createCustomerHubApi(customerHubClient)
